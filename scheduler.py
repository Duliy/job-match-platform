#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scheduler.py — 定时调度引擎（校园版 · 单进程架构）

在 FastAPI 进程内以后台线程运行，统一承担：
  1. 社招岗位定时采集（login_helper.py，headless，无弹窗）
  2. 公考职位定时采集（gongkao_crawler.py，纯 HTTP）
  3. 订阅推送扫描（SQL 粗筛，无需 AI Key，新岗位邮件通知）
  4. data/ 目录每日自动备份（保留最近 7 份）

替代原 Flask schedule_api.py + VIP AI 扫描。
配置文件（与原系统兼容，自动迁移）：
  data/schedule_config.json       社招采集配置
  data/gk_schedule_config.json    公考采集配置
  data/subscription_config.json   订阅推送配置（自动从 vip_schedule_config.json 迁移）
"""

import json
import os
import shutil
import smtplib
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import schedule as _sched

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(BASE_DIR, "data_backups")
LOG_DIR = os.path.join(DATA_DIR, "crawl_logs")
DB_PATH = os.path.join(DATA_DIR, "jobs.db")

CONFIG_FILE = os.path.join(DATA_DIR, "schedule_config.json")
GK_CONFIG_FILE = os.path.join(DATA_DIR, "gk_schedule_config.json")
SUB_CONFIG_FILE = os.path.join(DATA_DIR, "subscription_config.json")
# 兼容商业化版的旧配置文件名
LEGACY_SUB_CONFIG_FILE = os.path.join(DATA_DIR, "vip_schedule_config.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ── 运行状态（admin_api 读取用于健康面板）─────────────────────
social_running = False
social_last_run = None
social_last_count = 0

gk_running = False
gk_last_run = None
gk_last_count = 0

sub_running = False
sub_last_run = None
sub_last_scan_count = 0
sub_last_notify_count = 0

_scheduler_thread = None
_started = False

CRAWL_TIMEOUT = 3600  # 社招采集最长 60 分钟（无人值守，放宽）
GK_CRAWL_TIMEOUT = 3600  # 公考采集最长 60 分钟


# ══════════════════════════════════════════════════════
# 配置读写
# ══════════════════════════════════════════════════════
def _load_json(path, default):
    """读取 JSON 配置；文件不存在/损坏时返回 default 的拷贝（default 可为 None）"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(default) if default is not None else None


def _save_json(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_crawl_config():
    return _load_json(
        CONFIG_FILE,
        {
            "enabled": False,
            "interval_hours": 12,
            "keywords": [],
            "last_run": None,
            "last_count": 0,
            "last_error": "",
        },
    )


def save_crawl_config(cfg):
    _save_json(CONFIG_FILE, cfg)


def load_gk_config():
    return _load_json(
        GK_CONFIG_FILE,
        {
            "enabled": False,
            "interval_hours": 24,
            "keyword": "公务员",
            "year": "2026",
            "provinces": [],
            "last_run": None,
            "last_count": 0,
            "last_error": "",
        },
    )


def save_gk_config(cfg):
    _save_json(GK_CONFIG_FILE, cfg)


def load_sub_config():
    """订阅推送配置；首次读取时自动从商业化版 vip_schedule_config.json 迁移"""
    cfg = _load_json(SUB_CONFIG_FILE, None)
    if cfg is None and os.path.exists(LEGACY_SUB_CONFIG_FILE):
        cfg = _load_json(LEGACY_SUB_CONFIG_FILE, None)
        if cfg:
            _save_json(SUB_CONFIG_FILE, cfg)
    if cfg is None:
        cfg = {
            "enabled": True,
            "interval_hours": 48,
            "last_run": None,
            "last_scan_count": 0,
            "last_notify_count": 0,
            "last_error": "",
        }
    return cfg


def save_sub_config(cfg):
    _save_json(SUB_CONFIG_FILE, cfg)


# ══════════════════════════════════════════════════════
# 采集执行（headless，无人值守服务器适用）
# ══════════════════════════════════════════════════════
def _run_crawler_subprocess(args, log_file, timeout):
    """静默运行爬虫子进程：无弹窗、输出写入日志文件。

    Windows 上用 CREATE_NO_WINDOW 避免在服务器上弹控制台窗口。
    """
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            args,
            cwd=BASE_DIR,
            stdout=lf,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=env,
        )
        return_code = 0
        try:
            return_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # 先杀进程再抛出，避免孤儿进程和卡死的调度状态
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:
                pass
            raise
        return return_code


