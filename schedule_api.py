#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招聘信息采集 - 定时任务调度 API
Flask 服务 + 定时调度器

启动方式：
  python schedule_api.py           # 仅 API（默认端口 5000）
  python schedule_api.py 8080      # 指定端口

API 接口：
  GET  /api/schedule               # 获取调度配置和状态
  POST /api/schedule               # 更新调度配置
  POST /api/crawl/now              # 立即触发一次采集
  GET  /api/status                 # 服务状态
"""
import os, sys, json, sqlite3, subprocess, threading, time, asyncio
from datetime import datetime

# 数据导入（爬虫完成后自动同步到数据库）
from import_data import import_jobs_incremental, import_gk_jobs_incremental

# VIP 自动匹配依赖
import hashlib
from match_db import pre_filter, get_db as _get_match_db
from match_ai import call_deepseek_match, analyze_resume_with_deepseek

# 允许外部进程调用时指定端口
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "schedule_config.json")
os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

# ── Flask 相关（延迟导入，避免未安装时影响 CLI 使用）─────────
from flask import Flask, jsonify, request

app = Flask(__name__)

# ── CORS 跨域支持 ────────────────────────────────────────
@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization,X-Admin-Token")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response

# ══════════════════════════════════════════════════════════
# 管理员密码（建议部署后通过环境变量覆盖）
# 示例：set ADMIN_PASSWORD=your_strong_password
# ══════════════════════════════════════════════════════════
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def check_admin(req):
    """验证管理员权限，返回 True/False"""
    token = req.headers.get("X-Admin-Token") or (req.get_json(silent=True) or {}).get("admin_token", "")
    return token == ADMIN_PASSWORD

def admin_required(f):
    """装饰器：保护需要管理员权限的接口"""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not check_admin(request):
            return jsonify({"error": "Unauthorized", "message": "需要管理员权限"}), 401
        return f(*args, **kwargs)
    return wrapper

# 新增：Token 校验接口（前端登录用）
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json() or {}
    pwd = data.get("password", "")
    if pwd == ADMIN_PASSWORD:
        return jsonify({"ok": True, "token": ADMIN_PASSWORD})
    return jsonify({"ok": False, "message": "密码错误"}), 401


# ── 调度状态（内存中）────────────────────────────────────
scheduler_running = False
scheduler_thread = None
last_run_time = None
last_run_count = 0
is_running = False  # 社招采集是否正在进行

# ── 考公采集状态 ──────────────────────────────────────────
GK_CONFIG_FILE = os.path.join(BASE_DIR, "data", "gk_schedule_config.json")
gk_is_running = False
gk_last_run_time = None
gk_last_run_count = 0

# ── VIP 自动匹配状态 ──────────────────────────────────────
VIP_CONFIG_FILE = os.path.join(BASE_DIR, "data", "vip_schedule_config.json")
vip_is_running = False
vip_last_run_time = None
vip_last_scan_count = 0
vip_last_notify_count = 0


# ══════════════════════════════════════════════════════════
# VIP 配置读写
# ══════════════════════════════════════════════════════════
def load_vip_config():
    if os.path.exists(VIP_CONFIG_FILE):
        with open(VIP_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "enabled": True,
        "interval_hours": 48,
        "last_run": None,
        "last_scan_count": 0,
        "last_notify_count": 0,
    }


def save_vip_config(cfg):
    with open(VIP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════
# VIP 自动匹配扫描
# ══════════════════════════════════════════════════════════
def do_vip_scan():
    """扫描所有有效VIP会员，对存储的简历执行AI匹配，>=60% 的生成通知"""
    global vip_is_running, vip_last_run_time, vip_last_scan_count, vip_last_notify_count

    if vip_is_running:
        print("[VIP] 上一次扫描尚未完成，跳过")
        return {"success": False, "message": "扫描正在进行中"}

    try:
        vip_is_running = True
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[VIP] {start_time} 开始自动匹配扫描...")

        db_path = os.path.join(BASE_DIR, "data", "jobs.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # 找出所有有效VIP会员
        now_str = datetime.utcnow().isoformat()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.id, u.username, u.vip_expired_at,
                   mr.id as resume_id, mr.resume_text, mr.parsed_json
            FROM users u
            LEFT JOIN member_resumes mr ON mr.user_id = u.id
            WHERE u.is_vip = 1 AND u.vip_expired_at > ?
              AND u.is_disabled = 0
        ''', (now_str,))
        vip_users = cursor.fetchall()

        if not vip_users:
            print("[VIP] 没有有效的VIP会员，跳过")
            conn.close()
            return {"success": True, "count": 0, "message": "没有有效的VIP会员"}

        total_scan = len(vip_users)
        total_notify = 0
        total_new_matches = 0

        for u_row in vip_users:
            user_id = u_row["id"]
            username = u_row["username"]
            resume_text = u_row["resume_text"]
            parsed_json = u_row.get("parsed_json", "{}")

            if not resume_text or not resume_text.strip():
                print(f"[VIP] 用户 {username}(#{user_id}) 尚未上传简历，跳过")
                continue

            # 尝试从已解析结果中获取技能
            try:
                parsed = json.loads(parsed_json) if parsed_json else {}
            except Exception:
                parsed = {}
            skills = parsed.get("skills", [])
            education = parsed.get("education", "")

            total_new_matches += 1
            all_recommendations = []

            for jt in ["社招", "公考"]:
                candidates = pre_filter(
                    skills=skills, cities=[],
                    salary_min=0, salary_max=999999,
                    education=education, job_type=jt, max_candidates=50
                )
                # 技能词为英文，数据库关键字为中文，匹配不上时回退宽泛搜索
                if not candidates and skills:
                    candidates = pre_filter(
                        skills=[], cities=[],
                        salary_min=0, salary_max=999999,
                        education=education, job_type=jt, max_candidates=50
                    )
                if not candidates:
                    continue

                resume_dict = {"skills": skills, "education": education,
                              "experience": "", "name": "", "major": "", "school": "",
                              "raw_text": resume_text}
                pref_dict = {"cities": [], "salary_min": 0, "salary_max": 999999,
                             "job_type": jt, "education_match": True}

                try:
                    ai_results, usage = asyncio.run(
                        call_deepseek_match(resume_dict, pref_dict, candidates)
                    )
                except Exception as e:
                    print(f"[VIP] AI匹配失败 {username}(#{user_id}) {jt}: {e}")
                    ai_results = []
                    for c in candidates[:10]:
                        ai_results.append({
                            "job_id": c.get("id", 0), "job_type": jt,
                            "title": c.get("title", ""), "company": c.get("company", ""),
                            "salary": c.get("salary", ""), "salary_raw": c.get("salary_raw", ""),
                            "salary_min": c.get("salary_min", 0), "salary_max": c.get("salary_max", 0),
                            "location": c.get("location", ""), "education": c.get("education", ""),
                            "platform": c.get("platform", ""), "link": c.get("link", ""),
                            "match_score": 50, "admission_probability": "中",
                            "reason": "AI服务暂时不可用", "advantages": [], "suggestions": []
                        })

                all_recommendations.extend(ai_results)

            all_recommendations.sort(key=lambda x: x.get("match_score", 0), reverse=True)
            top15 = all_recommendations[:15]

            high_prob_count = sum(1 for r in top15 if r.get("match_score", 0) >= 60)

            # 保存匹配结果
            result_json = json.dumps(top15, ensure_ascii=False)
            conn.execute(
                "INSERT INTO vip_match_results (user_id, resume_id, match_json, high_prob_count) VALUES (?, ?, ?, ?)",
                (user_id, u_row["resume_id"], result_json, high_prob_count)
            )
            conn.commit()

            # 高概率岗位 -> 生成通知记录
            if high_prob_count > 0:
                high_prob_jobs = [r for r in top15 if r.get("match_score", 0) >= 60]
                total_notify += 1
                print(f"[VIP] {username}(#{user_id}) 发现 {high_prob_count} 个高概率岗位")

                # 检查邮件配置，生成通知
                email_cfg = dict(conn.execute("SELECT * FROM email_config WHERE id=1").fetchone() or {})
                # 获取用户绑定的通知邮箱
                user_row = conn.execute("SELECT notify_email FROM users WHERE id=?", (user_id,)).fetchone()
                user_email = user_row["notify_email"] if user_row else ""
                if email_cfg.get("enabled") and email_cfg.get("smtp_host"):
                    _send_vip_email(email_cfg, username, high_prob_jobs, to_email=user_email)
                else:
                    # 生成模拟通知链接
                    _generate_mock_notification(conn, user_id, high_prob_jobs)

        conn.close()

        vip_last_run_time = start_time
        vip_last_scan_count = total_new_matches
        vip_last_notify_count = total_notify

        # 保存配置
        cfg = load_vip_config()
        cfg["last_run"] = start_time
        cfg["last_scan_count"] = total_new_matches
        cfg["last_notify_count"] = total_notify
        save_vip_config(cfg)

        msg = f"扫描完成：{total_scan}个会员，{total_new_matches}个匹配，{total_notify}个有高概率岗位"
        print(f"[VIP] {msg}")
        return {"success": True, "message": msg, "scan_count": total_new_matches, "notify_count": total_notify}

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[VIP] 扫描异常：{e}")
        return {"success": False, "message": str(e)}
    finally:
        vip_is_running = False


def _generate_mock_notification(conn, user_id, high_prob_jobs):
    """生成模拟邮件通知链接并记录到数据库中"""
    notification = {
        "type": "mock_email",
        "created_at": datetime.now().isoformat(),
        "jobs": [
            {
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "score": j.get("match_score", 0),
                "link": j.get("link", ""),
            }
            for j in high_prob_jobs
        ],
        "mock_url": f"/vip/notify/{user_id}?t={int(time.time())}",
    }
    # 将模拟链接记录到 user_actions
    conn.execute(
        "INSERT INTO user_actions (user_id, action, detail) VALUES (?, 'vip_notify', ?)",
        (user_id, json.dumps(notification, ensure_ascii=False))
    )
    conn.commit()


def _send_vip_email(email_cfg, username, high_prob_jobs, to_email=""):
    """发送VIP高概率岗位邮件通知"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        if not to_email or "@" not in to_email:
            print(f"[VIP] {username} 未绑定有效邮箱，跳过邮件发送")
            return False

        from datetime import datetime
        now_str = datetime.now().strftime("%Y年%m月d日 %H:%M")
        job_count = len(high_prob_jobs[:10])

        # 生成岗位列表（与即时匹配邮件保持一致的卡片样式）
        jobs_html = ""
        for j in high_prob_jobs[:10]:
            score = int(j.get("match_score", 0))
            title = j.get("title", "") or "未知职位"
            company = j.get("company", "")
            salary = j.get("salary", "") or j.get("salary_raw", "")
            location = j.get("location", "")
            platform = j.get("platform", "")
            link = j.get("link", "")
            reason = j.get("reason", "")

            if score >= 80:
                score_bg = "#E8F5EE"; score_color = "#1B7343"
            else:
                score_bg = "#FBF3E5"; score_color = "#9C6B3C"

            detail_lines = []
            if company: detail_lines.append(company)
            if salary: detail_lines.append(salary)
            if location: detail_lines.append(location)
            if platform: detail_lines.append(f"来源：{platform}")
            detail_str = " · ".join(detail_lines)

            jobs_html += f'''
        <div style="margin-bottom:16px;">
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr>
              <td style="padding-bottom:4px;">
                <span style="font-size:15px;font-weight:700;color:#333;">{title}</span>
                <span style="display:inline-block;margin-left:8px;background:{score_bg};color:{score_color};font-size:11px;font-weight:600;padding:2px 9px;border-radius:10px;">{score}%</span>
              </td>
            </tr>
{f'            <tr><td style="font-size:13px;color:#777;">{detail_str}</td></tr>' if detail_str else ''}
{f'            <tr><td style="font-size:12px;color:#999;margin-top:4px;line-height:1.5;">{reason}</td></tr>' if reason else ''}
{f'            <tr><td style="padding-top:8px;"><a href="{link}" target="_blank" style="color:#9C6B3C;font-size:12px;text-decoration:none;font-weight:600;">查看详情 &rarr;</a></td></tr>' if link else ''}
          </table>
        </div>
        <hr style="border:none;border-top:1px solid #E8DDD0;margin:14px 0;">'''

        html_body = f"""
    <div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
      <div style="background:linear-gradient(135deg,#FBF8F3,#F5E6D3);padding:24px;border-radius:12px 12px 0 0;">
        <h2 style="color:#9C6B3C;margin:0;font-size:20px;letter-spacing:0.5px;">JobBoard VIP</h2>
        <p style="color:#8B7355;margin:4px 0 0 0;font-size:13px;">智能招聘匹配系统 · 岗位推荐通知</p>
      </div>
      <div style="padding:24px;border:1px solid #E8DDD0;border-top:none;border-radius:0 0 12px 12px;">
        <p style="margin:0 0 16px;font-size:14px;color:#555;line-height:1.7;">
          {username}，您好<br>
          定时扫描为您发现了 <b style="color:#9C6B3C;">{job_count}</b> 个与您简历高度匹配的岗位（匹配度 &ge; 60%），请及时关注
        </p>
        {jobs_html}
        <div style="margin-top:16px;text-align:center;">
          <a href="http://localhost:8766" target="_blank" style="display:inline-block;background:#9C6B3C;color:#fff;text-decoration:none;font-size:13px;font-weight:500;padding:8px 24px;border-radius:6px;">登录 JobBoard 查看完整报告</a>
        </div>
        <hr style="border:none;border-top:1px solid #E8DDD0;margin:18px 0 10px;">
        <p style="font-size:11px;color:#AAA;margin:0;line-height:1.6;">此邮件由 JobBoard 智能招聘匹配系统自动发送 &middot; 请勿直接回复</p>
      </div>
    </div>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"JobBoard 岗位推荐：发现 {job_count} 个高匹配度岗位"
        msg["From"] = email_cfg["from_email"]
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
            server.login(email_cfg["smtp_user"], email_cfg["smtp_pass"])
            server.sendmail(email_cfg["from_email"], [to_email], msg.as_string())
        print(f"[VIP] Email sent to {username} ({to_email})")
        return True
    except Exception as e:
        print(f"[VIP] Email failed: {e}")
        return False
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "enabled": False,
        "interval_hours": 12,
        "keywords": ["软件工程师", "数据分析"],
        "last_run": None,
        "last_count": 0,
    }


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════
# 采集逻辑（子进程调用）
# ══════════════════════════════════════════════════════════
def do_crawl(keywords):
    """执行社招采集 —— 弹出独立窗口显示实时进度"""
    global is_running, last_run_time, last_run_count

    if is_running:
        return {"success": False, "message": "采集正在进行中"}

    kw_str = ",".join(keywords)
    script = os.path.join(BASE_DIR, "login_helper.py")

    # 准备日志目录
    log_dir = os.path.join(BASE_DIR, "data", "crawl_logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"crawl_{ts}.log")

    try:
        is_running = True
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[Scheduler] {start_time} 开始采集，关键词：{kw_str}")

        # 用 PowerShell 在新窗口中运行，Tee 同时输出到窗口 + 日志文件
        ps_cmd = (
            f'& "{sys.executable}" "{script}" --keywords "{kw_str}" --auto 2>&1 | '
            f'Tee-Object -FilePath "{log_file}"; '
            f'Write-Host "`n=== 采集完成 ===" -ForegroundColor Green; '
            f'Write-Host "日志文件: {log_file}"'
        )
        proc = subprocess.Popen(
            ["powershell", "-NoExit", "-NoProfile", "-Command", ps_cmd],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        proc.wait(timeout=300)

        # 从日志中提取累计条数
        count = 0
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if "当前累计" in line and "条" in line:
                    try:
                        count = int("".join(filter(str.isdigit, line.split("当前累计")[-1].split("条")[0].strip())))
                    except Exception:
                        pass
                elif "本次新增" in line and "条" in line and count == 0:
                    try:
                        count = int("".join(filter(str.isdigit, line.split("本次新增")[-1].split("条")[0].strip())))
                    except Exception:
                        pass

        # ── 将 JSON 数据同步到 SQLite 数据库 ──
        db_new = 0
        try:
            db_path = os.path.join(BASE_DIR, "data", "jobs.db")
            conn = sqlite3.connect(db_path)
            db_new = import_jobs_incremental(conn)
            conn.close()
            print(f"[Scheduler] 数据库同步完成，新增 {db_new} 条社招岗位")
        except Exception as e:
            print(f"[Scheduler] 数据库同步失败: {e}")

        last_run_time = start_time
        last_run_count = count

        # 更新配置文件
        cfg = load_config()
        cfg["last_run"] = start_time
        cfg["last_count"] = count
        save_config(cfg)

        print(f"[Scheduler] 采集完成：{count} 条 | 日志: {log_file}")

        return {
            "success": True,
            "count": count,
            "message": f"采集完成，共 {count} 条",
            "start_time": start_time,
        }

    except subprocess.TimeoutExpired:
        print("[Scheduler] 采集超时（5分钟）")
        return {"success": False, "message": "采集超时（5分钟）"}
    except Exception as e:
        print(f"[Scheduler] 采集异常：{e}")
        return {"success": False, "message": str(e)}
    finally:
        is_running = False


# ══════════════════════════════════════════════════════════
# 考公考编采集逻辑（子进程调用）
# ══════════════════════════════════════════════════════════
def do_gk_crawl(province_codes, keyword, year="2026", max_pages=None, delay=1.0):
    """执行考公考编采集 —— 弹出独立窗口显示实时进度"""
    global gk_is_running, gk_last_run_time, gk_last_run_count

    if gk_is_running:
        return {"success": False, "message": "考公采集正在进行中"}

    script = os.path.join(BASE_DIR, "gongkao_crawler.py")
    if not os.path.exists(script):
        return {"success": False, "message": "考公爬虫文件不存在"}

    prov_str = ",".join(province_codes) if province_codes else "all"
    kw_str = keyword or "公务员"

    # 准备日志目录
    log_dir = os.path.join(BASE_DIR, "data", "crawl_logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"gk_{ts}.log")

    try:
        gk_is_running = True
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[考公] {start_time} 开始采集，省份：{prov_str}，关键词：{kw_str}")

        # 构建参数
        args_str_parts = []
        if province_codes:
            for p in province_codes:
                args_str_parts.append(f'--province "{p}"')
        else:
            args_str_parts.append("--all")
        args_str_parts.append(f'--keyword "{kw_str}"')
        args_str_parts.append(f'--year "{year}"')
        if max_pages:
            args_str_parts.append(f'--max-pages {max_pages}')
        args_str_parts.append(f'--delay {delay}')
        args_str = " ".join(args_str_parts)

        # 用 PowerShell 在新窗口中运行，Tee 同时输出到窗口 + 日志文件
        ps_cmd = (
            f'& "{sys.executable}" "{script}" {args_str} 2>&1 | '
            f'Tee-Object -FilePath "{log_file}"; '
            f'Write-Host "`n=== 考公采集完成 ===" -ForegroundColor Green; '
            f'Write-Host "日志文件: {log_file}"'
        )
        proc = subprocess.Popen(
            ["powershell", "-NoExit", "-NoProfile", "-Command", ps_cmd],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        proc.wait(timeout=600)

        # 从日志提取结果
        count = 0
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if "采集完成，共" in line and "条有效记录" in line:
                    try:
                        count = int("".join(filter(str.isdigit, line.split("条有效记录")[0].split("共")[-1].strip())))
                    except Exception:
                        pass

        # ── 将 JSON 数据同步到 SQLite 数据库 ──
        db_new = 0
        try:
            db_path = os.path.join(BASE_DIR, "data", "jobs.db")
            conn = sqlite3.connect(db_path)
            db_new = import_gk_jobs_incremental(conn)
            conn.close()
            print(f"[考公] 数据库同步完成，新增 {db_new} 条公考岗位")
        except Exception as e:
            print(f"[考公] 数据库同步失败: {e}")

        gk_last_run_time = start_time
        gk_last_run_count = count

        # 保存到配置
        cfg = load_gk_config()
        cfg["last_run"] = start_time
        cfg["last_count"] = count
        save_gk_config(cfg)

        print(f"[考公] 采集完成：{count} 条 | 日志: {log_file}")

        return {
            "success": True,
            "count": count,
            "message": f"考公采集完成，共 {count} 条",
            "start_time": start_time,
        }

    except subprocess.TimeoutExpired:
        print("[考公] 采集超时（10分钟）")
        return {"success": False, "message": "考公采集超时（10分钟）"}
    except Exception as e:
        print(f"[考公] 采集异常：{e}")
        return {"success": False, "message": str(e)}
    finally:
        gk_is_running = False


# ══════════════════════════════════════════════════════════
# 考公调度配置读写
# ══════════════════════════════════════════════════════════
def load_gk_config():
    if os.path.exists(GK_CONFIG_FILE):
        with open(GK_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "enabled": False,
        "interval_hours": 24,
        "keyword": "公务员",
        "year": "2026",
        "provinces": [],  # 空=全部省份
        "max_pages": None,
        "delay": 1.0,
        "last_run": None,
        "last_count": 0,
    }


def save_gk_config(cfg):
    with open(GK_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════
# 定时调度器（后台线程）
# ══════════════════════════════════════════════════════════
import schedule

def scheduler_loop():
    global scheduler_running
    print("[Scheduler] 定时任务线程已启动")
    while scheduler_running:
        schedule.run_pending()
        time.sleep(30)


def reload_schedule():
    """根据配置重载定时任务"""
    schedule.clear()
    cfg = load_config()

    if not cfg.get("enabled"):
        print("[Scheduler] 定时任务未启用")
    else:
        hours = cfg.get("interval_hours", 12)
        keywords = cfg.get("keywords", [])

        if keywords:
            def job():
                latest_cfg = load_config()
                kw = latest_cfg.get("keywords", [])
                print(f"[Scheduler] 定时任务触发，当前配置关键词：{kw}")
                do_crawl(kw)

            schedule.every(hours).hours.do(job)
            print(f"[Scheduler] 已设置：每 {hours} 小时执行一次，关键词：{keywords}")

    # VIP 自动扫描任务
    vip_cfg = load_vip_config()
    if vip_cfg.get("enabled", True):
        vip_hours = vip_cfg.get("interval_hours", 48)
        def vip_job():
            print("[VIP] 定时扫描触发")
            do_vip_scan()
        schedule.every(vip_hours).hours.do(vip_job)
        print(f"[VIP] 已设置：每 {vip_hours} 小时扫描一次VIP会员")


# ══════════════════════════════════════════════════════════
# API 路由
# ══════════════════════════════════════════════════════════
@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    """获取调度配置和状态"""
    cfg = load_config()
    return jsonify({
        "enabled": cfg.get("enabled", False),
        "interval_hours": cfg.get("interval_hours", 12),
        "keywords": cfg.get("keywords", []),
        "last_run": last_run_time or cfg.get("last_run"),
        "last_count": last_run_count or cfg.get("last_count", 0),
        "is_running": is_running,
        "scheduler_active": scheduler_running,
    })


@app.route("/api/schedule", methods=["POST"])
@admin_required
def update_schedule():
    """更新调度配置"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "无效的请求"}), 400

    keywords = data.get("keywords", [])
    if not keywords:
        return jsonify({"success": False, "message": "关键词不能为空"}), 400

    interval_hours = max(1, min(168, int(data.get("interval_hours", 12))))
    enabled = bool(data.get("enabled", False))

    cfg = load_config()
    cfg["keywords"] = keywords
    cfg["interval_hours"] = interval_hours
    cfg["enabled"] = enabled
    save_config(cfg)

    # 重载调度器
    reload_schedule()

    return jsonify({
        "success": True,
        "message": f"配置已更新：{'启用' if enabled else '停用'}，每 {interval_hours} 小时，关键词 {keywords}"
    })


