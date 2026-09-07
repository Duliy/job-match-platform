#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_cookie_tool.py — 构建「Cookie 采集工具」Windows 便携包

辅导员的典型场景：系统部署在服务器上，但采集 Cookie 需要在她自己的
Windows 电脑上登录招聘网站。这个便携包让她**不需要安装 Python**：
解压 → 双击运行.bat → 浏览器自动打开平台登录页 → 登录后自动保存 Cookie。

产物：dist_runtime_cache/cookie-tool-windows.zip
（构建便携包时会被纳入 downloads/ 供管理后台直接下载）
"""

import os
import shutil
import subprocess
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "dist_runtime_cache")
PYTHON_ZIP = os.path.join(CACHE_DIR, "python-3.8.10-embed-amd64.zip")
STAGE = os.path.join(CACHE_DIR, "cookie_tool_stage")
OUT = os.path.join(CACHE_DIR, "cookie-tool-windows.zip")

BAT = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Cookie 采集工具 - 就业服务平台
echo ============================================================
echo   Cookie 采集工具
echo.
echo   用途：智联招聘、猎聘网需要登录才能采集完整数据。
echo   接下来浏览器会自动打开各平台登录页，你依次登录即可。
echo   登录完成后回到这个黑窗口按回车。
echo.
echo   生成的 Cookie 文件会保存在 cookies 文件夹里，
echo   然后打开管理后台 - 爬虫系统 - Cookie 管理 上传即可。
echo ============================================================
echo.
python\python.exe cookie_collector.py
echo.
pause
"""


def main():
    if os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)

    # 1. 内嵌 Python
    print("[1/3] 内嵌 Python 3.8 ...")
    if not os.path.isfile(PYTHON_ZIP):
        raise SystemExit(
            f"缺少缓存的 Python embeddable: {PYTHON_ZIP}\n请先运行 build_portable.py 下载一次。"
        )
    py_dir = os.path.join(STAGE, "python")
    os.makedirs(py_dir)
    with zipfile.ZipFile(PYTHON_ZIP) as z:
        z.extractall(py_dir)
    # 启用 site-packages
    pth = os.path.join(py_dir, "python38._pth")
    with open(pth, "w", encoding="utf-8") as f:
        f.write("python38.zip\n.\nLib\\site-packages\n\nimport site\n")

    # 2. 离线 wheel（selenium + 依赖，win_amd64 / py38）
    print("[2/3] 下载 selenium 依赖 ...")
    site_pkgs = os.path.join(py_dir, "Lib", "site-packages")
    os.makedirs(site_pkgs, exist_ok=True)
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            site_pkgs,
            "--platform",
            "win_amd64",
            "--python-version",
            "3.8",
            "--implementation",
            "cp",
            "--abi",
            "cp38",
            "--only-binary=:all:",
            "--no-compile",
            "selenium==4.20.0",
        ]
    )

    # 3. 工具脚本
    print("[3/3] 打包工具脚本 ...")
    for f in ["cookie_collector.py", "portable_env.py"]:
        shutil.copy2(os.path.join(BASE_DIR, f), os.path.join(STAGE, f))
    with open(
        os.path.join(STAGE, "双击运行.bat"), "w", encoding="gbk", newline="\r\n"
    ) as f:
        f.write(BAT)
    os.makedirs(os.path.join(STAGE, "cookies"), exist_ok=True)

    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(STAGE):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, STAGE)
                z.write(full, os.path.join("Cookie采集工具", rel))
    print(f"\n✅ {OUT} ({os.path.getsize(OUT) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