def _sync_db(incremental=True, gk=False):
    """爬虫完成后把 JSON 数据同步进 SQLite"""
    try:
        from import_data import import_jobs_incremental, import_gk_jobs_incremental

        conn = sqlite3.connect(DB_PATH)
        if gk:
            n = import_gk_jobs_incremental(conn)
        else:
            n = import_jobs_incremental(conn)
        conn.close()
        return n
    except Exception as e:
        print(f"[Scheduler] 数据库同步失败: {e}")
        return 0


def run_social_crawl(keywords=None):
    """执行社招采集（前程无忧/实习僧免登录；智联/猎聘用 Cookie）"""
    global social_running, social_last_run, social_last_count
    if social_running:
        return {"success": False, "message": "社招采集正在进行中"}

    cfg = load_crawl_config()
    keywords = keywords or cfg.get("keywords", [])
    if not keywords:
        return {"success": False, "message": "未配置采集关键词"}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"crawl_{ts}.log")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        social_running = True
        script = os.path.join(BASE_DIR, "login_helper.py")
        _run_crawler_subprocess(
            [sys.executable, script, "--keywords", ",".join(keywords), "--auto"],
            log_file,
            CRAWL_TIMEOUT,
        )

        db_new = _sync_db(gk=False)
        social_last_run = start_time
        social_last_count = db_new

        cfg = load_crawl_config()
        cfg["last_run"] = start_time
        cfg["last_count"] = db_new
        cfg["last_error"] = ""
        save_crawl_config(cfg)
        print(f"[Scheduler] 社招采集完成，新增 {db_new} 条（日志: {log_file}）")
        return {"success": True, "count": db_new, "start_time": start_time}
    except subprocess.TimeoutExpired:
        cfg = load_crawl_config()
        cfg["last_error"] = "采集超时（60分钟）"
        save_crawl_config(cfg)
        return {"success": False, "message": "采集超时（60分钟）"}
    except Exception as e:
        cfg = load_crawl_config()
        cfg["last_error"] = str(e)
        save_crawl_config(cfg)
        return {"success": False, "message": str(e)}
    finally:
        social_running = False


def run_gk_crawl(provinces=None, keyword=None, year=None, max_pages=None, delay=1.0):
    """执行公考职位采集（纯 HTTP，无需 Chrome）"""
    global gk_running, gk_last_run, gk_last_count
    if gk_running:
        return {"success": False, "message": "公考采集正在进行中"}

    cfg = load_gk_config()
    provinces = provinces if provinces is not None else cfg.get("provinces", [])
    keyword = keyword or cfg.get("keyword", "公务员")
    year = year or cfg.get("year", "2026")
    max_pages = max_pages if max_pages is not None else cfg.get("max_pages")
    delay = delay if delay is not None else cfg.get("delay", 1.0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"gk_{ts}.log")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    args = [sys.executable, os.path.join(BASE_DIR, "gongkao_crawler.py")]
    if provinces:
        for p in provinces:
            args += ["--province", p]
    else:
        args.append("--all")
    args += ["--keyword", keyword, "--year", str(year), "--delay", str(delay)]
    if max_pages:
        args += ["--max-pages", str(max_pages)]

    try:
        gk_running = True
        _run_crawler_subprocess(args, log_file, GK_CRAWL_TIMEOUT)

        db_new = _sync_db(gk=True)
        gk_last_run = start_time
        gk_last_count = db_new

        cfg = load_gk_config()
        cfg["last_run"] = start_time
        cfg["last_count"] = db_new
        cfg["last_error"] = ""
        save_gk_config(cfg)
        print(f"[Scheduler] 公考采集完成，新增 {db_new} 条（日志: {log_file}）")
        return {"success": True, "count": db_new, "start_time": start_time}
    except subprocess.TimeoutExpired:
        cfg = load_gk_config()
        cfg["last_error"] = "采集超时（60分钟）"
        save_gk_config(cfg)
        return {"success": False, "message": "采集超时（60分钟）"}
    except Exception as e:
        cfg = load_gk_config()
        cfg["last_error"] = str(e)
        save_gk_config(cfg)
        return {"success": False, "message": str(e)}
    finally:
        gk_running = False


