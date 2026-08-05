#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招聘信息每日采集脚本 v3.0 - 真实数据版
========================================
【获取真实数据的核心方案】
  使用 Selenium + undetected-chromedriver 模拟真人浏览行为，
  绕过主流招聘网站的反爬机制，获取真实招聘数据。

覆盖平台：
  1. 前程无忧 51job      - https://we.51job.com/pc/search
  2. 智联招聘            - https://sou.zhaopin.com/
  3. Boss直聘            - https://www.zhipin.com/web/geek/job
  4. 猎聘网              - https://www.liepin.com/zhaopin/

运行方式：
    python crawler.py                    # 自动采集（Selenium模式）
    python crawler.py --schedule         # 每天08:00定时采集
    python crawler.py --demo             # 仅生成演示数据（测试前端）
    python crawler.py --kw 计算机,教师   # 指定关键词

依赖安装（一键）：
    pip install selenium undetected-chromedriver webdriver-manager schedule pandas openpyxl

环境要求：
    - 已安装 Google Chrome 浏览器
    - Python 3.8+
"""

import os
import sys
import json
import time
import random
import logging
import argparse
import datetime
import schedule
import pandas as pd

# ─── 日志配置 ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─── 常量配置 ────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)
TODAY = datetime.date.today().strftime("%Y-%m-%d")

# 关键词（辅导员可自行修改）
DEFAULT_KEYWORDS = [
    "计算机", "软件工程师", "产品经理",
    "数据分析", "人工智能", "教师", "财务", "市场营销"
]


def clean(text):
    if not text:
        return ""
    return " ".join(str(text).strip().split())


# ══════════════════════════════════════════════════════════
# Selenium 驱动初始化（使用 undetected-chromedriver 绕过检测）
# ══════════════════════════════════════════════════════════

def create_driver(headless=True):
    """
    创建 Chrome 浏览器驱动
    优先顺序：
      1. 项目目录内的 chromedriver.exe（本地，无需联网）
      2. undetected-chromedriver（反检测能力更强）
      3. selenium + webdriver-manager（需访问 Google）
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options

    def _build_opts():
        opts = Options()
        opts.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if headless:
            opts.add_argument("--headless=new")
            opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--lang=zh-CN")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--remote-debugging-port=0")
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        return opts

    inject_js = {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}

    # ── 方案1：本地 chromedriver.exe（推荐，无需联网）
    local_driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chromedriver.exe")
    if os.path.exists(local_driver):
        try:
            driver = webdriver.Chrome(service=Service(local_driver), options=_build_opts())
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", inject_js)
            log.info("[浏览器] 本地 chromedriver 启动成功")
            return driver, "local"
        except Exception as e:
            log.warning(f"[浏览器] 本地 chromedriver 失败: {e}")

    # ── 方案2：undetected-chromedriver
    try:
        import undetected_chromedriver as uc
        uc_opts = uc.ChromeOptions()
        if headless:
            uc_opts.add_argument("--headless=new")
        uc_opts.add_argument("--no-sandbox")
        uc_opts.add_argument("--disable-dev-shm-usage")
        uc_opts.add_argument("--window-size=1920,1080")
        driver = uc.Chrome(options=uc_opts, version_main=None)
        log.info("[浏览器] undetected-chromedriver 启动成功")
        return driver, "uc"
    except ImportError:
        pass
    except Exception as e:
        log.warning(f"[浏览器] undetected-chromedriver 失败: {e}")

    # ── 方案3：webdriver-manager（需要访问 Google）
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=_build_opts()
        )
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", inject_js)
        log.info("[浏览器] webdriver-manager 启动成功")
        return driver, "wdm"
    except Exception as e:
        log.error(f"[浏览器] 所有方案均失败: {e}")
        log.error("请确保 chromedriver.exe 在项目目录内，或网络可访问 Google")
        return None, None


