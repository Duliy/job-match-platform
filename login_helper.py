#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招聘数据手动登录 + 真实采集助手  v3.1
========================================================
匿名平台（无需登录）：51job、前程无忧 | 实习僧 | 公共招聘网
公开页优先：猎聘、实习僧；智联可能要求登录/安全验证，遇验证停止
登录墙平台（无法匿名）：国聘（iguopin.com）| Boss直聘
"""

import os, sys, json, time, random, logging, argparse, re

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_DIR = os.path.join(BASE_DIR, "cookies")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(COOKIE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# 平台列表（供交互模式和自动模式共用）
PLATFORMS = [
    ("51job", "前程无忧", "https://www.51job.com/"),
    ("zhaopin", "智联招聘", "https://passport.zhaopin.com/login"),
    ("liepin", "猎聘网", "https://www.liepin.com/"),
    ("shixiseng", "实习僧", "https://www.shixiseng.com/"),
    ("guopin", "国聘网", "https://www.iguopin.com/"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "crawler.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("login_helper")


# ── 工具函数 ──────────────────────────────────────────────
def clean(text):
    return " ".join(str(text).split()) if text else ""


_COMPANY_TAG_TOKENS = ("上市", "融资", "轮", "人规模", "不需要")

def _is_company_tag(text):
    """判断是否为公司标签（融资阶段/规模等），防止误识别为城市"""
    return any(k in text for k in _COMPANY_TAG_TOKENS)


def load_driver(headless=False, profile_dir=None):
    """
    Windows 兼容的 Chrome 启动配置
    - headless=True  : 无头模式（用于 API/定时任务子进程，稳定不弹窗）
    - headless=False : 可见模式（用于手动登录调试）
    - profile_dir     : 指定用户数据目录，默认用 chrome_profile/
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options

    local_drv = os.path.join(BASE_DIR, "chromedriver.exe")
    opts = Options()
    opts.page_load_strategy = "eager"

    # 便携包优先用内置 Chrome，其次环境变量，最后系统 Chrome
    from portable_env import find_chrome_binary, find_chromedriver

    chrome_bin = find_chrome_binary()
    if chrome_bin:
        opts.binary_location = chrome_bin

    # headless 模式
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-software-rasterizer")

    # 通用稳定性参数
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=zh-CN")
    opts.add_argument("--remote-debugging-port=0")  # 避免 DevToolsActivePort 崩溃

    # headless 模式不使用持久化 profile（避免与新系统 Chrome 版本冲突）
    if headless:
        import tempfile

        tmp_dir = os.path.join(tempfile.gettempdir(), "chrome_profile_headless")
        os.makedirs(tmp_dir, exist_ok=True)
        opts.add_argument(f"--user-data-dir={tmp_dir}")
    elif profile_dir:
        opts.add_argument(f"--user-data-dir={profile_dir}")
    else:
        default_profile = os.path.join(BASE_DIR, "chrome_profile")
        os.makedirs(default_profile, exist_ok=True)
        opts.add_argument(f"--user-data-dir={default_profile}")

    # 反检测（headless 模式下跳过，避免与新版 Chrome 不兼容）
    if not headless:
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_experimental_option("detach", True)

    try:
        drv_path = find_chromedriver() or local_drv
        drv = webdriver.Chrome(service=Service(drv_path), options=opts)
        drv.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            },
        )
        drv.set_page_load_timeout(30)
        return drv
    except Exception as e:
        log.error(f"Chrome 启动失败: {e}")
        log.info("尝试使用系统 ChromeDriver...")
        drv = webdriver.Chrome(options=opts)
        drv.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            },
        )
        drv.set_page_load_timeout(30)
        return drv