# ══════════════════════════════════════════════════════
# 订阅推送扫描（SQL 粗筛，无需 AI Key）
# ══════════════════════════════════════════════════════
def _build_notify_email(username, jobs, scan_time):
    """构建订阅推送邮件（岗位卡片列表）"""
    rows_html = ""
    for j in jobs[:15]:
        title = j.get("title") or j.get("职位名") or "未知岗位"
        company = j.get("company") or j.get("公司名") or ""
        salary = j.get("salary") or j.get("salary_raw") or ""
        location = j.get("city") or j.get("location") or j.get("province") or ""
        platform = j.get("platform") or j.get("source") or ""
        link = j.get("link") or j.get("url") or ""
        job_type = j.get("job_type", "社招")

        details = " · ".join(
            x
            for x in [company, salary, location, f"来源:{platform}" if platform else ""]
            if x
        )
        link_html = (
            f'<tr><td style="padding-top:6px;"><a href="{link}" target="_blank" '
            f'style="color:#9C6B3C;font-size:12px;text-decoration:none;font-weight:600;">查看详情 &rarr;</a></td></tr>'
            if link
            else ""
        )
        rows_html += f"""
        <div style="margin-bottom:14px;">
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr><td style="font-size:15px;font-weight:700;color:#333;">{title}
              <span style="display:inline-block;margin-left:8px;background:#EEF2FB;color:#3B5998;font-size:11px;font-weight:600;padding:2px 9px;border-radius:10px;">{job_type}</span>
            </td></tr>
            {f'<tr><td style="font-size:13px;color:#777;">{details}</td></tr>' if details else ""}
            {link_html}
          </table>
        </div>
        <hr style="border:none;border-top:1px solid #E8DDD0;margin:12px 0;">"""

    return f"""
<div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <div style="background:linear-gradient(135deg,#FBF8F3,#F5E6D3);padding:24px;border-radius:12px 12px 0 0;">
    <h2 style="color:#9C6B3C;margin:0;font-size:20px;">就业服务平台</h2>
    <p style="color:#8B7355;margin:4px 0 0 0;font-size:13px;">订阅岗位 · 新岗位通知</p>
  </div>
  <div style="padding:24px;border:1px solid #E8DDD0;border-top:none;border-radius:0 0 12px 12px;">
    <p style="margin:0 0 16px;font-size:14px;color:#555;line-height:1.7;">
      {username}，您好<br>
      {scan_time} 系统扫描到以下 <b style="color:#9C6B3C;">{len(jobs)}</b> 个与您简历方向相关的新岗位。
      如需 AI 智能匹配分析，请登录平台并使用您自己的 DeepSeek API Key。
    </p>
    {rows_html}
    <p style="font-size:11px;color:#AAA;margin:0;line-height:1.6;">此邮件由就业服务平台自动发送 · 请勿直接回复</p>
  </div>
</div>"""


def _send_email(to_addr, subject, html_body):
    """通过管理员配置的 SMTP 发送邮件。返回 (ok, message)"""
    from auth import get_email_config

    cfg = get_email_config()
    if not cfg or not cfg.get("enabled"):
        return False, "SMTP 未启用（管理员尚未在后台配置邮件服务）"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg["from_email"]
        msg["To"] = to_addr
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP_SSL(
            cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30
        ) as server:
            server.login(cfg["smtp_user"], cfg["smtp_pass"])
            server.sendmail(cfg["from_email"], [to_addr], msg.as_string())
        return True, "ok"
    except Exception as e:
        return False, str(e)


