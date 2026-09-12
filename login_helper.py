#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招聘数据手动登录 + 真实采集助手  v3.1
========================================================
匿名平台（无需登录）：51job、前程无忧 | 实习僧 | 公共招聘网
需登录平台：智联（headless下会被安全验证拦截）| 猎聘
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


def crawl_with_cookies(driver, keyword, success_keys):
    """
    使用已保存的 Cookie 采集招聘数据
    选择器已通过 debug 脚本在真实页面验证（2026-05-13）
    """
    from selenium.webdriver.common.by import By
    import urllib.parse

    jobs = []
    today = __import__("datetime").date.today().isoformat()

    kw_enc = urllib.parse.quote(keyword)

    # ═════════════════════════════════════════════════════
    # 平台1：前程无忧 51job  (匿名可访问，无需登录)
    #   卡片选择器：.joblist-item  (已验证20条)
    #   关键字段：
    #     .joblist-item-jobname → 职位名
    #     .sal                    → "5-7千\n重庆"
    #     .joblist-item-jobinfo     → "5-7千\n重庆"
    #     .hr-info / card.text     → 公司名
    # ═════════════════════════════════════════════════════
    try:
        log.info(f"[51job] 开始采集「{keyword}」...")
        url = f"https://we.51job.com/pc/search?keyword={kw_enc}&searchType=2&sortType=0&pageNum=1"
        driver.get(url)
        time.sleep(random.uniform(4, 6))

        if not wait_el(driver, ".joblist-item", timeout=12):
            log.warning("[51job] 页面无数据，跳过")
        else:
            cards = driver.find_elements(By.CSS_SELECTOR, ".joblist-item")
            log.info(f"[51job] 找到 {len(cards)} 张卡片")

            before = len(jobs)
            for card in cards[:25]:
                try:
                    # ── 职位名 ──────────────
                    try:
                        jn_el = card.find_element(By.CSS_SELECTOR, ".jname")
                        job_name = jn_el.text.strip()
                    except Exception:
                        job_name = ""

                    # ── 薪资 ─────────────────
                    try:
                        sal_el = card.find_element(By.CSS_SELECTOR, ".sal")
                        raw_sal = sal_el.text.strip()
                        # 格式 "5-7千\n重庆" 或 "6千-1万"
                        if "\n" in raw_sal:
                            salary = raw_sal.split("\n")[0].strip()
                        elif "|" in raw_sal:
                            salary = raw_sal.split("|")[0].strip()
                        else:
                            salary = raw_sal
                    except Exception:
                        salary = ""

                    # ── 地点（从 .shrink-0 找含"市/区"） ─────────────────
                    area = ""
                    try:
                        for shr_el in card.find_elements(By.CSS_SELECTOR, ".shrink-0"):
                            t = shr_el.text.strip()
                            if t and any(k in t for k in ["市", "区"]) and len(t) < 15:
                                area = t
                                break
                    except Exception:
                        area = ""

                    # ── 公司名（从 .cname / .hr-info 或全文） ─────
                    company = ""
                    for sel in [
                        ".cname",
                        ".hr-info",
                        ".hr-position",
                        ".detail-wrapper .hr-info",
                    ]:
                        try:
                            el = card.find_element(By.CSS_SELECTOR, sel)
                            t = el.text.strip()
                            if t and len(t) > 2:
                                company = t
                                break
                        except Exception:
                            pass
                    if not company:
                        # 从全文按 "集团/有限/科技/公司" 识别
                        full = card.text
                        if "|" in full:
                            segs = [s.strip() for s in full.split("|")]
                        else:
                            segs = [full]
                        for seg in segs:
                            if any(
                                k in seg
                                for k in ["集团", "有限", "科技", "公司", "企业"]
                            ):
                                if 2 < len(seg) < 30 and "投递" not in seg:
                                    company = seg
                                    break
                        # 兜底：倒数第2个有意义段
                        if not company:
                            meaningful = [
                                s
                                for s in segs
                                if s
                                and len(s) > 2
                                and not any(
                                    k in s
                                    for k in [
                                        "千",
                                        "万",
                                        "元",
                                        "经验",
                                        "市",
                                        "区",
                                        "投递",
                                        "本科",
                                        "硕士",
                                        "博士",
                                        "天",
                                        "招",
                                        "在线",
                                        "日",
                                    ]
                                )
                            ]
                            if len(meaningful) >= 2:
                                company = meaningful[-2]

                    # ── 链接 ─────────────────
                    # 51job 列表页职位链接通过 JS 动态生成，DOM 里只有公司主页链接
                    # 直接取卡片第一个 <a> 的 href（跳转公司页可接受）
                    link = ""
                    try:
                        link = (
                            card.find_element(By.CSS_SELECTOR, "a").get_attribute(
                                "href"
                            )
                            or ""
                        )
                    except Exception:
                        link = ""

                    if job_name:
                        jobs.append(
                            {
                                "职位名称": job_name,
                                "公司名称": company,
                                "薪资": salary,
                                "工作地点": area,
                                "学历要求": "",
                                "来源平台": "前程无忧",
                                "发布日期": today,
                                "链接": link,
                            }
                        )
                except Exception:
                    pass
            log.info(f"[51job] 新增 {len(jobs) - before} 条")
    except Exception as e:
        log.error(f"[51job] 采集失败: {e}")

    # ═════════════════════════════════════════════════════
    # 平台2：智联招聘
    #   卡片：[class*='joblist-box__item']  (已验证224条)
    #   卡片文本："软件工程师 | 4000-8000元 | SQL | ... | 鞍山·立山区 | 本科 | 公司名"
    # ═════════════════════════════════════════════════════
    if "zhaopin" in success_keys:
        try:
            log.info(f"[智联] 开始采集「{keyword}」...")
            load_cookies(driver, "zhaopin", "https://www.zhaopin.com")
            driver.get(f"https://sou.zhaopin.com/?kw={kw_enc}&p=1")
            time.sleep(random.uniform(5, 7))

            wait_el(driver, ".joblist-box__item", timeout=14)
            cards = driver.find_elements(By.CSS_SELECTOR, ".joblist-box__item")
            log.info(f"[智联] 找到 {len(cards)} 张卡片")

            before = len(jobs)
            for card in cards[:25]:
                try:
                    # 职位名
                    job_name = ""
                    try:
                        jn = card.find_element(By.CSS_SELECTOR, ".jobinfo__name")
                        job_name = jn.text.strip()
                    except Exception:
                        pass

                    # 薪资
                    salary = ""
                    try:
                        sl = card.find_element(By.CSS_SELECTOR, ".jobinfo__salary")
                        salary = sl.text.strip()
                    except Exception:
                        pass

                    # 地点 + 学历（从 .jobinfo__other-info-item 列表提取）
                    area = ""
                    edu = ""
                    try:
                        other_items = card.find_elements(
                            By.CSS_SELECTOR, ".jobinfo__other-info-item"
                        )
                        for item in other_items:
                            t = item.text.strip()
                            if not area and any(k in t for k in ["市", "区", "·"]):
                                area = t
                            elif any(
                                k in t for k in ["本科", "硕士", "博士", "大专", "学历"]
                            ):
                                edu = t
                    except Exception:
                        pass

                    # 公司名
                    company = ""
                    try:
                        co = card.find_element(By.CSS_SELECTOR, ".companyinfo__name")
                        company = co.text.strip()
                    except Exception:
                        pass

                    # 链接
                    link = ""
                    try:
                        link = (
                            card.find_element(By.CSS_SELECTOR, "a").get_attribute(
                                "href"
                            )
                            or ""
                        )
                    except Exception:
                        pass

                    if job_name:
                        jobs.append(
                            {
                                "职位名称": job_name,
                                "公司名称": company,
                                "薪资": salary,
                                "工作地点": area,
                                "学历要求": edu,
                                "来源平台": "智联招聘",
                                "发布日期": today,
                                "链接": link,
                            }
                        )
                except Exception:
                    pass
            log.info(f"[智联] 新增 {len(jobs) - before} 条")
        except Exception as e:
            log.error(f"[智联] 采集失败: {e}")

    # ═════════════════════════════════════════════════════
    # 平台3：猎聘网  ✅ 已验证（2026-05-14）
    #   容器：[class*='job-card-pc-container']（动态class前缀）
    #   文本格式：换行分隔（\n），非 pipe
    #   例卡片文本结构：
    #     职位名
    #     【
    #     城市-区
    #     】
    #     急聘/热招/...
    #     10-20k·14薪
    #     3年以上
    #     本科/大专/...
    #     公司名
    #     行业|融资|人数
    #     招聘人
    #     时间
    #     广告
    # ═════════════════════════════════════════════════════
    if "liepin" in success_keys:
        try:
            log.info(f"[猎聘] 开始采集「{keyword}」...")
            load_cookies(driver, "liepin", "https://www.liepin.com")
            driver.get(f"https://www.liepin.com/zhaopin/?key={kw_enc}&curPage=0")
            time.sleep(random.uniform(5, 7))

            if wait_el(driver, "[class*='job-card-pc-container']", timeout=15):
                cards = driver.find_elements(
                    By.CSS_SELECTOR, "[class*='job-card-pc-container']"
                )
            else:
                cards = []
            log.info(f"[猎聘] 找到 {len(cards)} 张卡片")

            before = len(jobs)
            for card in cards[:25]:
                try:
                    # 用换行符解析（card.text 包含真实 \n，非 pipe）
                    full = card.text.strip()
                    if not full:
                        continue
                    lines = [p.strip() for p in full.split("\n") if p.strip()]
                    skip = {"广告", "急聘", "热招", "【", "】", ""}
                    job_name = area = salary = company = edu = ""

                    for p in lines:
                        if p in skip:
                            continue
                        # 城市：含"市"或"区"且较短
                        if (
                            not area
                            and any(k in p for k in ["市", "区"])
                            and len(p) < 20
                        ):
                            area = p
                        # 薪资：含 k/K/千/万/元
                        elif not salary and any(
                            k in p for k in ["k", "K", "千", "万", "元"]
                        ):
                            salary = p
                        # 学历
                        elif any(
                            k in p for k in ["本科", "硕士", "博士", "大专", "学历"]
                        ):
                            edu = p
                        # 公司：含常见后缀
                        elif not company and any(
                            k in p
                            for k in [
                                "有限",
                                "集团",
                                "科技",
                                "公司",
                                "企业",
                                "厂",
                                "院",
                                "基金",
                                "银行",
                            ]
                        ):
                            if 3 < len(p) < 35:
                                company = p
                        # 职位名：第一个有意义的短字符串
                        elif not job_name and len(p) > 1 and len(p) < 50:
                            if not any(
                                k in p
                                for k in [
                                    "·招聘",
                                    "在线",
                                    "当前",
                                    "担当",
                                    "发布",
                                    "岗位",
                                    "猎头",
                                    "HR",
                                    "人事",
                                ]
                            ):
                                job_name = p

                    link = ""
                    try:
                        a_el = card.find_element(By.CSS_SELECTOR, "a")
                        link = a_el.get_attribute("href") or ""
                        if link and not link.startswith("http"):
                            link = "https://www.liepin.com" + link
                    except Exception:
                        pass

                    if job_name:
                        jobs.append(
                            {
                                "职位名称": job_name,
                                "公司名称": company,
                                "薪资": salary or "面议",
                                "工作地点": area,
                                "学历要求": edu,
                                "来源平台": "猎聘网",
                                "发布日期": today,
                                "链接": link,
                            }
                        )
                except Exception:
                    pass
            log.info(f"[猎聘] 新增 {len(jobs) - before} 条")
        except Exception as e:
            log.error(f"[猎聘] 采集失败: {e}")

    # ═════════════════════════════════════════════════════
    # 平台4：实习僧  ✅ 已验证（2026-05-14）
    #   URL: https://www.shixiseng.com/interns/?k=XXX
    #   容器: .intern-item（20条/页）
    #   字段提取：
    #     城市   → .city.ellipsis
    #     公司   → .intern-detail__company > a.title
    #     行业   → .intern-detail__company > .tip
    #     实习期 → 卡片文本解析 "X天/周 | X个月"
    #     职位名 → 需访问详情页 <title>（额外请求，但保证准确）
    #     薪资   → ⚠️ 字体图标编码，无法直接解析
    # ═════════════════════════════════════════════════════
    try:
        log.info(f"[实习僧] 开始采集「{keyword}」...")
        driver.get(f"https://www.shixiseng.com/interns/?k={kw_enc}")
        time.sleep(random.uniform(3, 5))

        if wait_el(driver, ".intern-item", timeout=12):
            cards = driver.find_elements(By.CSS_SELECTOR, ".intern-item")
        else:
            cards = []
        log.info(f"[实习僧] 找到 {len(cards)} 张卡片")

        before = len(jobs)
        for card in cards[:25]:
            try:
                # ── 城市 ──────────────────────────────────
                area = ""
                try:
                    area = card.find_element(
                        By.CSS_SELECTOR, ".city.ellipsis"
                    ).text.strip()
                except Exception:
                    pass

                # ── 公司名 ───────────────────────────────
                company = ""
                try:
                    co_a = card.find_element(
                        By.CSS_SELECTOR, ".intern-detail__company a.title"
                    )
                    company = co_a.text.strip()
                except Exception:
                    pass

                # ── 行业（公司区第二行）─────────────────
                industry = ""
                try:
                    co_tip = card.find_element(
                        By.CSS_SELECTOR, ".intern-detail__company .tip"
                    )
                    industry = co_tip.text.strip().split("/")[0]
                except Exception:
                    pass

                # ── 实习期 + 转正（从卡片文本解析）────────
                edu_parts = []
                card_text = card.text
                m = re.search(r"(\d+)天/周", card_text)
                if m:
                    edu_parts.append(f"{m.group(1)}天/周")
                m2 = re.search(r"(\d+)个月", card_text)
                if m2:
                    edu_parts.append(f"{m2.group(1)}个月")
                if "转正" in card_text:
                    edu_parts.append("可转正")
                edu = "，".join(edu_parts)

                # ── 职位名 + 详情页链接（无需访问详情页）────
                #   搜索页 <a> 文字格式：图标(CSS注入搜索词) + 中文基础词（如"实习"）
                #   URL slug 是唯一的，直接作为去重 key
                #   职位名 = 基础词；若基础词不含中文则用 keyword（搜索词）
                job_name = ""
                link = ""
                try:
                    a_el = card.find_element(By.CSS_SELECTOR, ".intern-detail__job a")
                    link = a_el.get_attribute("href") or ""
                    # 去掉私有区图标，保留中文基础词
                    raw_text = a_el.text or ""
                    base = re.sub(r"[\uE000-\uF8FF]", "", raw_text).strip()
                    # 基础词包含中文（非纯图标）→ 直接用；否则用 keyword
                    if base and re.search(r"[\u4e00-\u9fa5]", base):
                        job_name = base
                    else:
                        job_name = keyword
                except Exception:
                    pass

                if job_name or company:
                    jobs.append(
                        {
                            "职位名称": job_name or (keyword + "实习"),
                            "公司名称": company,
                            "薪资": "（见实习僧）",  # 薪资图标无法解析
                            "工作地点": area,
                            "学历要求": edu,
                            "来源平台": "实习僧",
                            "发布日期": today,
                            "链接": link,
                        }
                    )
            except Exception:
                pass
        log.info(f"[实习僧] 新增 {len(jobs) - before} 条")
    except Exception as e:
        log.error(f"[实习僧] 采集失败: {e}")

    # ═════════════════════════════════════════════════════
    # 平台5：中国公共招聘网（人社部）
    #   URL: https://zwfw.mohrss.gov.cn/job/?searchText=XXX
    #   卡片：[class*='job-item'], article, .item
    # ═════════════════════════════════════════════════════
    try:
        log.info(f"[公共招聘网] 开始采集「{keyword}」...")
        driver.get(f"https://zwfw.mohrss.gov.cn/job/?searchText={kw_enc}")
        time.sleep(random.uniform(4, 6))

        if wait_el(
            driver, "[class*='job'], article, .item, a[href*='job']", timeout=15
        ):
            cards = driver.find_elements(
                By.CSS_SELECTOR,
                "[class*='job-item'], [class*='position-item'], "
                "[class*='list'] li, article, .job-card, .item, "
                "a[href*='job'], a[href*='position']",
            )
        else:
            cards = []
        log.info(f"[公共招聘网] 找到 {len(cards)} 张卡片")

        before = len(jobs)
        for card in cards[:25]:
            try:
                job_name = ""
                for sel in [
                    "[class*='job-name']",
                    "[class*='title']",
                    "h3",
                    "h4",
                    ".name",
                    "strong",
                ]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and 2 < len(t) < 60:
                            job_name = t
                            break
                    except Exception:
                        pass

                salary = ""
                for sel in ["[class*='salary']", "[class*='money']", ".salary"]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and len(t) < 20:
                            salary = t
                            break
                    except Exception:
                        pass

                area = ""
                for sel in [
                    "[class*='area']",
                    "[class*='city']",
                    "[class*='location']",
                    "[class*='region']",
                ]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and 2 < len(t) < 20 and any(k in t for k in ["市", "区"]):
                            area = t
                            break
                    except Exception:
                        pass

                company = ""
                for sel in [
                    "[class*='company']",
                    "[class*='corp']",
                    "[class*='enterprise']",
                ]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and 2 < len(t) < 40:
                            company = t
                            break
                    except Exception:
                        pass

                link = ""
                try:
                    if card.tag_name == "a":
                        link = card.get_attribute("href") or ""
                    else:
                        a_el = card.find_element(By.CSS_SELECTOR, "a")
                        link = a_el.get_attribute("href") or ""
                    if link and not link.startswith("http"):
                        link = "https://zwfw.mohrss.gov.cn" + link
                except Exception:
                    pass

                if job_name:
                    jobs.append(
                        {
                            "职位名称": job_name,
                            "公司名称": company,
                            "薪资": salary or "面议",
                            "工作地点": area,
                            "学历要求": "",
                            "来源平台": "中国公共招聘网",
                            "发布日期": today,
                            "链接": link,
                        }
                    )
            except Exception:
                pass
        log.info(f"[公共招聘网] 新增 {len(jobs) - before} 条")
    except Exception as e:
        log.error(f"[公共招聘网] 采集失败: {e}")

    return jobs


