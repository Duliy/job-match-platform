#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cookie_collector.py — 一键采集招聘平台登录 Cookie

功能：
  - 依次打开各招聘平台登录页面
  - 让用户在浏览器中手动登录
  - 自动保存 Cookie 到 cookies/ 目录
  - 不涉及数据采集（爬取另由启动器完成）

用法：
  双击"一键采集cookie.bat" 即可运行

平台列表：
  - 51job（前程无忧）   — 无需登录，自动跳过
  - 智联招聘          — 需要登录
  - 猎聘网            — 需要登录
  - 实习僧            — 无需登录，自动跳过
  - 国聘网            — 需要登录
  - Boss直聘          — 无法登录（跳过）
"""
import os
import sys
import json
import time

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
COOKIE_DIR = os.path.join(BASE_DIR, "cookies")
os.makedirs(COOKIE_DIR, exist_ok=True)

PLATFORMS = [
    ("zhaopin",  "智联招聘",  "https://passport.zhaopin.com/login", True),
    ("liepin",   "猎聘网",    "https://www.liepin.com/",            True),
    ("guopin",   "国聘网",    "https://www.iguopin.com/",           True),
]


def load_driver():
    """启动 Chrome（可见窗口，用于手动登录）"""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    opts = webdriver.Chrome.options.Options()
    opts.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=zh-CN")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("detach", True)

    # 使用临时用户目录，避免污染用户日常 Chrome
    import tempfile
    tmp_dir = os.path.join(tempfile.gettempdir(), "jb_cookie_profile")
    os.makedirs(tmp_dir, exist_ok=True)
    opts.add_argument(f"--user-data-dir={tmp_dir}")

    local_drv = os.path.join(BASE_DIR, "chromedriver.exe")
    try:
        drv = webdriver.Chrome(service=Service(local_drv), options=opts)
    except Exception:
        drv = webdriver.Chrome(options=opts)

    drv.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return drv


def main():
    print("\n" + "=" * 52)
    print("  招聘平台 Cookie 一键采集工具")
    print("=" * 52)
    print()
    print("说明：")
    print("  本工具将依次打开招聘平台登录页面。")
    print("  请在浏览器中完成登录，然后回到本窗口按回车。")
    print("  登录成功的 Cookie 将自动保存到 cookies/ 文件夹。")
    print()
    print("提示：")
    print("  1. 前程无忧、实习僧 — 无需登录，无需采集 Cookie")
    print("  2. 智联招聘、猎聘网 — 需要登录（推荐登录）")
    print("  3. 国聘网 — 需要登录")
    print("  4. 不想登录某个平台时，直接按回车跳过即可")
    print()
    print("=" * 52)

    try:
        driver = load_driver()
    except Exception as e:
        print(f"\n[错误] Chrome 浏览器启动失败：{e}")
        print()
        print("可能原因：")
        print("  1. 未安装 Google Chrome 浏览器")
        print("  2. chromedriver.exe 与 Chrome 版本不兼容")
        print()
        print("请确认 Chrome 已安装后再运行本程序。")
        input("\n按回车键退出...")
        return

    saved = []
    skipped = []

    try:
        for key, name, url, needs_login in PLATFORMS:
            print(f"\n{'─' * 52}")
            print(f"  【{name}】")
            print(f"  登录地址：{url}")
            print(f"  {'─' * 52}")

            try:
                driver.get(url)
                time.sleep(2)
            except Exception as e:
                print(f"  [警告] 页面打开失败：{e}")
                print(f"  将跳过该平台。")
                skipped.append(name)
                continue

            print()
            print(f"  请在浏览器窗口中完成【{name}】的登录。")
            print(f"  登录完成后，回到本窗口按回车键保存 Cookie。")
            print(f"  如果不需要登录该平台，直接按回车键跳过。")
            print()

            try:
                input(f"  [{name}] 登录完成后按回车...")
            except KeyboardInterrupt:
                print("\n\n  已中断，正在退出...")
                break

            cks = driver.get_cookies()
            if cks:
                path = os.path.join(COOKIE_DIR, f"{key}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(cks, f, ensure_ascii=False, indent=2)
                saved.append((name, len(cks)))
                print(f"  [成功] Cookie 已保存：{path}（共 {len(cks)} 条）")
            else:
                skipped.append(name)
                print(f"  [跳过] 未获取到 Cookie，已跳过该平台。")

    finally:
        driver.quit()

    print("\n" + "=" * 52)
    print("  Cookie 采集完成")
    print("=" * 52)

    if saved:
        print()
        print(f"  已保存 Cookie 的平台（共 {len(saved)} 个）：")
        for name, cnt in saved:
            print(f"    [✅] {name} — {cnt} 条 Cookie")

    if skipped:
        print()
        print(f"  未采集 / 跳过的平台（共 {len(skipped)} 个）：")
        for name in skipped:
            print(f"    [⏭️] {name}")

    print()
    print("  Cookie 文件已保存在：")
    print(f"    {COOKIE_DIR}")
    print()
    print("  现在可以关闭本窗口，然后启动 JobBoard 系统。")
    print("  在管理后台中使用"立即采集"功能，系统将自动调用已保存的 Cookie。")
    print()
    print("=" * 52)

    input("\n  按回车键退出...")


if __name__ == "__main__":
    main()