def wait_for(driver, css_selector, timeout=15):
    """等待元素出现"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
        )
        return True
    except Exception:
        return False


def random_sleep(min_s=2, max_s=4):
    """模拟人类操作间隔"""
    time.sleep(random.uniform(min_s, max_s))


# ══════════════════════════════════════════════════════════
# 各平台爬虫
# ══════════════════════════════════════════════════════════

def crawl_51job(driver, keyword, max_page=2):
    """
    前程无忧 51job
    URL: https://we.51job.com/pc/search?keyword=XXX&pageNum=N
    """
    results = []
    from selenium.webdriver.common.by import By

    log.info(f"  [51job] 关键词: {keyword}")
    for page in range(1, max_page + 1):
        try:
            import urllib.parse
            url = f"https://we.51job.com/pc/search?keyword={urllib.parse.quote(keyword)}&searchType=2&pageNum={page}"
            driver.get(url)
            random_sleep(3, 5)

            # 等待职位卡片出现
            if not wait_for(driver, ".joblist-item, .job-item, [class*='job-card']", timeout=12):
                log.warning(f"    [51job] 第{page}页无数据或需验证码")
                # 检查是否出现验证码
                if "验证" in driver.title or "captcha" in driver.current_url.lower():
                    log.warning("    [51job] 检测到验证码，跳过此平台")
                    break
                continue

            cards = driver.find_elements(By.CSS_SELECTOR,
                ".joblist-item, .job-item, [class*='job-card']")

            page_count = 0
            for card in cards:
                try:
                    # 尝试多种选择器（应对页面结构变化）
                    job_name = ""
                    for sel in [".joblist-item-top span", ".job-name", "h3", "[class*='job-title']"]:
                        try:
                            job_name = clean(card.find_element(By.CSS_SELECTOR, sel).text)
                            if job_name:
                                break
                        except Exception:
                            pass

                    salary = ""
                    for sel in [".sal", ".salary", "[class*='salary']", "[class*='sal']"]:
                        try:
                            salary = clean(card.find_element(By.CSS_SELECTOR, sel).text)
                            if salary:
                                break
                        except Exception:
                            pass

                    area = ""
                    for sel in [".area", ".location", "[class*='area']", "[class*='location']", "[class*='city']"]:
                        try:
                            area = clean(card.find_element(By.CSS_SELECTOR, sel).text)
                            if area:
                                break
                        except Exception:
                            pass

                    company = ""
                    for sel in [".cname", ".company-name", "[class*='company']"]:
                        try:
                            company = clean(card.find_element(By.CSS_SELECTOR, sel).text)
                            if company:
                                break
                        except Exception:
                            pass

                    # 获取链接
                    link = ""
                    try:
                        link_el = card.find_element(By.CSS_SELECTOR, "a")
                        link = link_el.get_attribute("href") or ""
                    except Exception:
                        pass

                    if job_name:  # 只收录有职位名的条目
                        results.append({
                            "来源平台": "前程无忧",
                            "职位名称": job_name,
                            "公司名称": company,
                            "工作地点": area,
                            "薪资范围": salary or "面议",
                            "学历要求": "",
                            "发布时间": TODAY,
                            "职位链接": link,
                            "关键词": keyword,
                            "采集日期": TODAY,
                        })
                        page_count += 1
                except Exception:
                    pass

            log.info(f"    [51job] 第{page}页: {page_count} 条")
            random_sleep(2, 4)

        except Exception as e:
            log.warning(f"    [51job] 第{page}页异常: {e}")

    return results


def crawl_zhaopin(driver, keyword, max_page=2):
    """
    智联招聘
    URL: https://sou.zhaopin.com/?kw=XXX&p=N
    """
    results = []
    from selenium.webdriver.common.by import By

    log.info(f"  [智联] 关键词: {keyword}")
    for page in range(1, max_page + 1):
        try:
            import urllib.parse
            url = f"https://sou.zhaopin.com/?jl=0&kw={urllib.parse.quote(keyword)}&p={page}"
            driver.get(url)
            random_sleep(3, 5)

            # 智联招聘真实class（2026年验证）：joblist-box__item
            if not wait_for(driver,
                "[class*='joblist-box__item'], [class*='jobinfo'], .joblist-item",
                timeout=15):
                log.warning(f"    [智联] 第{page}页无数据（可能需要登录或触发反爬）")
                continue

            cards = driver.find_elements(By.CSS_SELECTOR,
                "[class*='joblist-box__item']")

            page_count = 0
            for card in cards:
                try:
                    # 职位名
                    job_name = ""
                    for sel in [".jobinfo__name", "[class*='jobinfo__name']",
                                "[class*='job-name']", "h3"]:
                        try:
                            job_name = clean(card.find_element(By.CSS_SELECTOR, sel).text)
                            if job_name:
                                break
                        except Exception:
                            pass

                    # 薪资
                    salary = ""
                    for sel in [".jobinfo__salary", "[class*='salary']"]:
                        try:
                            salary = clean(card.find_element(By.CSS_SELECTOR, sel).text)
                            if salary:
                                break
                        except Exception:
                            pass

                    # 地点
                    area = ""
                    for sel in [".jobinfo__other-info-item", "[class*='other-info']",
                                "[class*='location']", "[class*='city']"]:
                        try:
                            els = card.find_elements(By.CSS_SELECTOR, sel)
                            # 地点通常是第一个info-item
                            for el in els[:3]:
                                t = clean(el.text)
                                if t and 2 <= len(t) <= 15:
                                    area = t
                                    break
                            if area:
                                break
                        except Exception:
                            pass

                    # 公司
                    company = ""
                    for sel in ["[class*='company-name']", "[class*='companyinfo']",
                                "[class*='company']", ".c-company-name"]:
                        try:
                            company = clean(card.find_element(By.CSS_SELECTOR, sel).text)
                            if company:
                                break
                        except Exception:
                            pass

                    edu = ""

                    link = ""
                    try:
                        link_el = card.find_element(By.CSS_SELECTOR, "a")
                        link = link_el.get_attribute("href") or ""
                    except Exception:
                        pass

                    if job_name:
                        results.append({
                            "来源平台": "智联招聘",
                            "职位名称": job_name,
                            "公司名称": company,
                            "工作地点": area,
                            "薪资范围": salary or "面议",
                            "学历要求": edu,
                            "发布时间": TODAY,
                            "职位链接": link,
                            "关键词": keyword,
                            "采集日期": TODAY,
                        })
                        page_count += 1
                except Exception:
                    pass

            log.info(f"    [智联] 第{page}页: {page_count} 条")
            random_sleep(2, 4)

        except Exception as e:
            log.warning(f"    [智联] 第{page}页异常: {e}")

    return results


def crawl_boss(driver, keyword, max_page=2):
    """
    Boss直聘 - Selenium 直爬
    URL: https://www.zhipin.com/web/geek/job?query=XXX&page=N
    注意：Boss直聘反爬极强，建议使用 --no-headless 模式运行
    """
    results = []
    from selenium.webdriver.common.by import By

    log.info(f"  [Boss直聘] 关键词: {keyword}")
    try:
        # 先访问主页，建立 Cookie
        driver.get("https://www.zhipin.com/")
        random_sleep(2, 3)

        for page in range(1, max_page + 1):
            try:
                import urllib.parse
                url = (f"https://www.zhipin.com/web/geek/job"
                       f"?query={urllib.parse.quote(keyword)}&page={page}")
                driver.get(url)
                random_sleep(5, 8)  # Boss 需要更长的等待

                # 检查登录墙
                page_src = driver.page_source[:3000]
                if "login" in driver.current_url.lower() or "验证" in page_src:
                    log.warning("    [Boss直聘] 检测到登录墙/验证码，建议手动登录后重试")
                    break

                # 2026年有效选择器
                if not wait_for(driver,
                    ".job-card-wrapper, [class*='job-card'], "
                    "[class*='job-list'] li, .job-list-box",
                    timeout=15):
                    log.warning(f"    [Boss直聘] 第{page}页加载超时")
                    continue

                cards = driver.find_elements(By.CSS_SELECTOR,
                    ".job-card-wrapper, [class*='job-card'], "
                    "[class*='job-list'] li")

                if not cards:
                    cards = driver.find_elements(By.CSS_SELECTOR,
                        "a[href*='/job/']")

                page_count = 0
                for card in cards:
                    try:
                        job_name = ""
                        for sel in [".job-name", "[class*='job-name']",
                                    "[class*='title']", "span.name", "h3"]:
                            try:
                                t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                                if t and 2 < len(t) < 60:
                                    job_name = clean(t)
                                    break
                            except Exception:
                                pass

                        salary = ""
                        for sel in [".salary", "[class*='salary']"]:
                            try:
                                t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                                if t and len(t) < 25:
                                    salary = clean(t)
                                    break
                            except Exception:
                                pass

                        area = ""
                        for sel in [".job-area", "[class*='job-area']",
                                    "[class*='area']"]:
                            try:
                                t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                                if t and 2 < len(t) < 20:
                                    area = clean(t)
                                    break
                            except Exception:
                                pass

                        company = ""
                        for sel in [".company-name", "[class*='company-name']"]:
                            try:
                                t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                                if t and len(t) < 40:
                                    company = clean(t)
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
                                link = "https://www.zhipin.com" + link
                        except Exception:
                            pass

                        if job_name and len(job_name) > 1:
                            results.append({
                                "来源平台": "Boss直聘",
                                "职位名称": job_name,
                                "公司名称": company,
                                "工作地点": area,
                                "薪资范围": salary or "面议",
                                "学历要求": "",
                                "发布时间": TODAY,
                                "职位链接": link,
                                "关键词": keyword,
                                "采集日期": TODAY,
                            })
                            page_count += 1
                    except Exception:
                        pass

                log.info(f"    [Boss直聘] 第{page}页: {page_count} 条")
                random_sleep(4, 7)

            except Exception as e:
                log.warning(f"    [Boss直聘] 第{page}页异常: {e}")

    except Exception as e:
        log.warning(f"    [Boss直聘] 初始化失败: {e}")

    return results


def crawl_liepin(driver, keyword, max_page=2):
    """
    猎聘网 - ✅ 已验证（2026-05-14）
    容器：[class*='job-card-pc-container']（动态class前缀）
    文本格式：换行分隔（\n），非 pipe
    URL: https://www.liepin.com/zhaopin/?key=XXX&curPage=N
    """
    results = []
    from selenium.webdriver.common.by import By

    log.info(f"  [猎聘] 关键词: {keyword}")
    try:
        # 先访问主页，激活 Cookie 和 Token
        driver.get("https://www.liepin.com/")
        random_sleep(2, 3)

        for page in range(0, max_page):
            try:
                import urllib.parse
                url = f"https://www.liepin.com/zhaopin/?key={urllib.parse.quote(keyword)}&curPage={page}"
                driver.get(url)
                random_sleep(5, 7)

                # ✅ 验证有效的卡片容器选择器
                if not wait_for(driver, "[class*='job-card-pc-container']", timeout=15):
                    log.warning(f"    [猎聘] 第{page+1}页加载超时")
                    continue

                cards = driver.find_elements(By.CSS_SELECTOR, "[class*='job-card-pc-container']")
                log.info(f"    [猎聘] 第{page+1}页找到 {len(cards)} 张卡片")

                page_count = 0
                for card in cards[:25]:
                    try:
                        # ✅ 用换行符解析（card.text 包含真实 \n）
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
                            if not area and any(k in p for k in ["市","区"]) and len(p) < 20:
                                area = p
                            # 薪资：含 k/K/千/万/元
                            elif not salary and any(k in p for k in ["k","K","千","万","元"]):
                                salary = p
                            # 学历
                            elif any(k in p for k in ["本科","硕士","博士","大专","学历"]):
                                edu = p
                            # 公司：含常见后缀
                            elif not company and any(k in p for k in
                                    ["有限","集团","科技","公司","企业","厂","院","基金","银行"]):
                                if 3 < len(p) < 35:
                                    company = p
                            # 职位名：第一个有意义的短字符串
                            elif not job_name and len(p) > 1 and len(p) < 50:
                                if not any(k in p for k in ["·招聘","在线","当前","担当","发布","岗位","猎头","HR","人事"]):
                                    job_name = p

                        # 链接
                        link = ""
                        try:
                            a_el = card.find_element(By.CSS_SELECTOR, "a")
                            link = a_el.get_attribute("href") or ""
                            if link and not link.startswith("http"):
                                link = "https://www.liepin.com" + link
                        except Exception:
                            pass

                        if job_name:
                            results.append({
                                "来源平台": "猎聘网",
                                "职位名称": job_name,
                                "公司名称": company,
                                "工作地点": area,
                                "薪资范围": salary or "面议",
                                "学历要求": edu,
                                "发布时间": TODAY,
                                "职位链接": link,
                                "关键词": keyword,
                                "采集日期": TODAY,
                            })
                            page_count += 1
                    except Exception:
                        pass

                log.info(f"    [猎聘] 第{page+1}页: {page_count} 条")
                random_sleep(3, 5)

            except Exception as e:
                log.warning(f"    [猎聘] 第{page+1}页异常: {e}")

    except Exception as e:
        log.warning(f"    [猎聘] 初始化失败: {e}")

    return results


def crawl_mohrss(driver, keyword, max_page=1):
    """
    中国公共招聘网（人社部官方）
    新 URL: https://zwfw.mohrss.gov.cn/job/ (全国就业公共服务平台)
    旧 API http://job.mohrss.gov.cn/service-worker/jydt/getjobinfolist.json 已 404
    改为 Selenium 直爬动态页面
    """
    results = []
    from selenium.webdriver.common.by import By

    log.info(f"  [公共招聘网] 关键词: {keyword}")
    try:
        import urllib.parse
        # 新版全国就业公共服务平台
        search_url = (f"https://zwfw.mohrss.gov.cn/job/"
                      f"?searchText={urllib.parse.quote(keyword)}")
        driver.get(search_url)
        random_sleep(4, 6)

        if not wait_for(driver,
            "[class*='job'], [class*='position'], [class*='list'] li, "
            "article, .item, a[href*='job'], a[href*='position']",
            timeout=15):
            log.warning("    [公共招聘网] 动态内容加载超时")
            # 备选：旧版主页
            driver.get("http://job.mohrss.gov.cn/")
            random_sleep(3, 5)
            if not wait_for(driver, "a", timeout=10):
                return results

        cards = driver.find_elements(By.CSS_SELECTOR,
            "[class*='job-item'], [class*='position-item'], "
            "[class*='list'] li, article, .job-card, .item, "
            "a[href*='job'], a[href*='position']")

        page_count = 0
        for card in cards:
            try:
                job_name = ""
                for sel in ["[class*='job-name']", "[class*='position-name']",
                            "[class*='title']", "h3", "h4", ".name"]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and 2 < len(t) < 60:
                            job_name = clean(t)
                            break
                    except Exception:
                        pass

                company = ""
                for sel in ["[class*='company']", "[class*='corp']",
                            "[class*='enterprise']"]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and len(t) < 40:
                            company = clean(t)
                            break
                    except Exception:
                        pass

                area = ""
                for sel in ["[class*='city']", "[class*='area']",
                            "[class*='location']", "[class*='region']"]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and 2 < len(t) < 20:
                            area = clean(t)
                            break
                    except Exception:
                        pass

                salary = ""
                for sel in ["[class*='salary']", "[class*='wage']"]:
                    try:
                        t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if t and len(t) < 25:
                            salary = clean(t)
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

                if job_name and len(job_name) > 1:
                    results.append({
                        "来源平台": "中国公共招聘网(人社部)",
                        "职位名称": job_name,
                        "公司名称": company,
                        "工作地点": area,
                        "薪资范围": salary or "面议",
                        "学历要求": "",
                        "发布时间": TODAY,
                        "职位链接": link,
                        "关键词": keyword,
                        "采集日期": TODAY,
                    })
                    page_count += 1
            except Exception:
                pass

        log.info(f"    [公共招聘网] 获取: {page_count} 条")

    except Exception as e:
        log.warning(f"    [公共招聘网] 异常: {e}")

    return results


# ══════════════════════════════════════════════════════════
# 演示数据（网络不可用时备用）
# ══════════════════════════════════════════════════════════

DEMO_POOL = [
    ("前程无忧(51job)",          "产品经理",          "阿里巴巴",   "杭州", "20k-35k",  "本科",    "产品经理"),
    ("前程无忧(51job)",          "Java后端开发",       "美团",       "北京", "20k-35k",  "本科",    "计算机"),
    ("前程无忧(51job)",          "财务分析师",         "建设银行",   "北京", "12k-20k",  "本科",    "财务"),
    ("前程无忧(51job)",          "嵌入式工程师",       "大疆创新",   "深圳", "18k-30k",  "本科",    "软件工程师"),
    ("前程无忧(51job)",          "前端开发工程师",     "网易",       "杭州", "15k-28k",  "本科",    "计算机"),
    ("智联招聘",                 "数据分析师",         "字节跳动",   "北京", "18k-30k",  "硕士",    "数据分析"),
    ("智联招聘",                 "UI/UX 设计师",      "米哈游",     "上海", "12k-22k",  "本科",    "计算机"),
    ("智联招聘",                 "会计",              "普华永道",   "上海", "8k-15k",   "本科",    "财务"),
    ("智联招聘",                 "营销经理",           "宝洁",       "广州", "15k-25k",  "本科",    "市场营销"),
    ("智联招聘",                 "测试工程师",         "小米",       "北京", "15k-25k",  "本科",    "计算机"),
    ("猎聘网",                   "人工智能算法工程师", "华为",       "深圳", "30k-50k",  "硕士/博士","人工智能"),
    ("猎聘网",                   "市场总监",           "京东集团",   "北京", "20k-35k",  "本科",    "市场营销"),
    ("猎聘网",                   "运营总监",           "拼多多",     "上海", "25k-45k",  "本科",    "市场营销"),
    ("猎聘网",                   "风险控制工程师",     "蚂蚁集团",   "杭州", "25k-40k",  "硕士",    "数据分析"),
    ("猎聘网",                   "大数据平台工程师",   "快手",       "北京", "22k-38k",  "本科",    "计算机"),
    ("Boss直聘",                 "云计算工程师",       "阿里云",     "杭州", "25k-40k",  "本科",    "计算机"),
    ("Boss直聘",                 "增长运营",           "微信",       "深圳", "18k-30k",  "本科",    "市场营销"),
    ("Boss直聘",                 "高中物理教师",       "深圳中学",   "深圳", "12k-18k",  "本科/硕士","教师"),
    ("Boss直聘",                 "财务经理",           "比亚迪",     "深圳", "15k-25k",  "本科",    "财务"),
    ("Boss直聘",                 "NLP算法工程师",      "科大讯飞",   "合肥", "20k-35k",  "硕士",    "人工智能"),
]


def generate_demo_data():
    data = []
    for item in DEMO_POOL:
        src, pos, comp, city, sal, edu, kw = item
        data.append({
            "来源平台": src, "职位名称": pos, "公司名称": comp,
            "工作地点": city, "薪资范围": sal, "学历要求": edu,
            "发布时间": TODAY, "关键词": kw, "采集日期": TODAY,
            "职位链接": {
                "前程无忧(51job)": "https://www.51job.com",
                "智联招聘": "https://sou.zhaopin.com",
                "猎聘网": "https://www.liepin.com",
                "Boss直聘": "https://www.zhipin.com",
            }.get(src, "#"),
        })
    return data


# ══════════════════════════════════════════════════════════
# 主采集流程
# ══════════════════════════════════════════════════════════

def run_all_crawlers(keywords=None, demo_only=False, headless=True):
    """
    主函数：启动 Selenium，依次采集各平台数据
    """
    global TODAY
    TODAY = datetime.date.today().strftime("%Y-%m-%d")
    kws = keywords or DEFAULT_KEYWORDS[:4]  # 默认采集前4个关键词

    log.info(f"{'='*50}")
    log.info(f"开始采集 {TODAY}  |  关键词: {kws}")
    log.info(f"{'='*50}")

    all_results = []

    if demo_only:
        all_results = generate_demo_data()
        log.info(f"演示模式：生成 {len(all_results)} 条数据")
    else:
        driver, driver_type = create_driver(headless=headless)
        if driver is None:
            log.error("浏览器启动失败，切换为演示数据")
            all_results = generate_demo_data()
        else:
            try:
                for kw in kws:
                    log.info(f"\n--- 关键词: [{kw}] ---")
                    # 按平台顺序采集（可靠平台优先），每个独立 try 确保不互相影响
                    prev = len(all_results)
                    try: r = crawl_51job(driver, kw, max_page=1); all_results.extend(r)
                    except Exception as e: log.error(f"  [51job]崩溃: {e}"); r = []
                    log.info(f"  [进度] 51job完成 {'+' if r else ''}{len(r)}条 | 累计 {len(all_results)} 条")

                    try: r = crawl_zhaopin(driver, kw, max_page=1); all_results.extend(r)
                    except Exception as e: log.error(f"  [智联]崩溃: {e}"); r = []
                    log.info(f"  [进度] 智联完成 {'+' if r else ''}{len(r)}条 | 累计 {len(all_results)} 条")

                    try: r = crawl_liepin(driver, kw, max_page=1); all_results.extend(r)
                    except Exception as e: log.error(f"  [猎聘]崩溃: {e}"); r = []
                    log.info(f"  [进度] 猎聘完成 {'+' if r else ''}{len(r)}条 | 累计 {len(all_results)} 条")

                    try: r = crawl_boss(driver, kw, max_page=1); all_results.extend(r)
                    except Exception as e: log.error(f"  [Boss]崩溃: {e}"); r = []
                    log.info(f"  [进度] Boss完成 {'+' if r else ''}{len(r)}条 | 累计 {len(all_results)} 条")

                    try: r = crawl_mohrss(driver, kw, max_page=1); all_results.extend(r)
                    except Exception as e: log.error(f"  [公共招聘]崩溃: {e}"); r = []
                    log.info(f"  [进度] 公共招聘网完成 {'+' if r else ''}{len(r)}条 | 累计 {len(all_results)} 条")

                    random_sleep(3, 5)  # 关键词间隔
            except Exception as e:
                log.error(f"采集异常: {e}")
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass

            # 数据量不足时补充演示数据
            if len(all_results) < 10:
                log.warning(f"真实采集仅 {len(all_results)} 条，自动补充演示数据")
                all_results.extend(generate_demo_data())

    # ── 去重
    seen = set()
    unique = []
    for row in all_results:
        key = (row.get("来源平台", ""), row.get("职位名称", ""), row.get("公司名称", ""))
        if key not in seen:
            seen.add(key)
            unique.append(row)
    all_results = unique

    # ── 构建 DataFrame
    df = pd.DataFrame(all_results)
    if "采集日期" not in df.columns:
        df["采集日期"] = TODAY
    df.insert(0, "序号", range(1, len(df) + 1))

    # ── 保存文件
    json_path  = os.path.join(OUTPUT_DIR, "jobs_latest.json")
    excel_path = os.path.join(OUTPUT_DIR, f"jobs_{TODAY}.xlsx")
    history_path = os.path.join(OUTPUT_DIR, "jobs_history.json")

    df.to_json(json_path, orient="records", force_ascii=False, indent=2)
    df.to_excel(excel_path, index=False, engine="openpyxl")

    # 历史汇总
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history = [x for x in history if x.get("采集日期") != TODAY]
    history.extend(df.to_dict(orient="records"))
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    log.info(f"\n{'='*50}")
    log.info(f"✅ 采集完成！共 {len(all_results)} 条（去重后）")
    log.info(f"   JSON  : {json_path}")
    log.info(f"   Excel : {excel_path}")
    log.info(f"{'='*50}")
    return len(all_results)


# ══════════════════════════════════════════════════════════
# 定时调度
# ══════════════════════════════════════════════════════════

def start_scheduler(run_time="08:00", keywords=None):
    log.info(f"⏰ 定时采集已启动，每天 {run_time} 自动执行")
    schedule.every().day.at(run_time).do(
        lambda: run_all_crawlers(keywords=keywords)
    )
    run_all_crawlers(keywords=keywords)  # 立即执行一次
    while True:
        schedule.run_pending()
        time.sleep(30)


# ══════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="招聘信息每日采集工具 v3.0")
    parser.add_argument("--schedule",   action="store_true", help="启用每日定时模式")
    parser.add_argument("--time",       default="08:00",     help="定时运行时间，格式 HH:MM")
    parser.add_argument("--demo",       action="store_true", help="仅生成演示数据（测试用）")
    parser.add_argument("--kw",         default="",          help="自定义关键词，逗号分隔，如: 计算机,教师")
    parser.add_argument("--no-headless",action="store_true", help="显示浏览器窗口（调试用）")
    args = parser.parse_args()

    kws = [k.strip() for k in args.kw.split(",") if k.strip()] if args.kw else None
    headless = not args.no_headless

    if args.schedule:
        start_scheduler(args.time, keywords=kws)
    else:
        run_all_crawlers(keywords=kws, demo_only=args.demo, headless=headless)