def save_results(new_jobs, keyword):
    """
    合并保存招聘数据（不覆盖，只追加去重）
    - 读取已有 jobs_latest.json，与新数据合并去重
    - 每条记录标记 first_seen（首次发现时间），用于 7 天过期清理
    - 每次保存时自动清理 7 天前的记录
    """
    import pandas as pd
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
                key = (
                    j.get("职位名称", ""),
                    j.get("公司名称", ""),
                    j.get("工作地点", ""),
                )
                existing_jobs[key] = j
        except Exception:
            existing_jobs = {}

    # ── 2. 合并新数据 ─────────────────────────────────
    added_count = 0
    for idx, job in enumerate(new_jobs):
        # 每条记录标记本次采集的关键词
        job["关键词"] = keyword

        platform = job.get("来源平台", "")
        if platform == "实习僧":
            # 实习僧搜索页每张卡片都是不同的实习岗位
            # → 用完整链接作为唯一 key；若链接为空则用 (公司+地点+职位名+序号) 防重
            link = job.get("链接", "").strip()
            if link:
                key = link
            else:
                key = "sx__%s__%s__%s__%d" % (
                    job.get("公司名称", ""),
                    job.get("工作地点", ""),
                    job.get("职位名称", ""),
                    idx,
                )
        else:
            key = (job.get("职位名称", ""), job.get("公司名称", ""))
        if key not in existing_jobs:
            # 新职位：标记首次出现时间
            job["first_seen"] = today
            existing_jobs[key] = job
            added_count += 1
        else:
            # 已存在：保留原有的 first_seen，同时追加关键词（多关键词搜索时）
            old = existing_jobs[key]
            old["first_seen"] = old.get("first_seen", today)
            # 合并关键词（逗号分隔，去重）
            old_kw = old.get("关键词", "")
            if old_kw and keyword not in old_kw.split(","):
                old["关键词"] = old_kw + "," + keyword
            elif not old_kw:
                old["关键词"] = keyword

    # ── 3. 过滤 7 天前过期数据 ─────────────────────────
    all_jobs = list(existing_jobs.values())
    before_count = len(all_jobs)
    all_jobs = [j for j in all_jobs if j.get("first_seen", "") >= expire_threshold]
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
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

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
def run_crawl(driver, keywords, success_keys):
    """执行采集（供交互模式和API调用共用）"""
    all_jobs = []
    for kw in keywords:
        print(f"\n  ▶ 正在采集：【{kw}】")
        jobs = crawl_with_cookies(driver, kw, success_keys)
        if jobs:
            print(f"  ✅ 【{kw}】采集到 {len(jobs)} 条")
            all_jobs.extend(jobs)
        else:
            print(f"  ⚠ 【{kw}】未采集到数据")

    if all_jobs:
        total = save_results(all_jobs, "，".join(keywords))
        print(f"\n  🎉 全部完成！本次新增 {len(all_jobs)} 条，当前累计 {total} 条")
        for j in all_jobs[:8]:
            print(
                f"    [{j['来源平台']}] {j['职位名称']} | {j['公司名称']} | {j['薪资']} | {j['工作地点']}"
            )
        if len(all_jobs) > 8:
            print(f"    ... 还有 {len(all_jobs) - 8} 条（见 data/ 目录）")
        return total
    else:
        print("\n  ⚠ 未采集到任何数据。可能原因：")
        print("    1. 登录 Cookie 已过期 → 重新运行本程序再登录一次")
        print("    2. 网站临时风控      → 稍后再试")
        print("    3. 网络连接问题      → 检查网络")
        total = save_results([], "，".join(keywords))
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
    args = parser.parse_args()

    # 自动模式：跳过登录，直接采集
    if args.keywords:
        keywords = [
            k.strip() for k in args.keywords.replace("，", ",").split(",") if k.strip()
        ]
        print(f"\n[自动模式] 关键词：{keywords}")
        driver = load_driver(headless=True)
        try:
            # 匿名平台（无需Cookie，直接参与采集）
            success_keys = ["51job", "liepin", "shixiseng"]

            # 尝试加载已有 Cookie（传入真实 domain URL）
            for name, label, domain_url in PLATFORMS:
                path = os.path.join(COOKIE_DIR, f"{name}.json")
                if os.path.exists(path):
                    load_cookies(driver, name, domain_url)
                    if name not in success_keys:
                        success_keys.append(name)
                    print(f"  已加载 Cookie: {name}")

            print(f"  有效平台：{success_keys}")
            count = run_crawl(driver, keywords, success_keys)
            print(f"\n[完成] 共采集 {count} 条")
        finally:
            # driver.quit() 在异常会话上可能永久挂起（无人值守服务器的真实事故），
            # 用看门狗强制退出，保证调度器不会被拖到超时
            import threading as _th

            def _force_exit():
                print("[Watchdog] driver.quit() 超时，强制退出进程")
                os._exit(0)

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
        run_crawl(driver, keywords, success_keys)

    finally:
        driver.quit()
        print("\n浏览器已关闭。")


if __name__ == "__main__":
    main()