@app.route("/api/crawl/now", methods=["POST"])
@admin_required
def trigger_crawl():
    """立即触发一次采集"""
    if is_running:
        return jsonify({"success": False, "message": "采集正在进行中，请稍后再试"}), 409

    cfg = load_config()
    keywords = cfg.get("keywords", [])

    if not keywords:
        return jsonify({"success": False, "message": "请先配置关键词"}), 400

    # 后台异步执行；传入关键词列表的副本，防止闭包引用被后续修改
    kw_copy = list(keywords)

    def background_crawl():
        do_crawl(kw_copy)

    threading.Thread(target=background_crawl, daemon=True).start()
    return jsonify({
        "success": True,
        "message": f"采集已启动，关键词：{keywords}",
        "keywords": keywords,
    })


@app.route("/api/status", methods=["GET"])
def status():
    """服务状态"""
    return jsonify({
        "running": True,
        "scheduler_active": scheduler_running,
        "is_crawling": is_running,
        "last_run": last_run_time,
        "last_count": last_run_count,
    })


# ══════════════════════════════════════════════════════════
# 考公考编 API
# ══════════════════════════════════════════════════════════
@app.route("/api/gk/schedule", methods=["GET"])
def get_gk_schedule():
    """获取考公调度配置和状态"""
    cfg = load_gk_config()
    return jsonify({
        "enabled": cfg.get("enabled", False),
        "interval_hours": cfg.get("interval_hours", 24),
        "keyword": cfg.get("keyword", "公务员"),
        "year": cfg.get("year", "2026"),
        "provinces": cfg.get("provinces", []),
        "max_pages": cfg.get("max_pages"),
        "delay": cfg.get("delay", 1.0),
        "last_run": gk_last_run_time or cfg.get("last_run"),
        "last_count": gk_last_run_count or cfg.get("last_count", 0),
        "is_running": gk_is_running,
    })