def load_cookies(driver, key, domain_url):
    path = os.path.join(COOKIE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return False
    driver.get(domain_url)
    time.sleep(1)
    with open(path, encoding="utf-8") as f:
        cks = json.load(f)
    for ck in cks:
        ck.pop("sameSite", None)
        try:
            driver.add_cookie(ck)
        except Exception:
            pass
    driver.refresh()
    time.sleep(2)
    log.info(f"  [Cookie] {key}: {len(cks)} cookies injected")
    return True


def wait_el(driver, selector, timeout=12):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        return True
    except Exception:
        return False


def crawl_with_cookies(driver, keyword, success_keys, max_pages=0, on_page=None, report=None):
    """公开页优先，各来源独立报告；登录 Cookie 仅在需要登录时作为后备。"""
    from crawler_sources import crawl_source, LABELS
    from crawler_51job import crawl_51job
    jobs, sources = [], {}
    for platform in ('51job', 'shixiseng', 'liepin', 'zhaopin', 'mohrss', 'guopin'):
        if platform not in success_keys:
            continue
        detail = {}
        if platform == '51job':
            batch = crawl_51job(driver, keyword, max_pages=max_pages,
                               on_page=on_page, report=detail)
        elif platform in LABELS:
            # 智联明确可能需要登录：已有登录状态直接使用，没 Cookie 仍尝试公开页。
            path = os.path.join(COOKIE_DIR, platform + '.json')
            cookie_loaded = False
            if platform == 'zhaopin' and os.path.isfile(path):
                try:
                    load_cookies(driver, platform, 'https://www.zhaopin.com')
                    cookie_loaded = True
                except Exception as exc:
                    log.warning('[智联招聘] 登录 Cookie 加载失败：%s', type(exc).__name__)
            batch = crawl_source(driver, keyword, platform, max_pages=max_pages,
                                 on_page=on_page, report=detail)
            path = os.path.join(COOKIE_DIR, platform + '.json')
            if (not cookie_loaded and not detail.get('complete') and '需要登录' in detail.get('reason', '')
                    and os.path.isfile(path)):
                log.info('[%s] 匿名访问需登录，尝试已保存的登录 Cookie', LABELS[platform])
                domain = next(url for key, _, url in PLATFORMS if key == platform)
                try:
                    load_cookies(driver, platform, domain)
                    retry = {}
                    batch += crawl_source(driver, keyword, platform, max_pages=max_pages,
                                          on_page=on_page, report=retry)
                    detail = retry
                    detail['auth_mode'] = 'saved_cookie'
                except Exception as exc:
                    detail.update(complete=False, reason='登录 Cookie 加载失败：' + type(exc).__name__)
        else:
            batch = []
            detail = {'complete': False, 'reason': '来源尚无可用采集适配器，请先停用或人工导入', 'count': 0}
        sources[platform] = detail
        jobs.extend(batch)
        # Persist source-level results even when a later platform fails.
        state_path = os.path.join(DATA_DIR, 'source_status.json')
        import tempfile
        state = {}
        try:
            with open(state_path, encoding='utf-8') as f: state = json.load(f)
        except (OSError, ValueError):
            pass
        state[platform] = dict(detail, keyword=keyword,
                               checked_at=__import__('datetime').datetime.now().isoformat(timespec='seconds'))
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=DATA_DIR, delete=False) as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            tmp = f.name
        os.replace(tmp, state_path)
    failures = [key + ': ' + detail.get('reason', '未知错误') for key, detail in sources.items()
                if not detail.get('complete')]
    if report is not None:
        report.update(complete=not failures, reason='; '.join(failures), sources=sources)
    return jobs


def job_identity(job):
    """同一岗位跨页/跨关键词合并，不合并异地岗位或不同岗位详情链接。"""
    from urllib.parse import urlsplit
    link = job.get("链接", "").strip()
    parts = urlsplit(link)
    from crawler_sources import stable_source_link
    stable = stable_source_link(link)
    if stable:
        return (job.get("来源平台", ""), stable)
    # 旧 51job 数据误用了公司主页，该链接不能作为岗位 ID。
    if link and not ("51job.com" in (parts.hostname or "") and "/co" in parts.path):
        return (job.get("来源平台", ""), parts.netloc, parts.path, parts.query)
    return tuple(job.get(k, "") for k in
                 ("来源平台", "职位名称", "公司名称", "工作地点"))