def run_subscription_scan():
    """扫描所有订阅用户（绑定了通知邮箱且上传过简历），
    用 SQL 粗筛找出上次扫描后的新岗位，邮件推送。

    校园版：不使用 AI（不需要 API Key），仅技能/学历关键词粗筛。
    """
    global sub_running, sub_last_run, sub_last_scan_count, sub_last_notify_count

    if sub_running:
        return {"success": False, "message": "订阅扫描正在进行中"}

    from match_db import pre_filter

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = load_sub_config()
    last_run = cfg.get("last_run") or "1970-01-01 00:00:00"

    print(f"[Subscription] {start_time} 开始订阅推送扫描...")
    try:
        sub_running = True

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.id, u.username, u.notify_email,
                   mr.resume_text, mr.parsed_json
            FROM users u
            JOIN member_resumes mr ON mr.user_id = u.id
            WHERE u.notify_email IS NOT NULL AND u.notify_email != ''
              AND u.is_disabled = 0
              AND mr.resume_text IS NOT NULL AND mr.resume_text != ''
            """
        )
        subscribers = cursor.fetchall()
        conn.close()

        if not subscribers:
            print("[Subscription] 没有订阅用户，跳过")
            sub_last_run = start_time
            cfg["last_run"] = start_time
            cfg["last_scan_count"] = 0
            save_sub_config(cfg)
            return {"success": True, "count": 0, "message": "没有订阅用户"}

        total_scan = len(subscribers)
        total_notify = 0

        for row in subscribers:
            try:
                parsed = json.loads(row["parsed_json"]) if row["parsed_json"] else {}
            except Exception:
                parsed = {}
            skills = parsed.get("skills", [])
            education = parsed.get("education", "")

            # 两类岗位分别粗筛
            new_jobs = []
            for jt in ["社招", "公考"]:
                candidates = pre_filter(
                    skills=skills,
                    cities=[],
                    salary_min=0,
                    salary_max=999999,
                    education=education,
                    job_type=jt,
                    max_candidates=50,
                )
                if not candidates and skills:
                    # 技能词（常为英文）匹配不上中文关键词时回退宽泛搜索
                    candidates = pre_filter(
                        skills=[],
                        cities=[],
                        salary_min=0,
                        salary_max=999999,
                        education=education,
                        job_type=jt,
                        max_candidates=50,
                    )
                for c in candidates:
                    # 只保留上次扫描之后更新的岗位（增量推送，避免重复打扰）
                    updated = str(c.get("updated_at") or c.get("collect_time") or "")
                    if updated > last_run:
                        c["job_type"] = jt
                        new_jobs.append(c)

            if not new_jobs:
                continue

            # 去重 + 取前 15 条
            seen = set()
            deduped = []
            for j in new_jobs:
                key = (j.get("title"), j.get("company") or j.get("公司名"))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(j)
            new_jobs = deduped[:15]

            html = _build_notify_email(row["username"], new_jobs, start_time)
            ok, msg = _send_email(
                row["notify_email"],
                f"就业服务平台：{len(new_jobs)} 个与您相关的新岗位",
                html,
            )
            if ok:
                total_notify += 1
                print(
                    f"[Subscription] 已通知 {row['username']} <{row['notify_email']}>，{len(new_jobs)} 个新岗位"
                )
            else:
                print(f"[Subscription] 通知 {row['username']} 失败: {msg}")

        sub_last_run = start_time
        sub_last_scan_count = total_scan
        sub_last_notify_count = total_notify

        cfg["last_run"] = start_time
        cfg["last_scan_count"] = total_scan
        cfg["last_notify_count"] = total_notify
        cfg["last_error"] = ""
        save_sub_config(cfg)

        print(
            f"[Subscription] 扫描完成：{total_scan} 个订阅用户，通知 {total_notify} 人"
        )
        return {"success": True, "count": total_scan, "notified": total_notify}
    except Exception as e:
        cfg = load_sub_config()
        cfg["last_error"] = str(e)
        save_sub_config(cfg)
        print(f"[Subscription] 扫描异常: {e}")
        return {"success": False, "message": str(e)}
    finally:
        sub_running = False


# ══════════════════════════════════════════════════════
# 数据备份（每日一次，保留最近 7 份）
# ══════════════════════════════════════════════════════
def backup_data():
    """把 data/ 目录整体复制到 data_backups/YYYYMMDD_HHMMSS/，保留最近 7 份"""
    if not os.path.isdir(DATA_DIR):
        return
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, ts)
        shutil.copytree(DATA_DIR, dst, ignore=shutil.ignore_patterns("crawl_logs"))
        # 清理旧备份
        backups = sorted(
            d
            for d in os.listdir(BACKUP_DIR)
            if os.path.isdir(os.path.join(BACKUP_DIR, d))
        )
        while len(backups) > 7:
            shutil.rmtree(os.path.join(BACKUP_DIR, backups.pop(0)), ignore_errors=True)
        print(f"[Backup] 数据已备份到 {dst}")
    except Exception as e:
        print(f"[Backup] 备份失败: {e}")


# ══════════════════════════════════════════════════════
# 调度主循环
# ══════════════════════════════════════════════════════
def reload_schedules():
    """根据配置文件重建定时任务"""
    _sched.clear()

    cfg = load_crawl_config()
    if cfg.get("enabled") and cfg.get("keywords"):
        hours = cfg.get("interval_hours", 12)

        def _social_job():
            run_social_crawl(load_crawl_config().get("keywords", []))

        _sched.every(hours).hours.do(_social_job)
        print(f"[Scheduler] 社招采集：每 {hours} 小时，关键词 {cfg.get('keywords')}")

    gk = load_gk_config()
    if gk.get("enabled"):
        hours = gk.get("interval_hours", 24)

        def _gk_job():
            run_gk_crawl()

        _sched.every(hours).hours.do(_gk_job)
        print(f"[Scheduler] 公考采集：每 {hours} 小时")

    sub = load_sub_config()
    if sub.get("enabled", True):
        hours = sub.get("interval_hours", 48)
        _sched.every(hours).hours.do(run_subscription_scan)
        print(f"[Scheduler] 订阅推送：每 {hours} 小时")

    # 每日凌晨 3:30 备份数据
    _sched.every().day.at("03:30").do(backup_data)


def _loop():
    print("[Scheduler] 定时任务线程已启动")
    while True:
        try:
            _sched.run_pending()
        except Exception as e:
            print(f"[Scheduler] 调度循环异常: {e}")
        time.sleep(30)


def start():
    """启动调度引擎（幂等）"""
    global _scheduler_thread, _started
    if _started:
        return
    _started = True
    reload_schedules()
    _scheduler_thread = threading.Thread(target=_loop, daemon=True)
    _scheduler_thread.start()


def status():
    """健康面板用的状态汇总"""
    return {
        "social": {
            "running": social_running,
            "last_run": social_last_run or load_crawl_config().get("last_run"),
            "last_count": social_last_count or load_crawl_config().get("last_count", 0),
            "last_error": load_crawl_config().get("last_error", ""),
            "enabled": load_crawl_config().get("enabled", False),
        },
        "gk": {
            "running": gk_running,
            "last_run": gk_last_run or load_gk_config().get("last_run"),
            "last_count": gk_last_count or load_gk_config().get("last_count", 0),
            "last_error": load_gk_config().get("last_error", ""),
            "enabled": load_gk_config().get("enabled", False),
        },
        "subscription": {
            "running": sub_running,
            "last_run": sub_last_run or load_sub_config().get("last_run"),
            "last_scan_count": sub_last_scan_count
            or load_sub_config().get("last_scan_count", 0),
            "last_notify_count": sub_last_notify_count
            or load_sub_config().get("last_notify_count", 0),
            "last_error": load_sub_config().get("last_error", ""),
            "enabled": load_sub_config().get("enabled", True),
        },
    }
