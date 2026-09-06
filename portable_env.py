#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portable_env.py — 便携包环境解析

绿色便携包内嵌 Chrome 与 chromedriver，运行时按以下优先级解析：
  1. 环境变量 CHROME_BINARY / CHROMEDRIVER_PATH（手动覆盖）
  2. 便携包内置 runtime/chrome/chrome.exe 与 chromedriver.exe
  3. 项目根目录下的 chromedriver.exe（兼容旧布局）
  4. 系统安装的 Chrome（常见安装路径 + PATH）
"""

import os
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_SYSTEM_CHROME_PATHS = [
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome_binary():
    """返回可用的 chrome.exe 路径，找不到返回 None"""
    env = os.environ.get("CHROME_BINARY", "").strip()
    if env and os.path.isfile(env):
        return env

    bundled = os.path.join(BASE_DIR, "runtime", "chrome", "chrome.exe")
    if os.path.isfile(bundled):
        return bundled

    for p in _SYSTEM_CHROME_PATHS:
        if os.path.isfile(p):
            return p

    which = (
        shutil.which("chrome")
        or shutil.which("chrome.exe")
        or shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if which:
        return which
    return None


def find_chromedriver():
    """返回可用的 chromedriver 路径，找不到返回 None"""
    env = os.environ.get("CHROMEDRIVER_PATH", "").strip()
    if env and os.path.isfile(env):
        return env

    bundled = os.path.join(BASE_DIR, "runtime", "chrome", "chromedriver.exe")
    if os.path.isfile(bundled):
        return bundled

    local = os.path.join(BASE_DIR, "chromedriver.exe")
    if os.path.isfile(local):
        return local

    which = shutil.which("chromedriver") or shutil.which("chromedriver.exe")
    return which