def save_results(new_jobs, keyword, export_excel=True):
    """
    合并保存招聘数据（不覆盖，只追加去重）
    - 读取已有 jobs_latest.json，与新数据合并去重
    - 保留 first_seen，以 last_seen 标记最近采到时间
    - 每次保存清理超过 7 天未再次采到的记录
    """
    from datetime import datetime, timedelta

    today = datetime.today().strftime("%Y-%m-%d")  # 仅日期，文件名不能用冒号
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expire_days = 7
    expire_threshold = (datetime.now() - timedelta(days=expire_days)).strftime(
        "%Y-%m-%d"
    )

    json_path = os.path.join(DATA_DIR, "jobs_latest.json")

    # ── 1. 读取已有数据 ────────────────────────────────
    existing_jobs = {}  # key -> job dict（用于去重和保留 first_seen）
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                old_data = json.load(f)
            for j in old_data.get("jobs", []):
                key = job_identity(j)
                existing_jobs[key] = j
        except Exception:
            existing_jobs = {}

    # ── 2. 合并新数据 ─────────────────────────────────
    added_count = 0
    for job in new_jobs:
        # 每条记录标记本次采集的关键词
        job["关键词"] = job.get("关键词") or keyword

        job["last_seen"] = today
        key = job_identity(job)
        if key not in existing_jobs:
            # 新职位：标记首次出现时间
            job["first_seen"] = today
            existing_jobs[key] = job
            added_count += 1
        else:
            # 已存在：保留原有的 first_seen，同时追加关键词（多关键词搜索时）
            old = existing_jobs[key]
            previous_keywords = old.get("关键词", "")
            first_seen = old.get("first_seen", today)
            old.update(job)
            old["first_seen"] = first_seen
            old["关键词"] = ",".join(dict.fromkeys(
                k.strip() for value in (previous_keywords, job["关键词"])
                for k in value.split(",") if k.strip()))

    # ── 3. 过滤 7 天前过期数据 ─────────────────────────
    all_jobs = list(existing_jobs.values())
    before_count = len(all_jobs)
    all_jobs = [j for j in all_jobs if j.get("last_seen", j.get("first_seen", "")) >= expire_threshold]
    expired = before_count - len(all_jobs)

    # ── 4. 保存 jobs_latest.json ───────────────────────
    # 累积顶层 keywords（从已有 jobs 中提取，去重排序）
    all_kw_set = set()
    for j in all_jobs:
        for kw in j.get("关键词", "").split(","):
            if kw.strip():
                all_kw_set.add(kw.strip())

    result = {
        "update_time": now_str,
        "keyword": keyword,
        "keywords": sorted(all_kw_set),
        "total": len(all_jobs),
        "jobs": all_jobs,
    }
    temp_path = json_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, json_path)
    if not export_excel:
        return len(all_jobs)
    import pandas as pd

    # ── 5. 保存 Excel（当日独立文件） ───────────────────
    excel_path = os.path.join(DATA_DIR, f"jobs_{today}.xlsx")
    try:
        if os.path.exists(excel_path):
            os.remove(excel_path)
    except Exception:
        log.warning("Excel文件被占用，跳过Excel写入")
        excel_path = None

    if excel_path:
        try:
            df = pd.DataFrame(all_jobs)
            df.to_excel(excel_path, index=False)
        except Exception as e:
            log.warning(f"Excel写入失败: {e}，保存为CSV")
            csv_path = os.path.join(DATA_DIR, f"jobs_{today}.csv")
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            excel_path = csv_path

    ext = os.path.splitext(excel_path)[1].upper() if excel_path else ".CSV"
    log.info("\n✅ 结果已保存:")
    log.info(f"   JSON  → {json_path}")
    log.info(f"   {ext}  → {excel_path}")
    if expired > 0:
        log.info(
            f"   合并结果：本次新增 {added_count} 条 | 过期清理 {expired} 条 | 当前累计 {len(all_jobs)} 条"
        )
    else:
        log.info(
            f"   合并结果：本次新增 {added_count} 条 | 当前累计 {len(all_jobs)} 条"
        )

    return len(all_jobs)


# ══════════════════════════════════════════════════════════
# 采集入口：支持交互模式和自动模式（API/定时任务调用）
# 用法：
#   交互模式：python login_helper.py
#   自动模式：python login_helper.py --keywords 软件工程师,数据分析
# ══════════════════════════════════════════════════════════
def run_crawl(driver, keywords, success_keys, max_pages=0):
    """执行采集（供交互模式和API调用共用）"""
    all_jobs = []
    incomplete = []
    for kw in keywords:
        print(f"\n  ▶ 正在采集：【{kw}】")
        report = {}
        jobs = crawl_with_cookies(
            driver, kw, success_keys, max_pages=max_pages,
            on_page=lambda batch: save_results(batch, kw, export_excel=False), report=report)
        if report and not report["complete"]:
            incomplete.append("{}: {}".format(kw, report["reason"]))
        for job in jobs:
            job["关键词"] = kw
        if jobs:
            print(f"  ✅ 【{kw}】采集到 {len(jobs)} 条")
            all_jobs.extend(jobs)
        else:
            print(f"  ⚠ 【{kw}】未采集到数据")

    if all_jobs:
        total = save_results(all_jobs, "，".join(keywords))
        state = "部分完成（详见错误）" if incomplete else "全部完成"
        print(f"\n  {state}！本次读取 {len(all_jobs)} 条，去重后当前累计 {total} 条")
        for j in all_jobs[:8]:
            print(
                f"    [{j['来源平台']}] {j['职位名称']} | {j['公司名称']} | {j['薪资']} | {j['工作地点']}"
            )
        if len(all_jobs) > 8:
            print(f"    ... 还有 {len(all_jobs) - 8} 条（见 data/ 目录）")
        if incomplete:
            raise RuntimeError("来源采集未完成，已保存部分结果：" + "; ".join(incomplete))
        return total
    else:
        print("\n  ⚠ 未采集到任何数据。可能原因：")
        print("    1. 登录 Cookie 已过期 → 重新运行本程序再登录一次")
        print("    2. 网站临时风控      → 稍后再试")
        print("    3. 网络连接问题      → 检查网络")
        total = save_results([], "，".join(keywords))
        if incomplete:
            raise RuntimeError("来源采集未完成：" + "; ".join(incomplete))
        return total