@app.route("/api/gk/schedule", methods=["POST"])
@admin_required
def update_gk_schedule():
    """更新考公调度配置"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "无效的请求"}), 400

    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"success": False, "message": "关键词不能为空"}), 400

    cfg = load_gk_config()
    cfg["keyword"] = keyword
    cfg["year"] = str(data.get("year", "2026"))
    cfg["provinces"] = data.get("provinces", [])
    cfg["interval_hours"] = max(1, min(168, int(data.get("interval_hours", 24))))
    cfg["enabled"] = bool(data.get("enabled", False))
    cfg["max_pages"] = data.get("max_pages")
    cfg["delay"] = float(data.get("delay", 1.0))
    save_gk_config(cfg)

    return jsonify({
        "success": True,
        "message": f"考公配置已更新：关键词={keyword}，年份={cfg['year']}，省份={cfg['provinces'] or '全部'}"
    })


@app.route("/api/gk/crawl/now", methods=["POST"])
@admin_required
def trigger_gk_crawl():
    """立即触发一次考公采集"""
    if gk_is_running:
        return jsonify({"success": False, "message": "考公采集正在进行中，请稍后再试"}), 409

    cfg = load_gk_config()
    provinces = cfg.get("provinces", [])
    keyword = cfg.get("keyword", "公务员")
    year = cfg.get("year", "2026")
    max_pages = cfg.get("max_pages")
    delay = cfg.get("delay", 1.0)

    def bg_gk():
        do_gk_crawl(provinces, keyword, year, max_pages, delay)

    threading.Thread(target=bg_gk, daemon=True).start()
    return jsonify({
        "success": True,
        "message": f"考公采集已启动，省份：{provinces or '全部'}，关键词：{keyword}",
        "keyword": keyword,
        "provinces": provinces,
    })


# ══════════════════════════════════════════════════════════
# VIP 自动匹配 API
# ══════════════════════════════════════════════════════════
@app.route("/api/vip/scan/schedule", methods=["GET"])
def get_vip_scan_schedule():
    """获取VIP自动匹配调度配置"""
    cfg = load_vip_config()
    return jsonify({
        "enabled": cfg.get("enabled", True),
        "interval_hours": cfg.get("interval_hours", 48),
        "last_run": vip_last_run_time or cfg.get("last_run"),
        "last_scan_count": vip_last_scan_count or cfg.get("last_scan_count", 0),
        "last_notify_count": vip_last_notify_count or cfg.get("last_notify_count", 0),
        "is_running": vip_is_running,
    })


@app.route("/api/vip/scan/schedule", methods=["POST"])
@admin_required
def update_vip_scan_schedule():
    """更新VIP自动匹配调度配置"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "无效的请求"}), 400

    interval_hours = max(6, min(168, int(data.get("interval_hours", 48))))
    enabled = bool(data.get("enabled", True))

    cfg = load_vip_config()
    cfg["interval_hours"] = interval_hours
    cfg["enabled"] = enabled
    save_vip_config(cfg)

    reload_schedule()
    return jsonify({
        "success": True,
        "message": f"VIP扫描配置已更新：{'启用' if enabled else '停用'}，每 {interval_hours} 小时"
    })


@app.route("/api/vip/scan/now", methods=["POST"])
@admin_required
def trigger_vip_scan():
    """立即触发一次VIP自动匹配扫描"""
    if vip_is_running:
        return jsonify({"success": False, "message": "VIP扫描正在进行中"}), 409

    def bg_vip():
        do_vip_scan()

    threading.Thread(target=bg_vip, daemon=True).start()
    return jsonify({"success": True, "message": "VIP扫描已启动"})


def start_scheduler():
    global scheduler_running, scheduler_thread
    if scheduler_running:
        return
    scheduler_running = True
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()
    reload_schedule()


def main():
    print(f"\n[Schedule API] 启动中，端口 {PORT}...")
    start_scheduler()
    print(f"[Schedule API] 监听 http://0.0.0.0:{PORT}")
    print(f"[Schedule API] API文档：http://localhost:{PORT}/api/status")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