def main():
    parser = argparse.ArgumentParser(description="招聘数据采集")
    parser.add_argument(
        "--keywords",
        type=str,
        default="",
        help="关键词，多个用逗号分隔（留空则进入交互模式）",
    )
    parser.add_argument(
        "--auto", action="store_true", help="自动模式：跳过交互，直接用已有Cookie采集"
    )
    parser.add_argument("--max-pages", type=int, default=0,
                        help="各平台每关键词页数上限，0=全部（默认）")
    parser.add_argument("--platforms", default="51job,liepin,shixiseng,zhaopin",
                        help="采集平台，逗号分隔；如仅前程无忧：51job")
    args = parser.parse_args()
    if args.max_pages < 0:
        parser.error("--max-pages 不能为负数")
    platforms = {p.strip() for p in args.platforms.split(",") if p.strip()}
    if not platforms or platforms - {p[0] for p in PLATFORMS} - {"mohrss"}:
        parser.error("--platforms 包含未知平台或为空")

    # 自动模式：跳过登录，直接采集
    if args.keywords:
        keywords = [
            k.strip() for k in args.keywords.replace("，", ",").split(",") if k.strip()
        ]
        print(f"\n[自动模式] 关键词：{keywords}")
        driver = load_driver(headless=True)
        try:
            # 匿名平台（无需Cookie，直接参与采集）
            success_keys = [p for p in ("51job", "liepin", "shixiseng", "zhaopin", "mohrss") if p in platforms]

            # 尝试加载已有 Cookie（传入真实 domain URL）
            for name, label, domain_url in PLATFORMS:
                path = os.path.join(COOKIE_DIR, f"{name}.json")
                if name in platforms and os.path.exists(path):
                    # 各平台采集时再注入，避免重复打开登录页。
                    if name not in success_keys:
                        success_keys.append(name)
                    print(f"  发现可用 Cookie: {name}")

            print(f"  有效平台：{success_keys}")
            count = run_crawl(driver, keywords, success_keys, max_pages=args.max_pages)
            print(f"\n[完成] 共采集 {count} 条")
        finally:
            # driver.quit() 在异常会话上可能永久挂起（无人值守服务器的真实事故），
            # 用看门狗强制退出，保证调度器不会被拖到超时
            import threading as _th

            quit_exit_code = 1 if sys.exc_info()[0] else 0

            def _force_exit():
                print("[Watchdog] driver.quit() 超时，强制退出进程")
                os._exit(quit_exit_code)

            _wd = _th.Timer(15, _force_exit)
            _wd.daemon = True
            _wd.start()
            try:
                driver.quit()
            finally:
                _wd.cancel()
        return

    # ── 交互模式（原流程）──────────────────────────────
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + "  招聘数据手动登录 & 真实采集助手".center(56) + "  ║")
    print("╚" + "═" * 58 + "╝\n")

    driver = load_driver()

    try:
        print("=" * 60)
        print("  🔑 步骤1：手动登录各招聘平台")
        print("=" * 60)
        print("  浏览器将依次打开各平台登录页。")
        print("  请在浏览器内完成登录，然后回到这里按 Enter。\n")

        success_keys = []
        for name, label, url in PLATFORMS:
            print(f"\n  正在打开：{label}  ({name})")
            print(f"    登录地址：{url}")
            try:
                driver.get(url)
                time.sleep(2)
            except Exception as e:
                log.warning(f"  打开失败: {e}")

            input(
                f"  ✅ 请在浏览器完成【{label}】登录，完成后按 Enter（跳过直接按 Enter）..."
            )

            path = os.path.join(COOKIE_DIR, f"{name}.json")
            cks = driver.get_cookies()
            if cks:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(cks, f, ensure_ascii=False, indent=2)
                log.info(f"[Cookie] {name}: {len(cks)} 条 -> {path}")
                success_keys.append(name)
            else:
                print(f"  ⚠ 未获取到Cookie，跳过该平台")

        print("\n" + "=" * 60)
        print("  🔍 步骤2：输入关键词采集数据")
        print("=" * 60)

        kw_input = input("\n  请输入搜索关键词（多个用逗号分隔）: ").strip()
        if not kw_input:
            kw_input = "软件工程师"
            print(f"  未输入，使用默认关键词：【{kw_input}】")

        keywords = [
            k.strip() for k in kw_input.replace("，", ",").split(",") if k.strip()
        ]
        print(f"\n  将依次采集关键词：{keywords}\n" + "─" * 50)
        run_crawl(driver, keywords, success_keys, max_pages=args.max_pages)

    finally:
        driver.quit()
        print("\n浏览器已关闭。")


if __name__ == "__main__":
    main()
