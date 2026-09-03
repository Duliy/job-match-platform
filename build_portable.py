#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_portable.py — 校园版便携包组装脚本（在 Linux 构建机上运行）

把项目代码 + 内嵌 Python 3.8 + Chrome 109 + chromedriver + vc_redist
组装成一个 zip，辅导员拿到后「解压 → 双击启动系统.bat」即可。

用法：
  python3 build_portable.py              # 完整构建（联网下载运行库）
  python3 build_portable.py --skip-downloads   # 仅刷新代码部分（runtime 已存在时）

产物：dist/就业服务平台-校园版.zip
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
PKG_DIR = os.path.join(DIST_DIR, "就业服务平台-校园版")
RUNTIME_DIR = os.path.join(BASE_DIR, "dist_runtime_cache")  # 下载的运行库缓存

# ── 下载源 ──────────────────────────────────────────────────
PYTHON_EMBED_URL = (
    "https://www.python.org/ftp/python/3.8.10/python-3.8.10-embed-amd64.zip"
)
# Chrome 109.0.5414.74（最后一个支持 Win7/8/Server2012 的版本）对应的 Chromium 快照
CHROME_URL = "https://www.googleapis.com/download/storage/v1/b/chromium-browser-snapshots/o/Win_x64%2F1070094%2Fchrome-win.zip?alt=media"
CHROMEDRIVER_URL = (
    "https://chromedriver.storage.googleapis.com/109.0.5414.74/chromedriver_win32.zip"
)
# VS2015-2019 14.28（支持 Server 2012 的运行库，含 UCRT）
VC_REDIST_URL = "https://aka.ms/vs/16/release/vc_redist.x64.exe"

# ── 打包进 zip 的项目文件（白名单）─────────────────────────
CODE_FILES = [
    # 后端
    "match_api.py",
    "match_ai.py",
    "match_db.py",
    "match_utils.py",
    "admin_api.py",
    "auth.py",
    "scheduler.py",
    "db_schema_v2.py",
    "import_data.py",
    "portable_env.py",
    "serve.py",
    "init_admin.py",
    "环境预检.py",
    # 爬虫
    "login_helper.py",
    "gongkao_crawler.py",
    "cookie_collector.py",
    # 前端
    "index.html",
    "resume_match.html",
    "admin.html",
    "manifest.json",
    "icon-192.png",
    "icon-512.png",
    # 入口脚本
    "启动系统.bat",
    "停止服务.bat",
    "安装开机自启.bat",
    "取消开机自启.bat",
    "Cookie采集工具.bat",
    "环境预检.bat",
    # 文档
    "辅导员手册.md",
]


def download(url, dest, desc):
    if os.path.exists(dest):
        print(f"  [缓存] {desc}")
        return
    print(f"  [下载] {desc}\n         {url}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    print(f"         -> {os.path.getsize(dest) / 1024 / 1024:.1f} MB")


def step_python():
    """内嵌 Python 3.8 + 依赖"""
    cache_zip = os.path.join(RUNTIME_DIR, "python-3.8.10-embed-amd64.zip")
    download(PYTHON_EMBED_URL, cache_zip, "Python 3.8.10 embeddable (win64)")

    py_dir = os.path.join(PKG_DIR, "runtime", "python")
    os.makedirs(py_dir, exist_ok=True)
    with zipfile.ZipFile(cache_zip) as z:
        z.extractall(py_dir)
    print("  [解压] Python 运行时")

    # 启用 site-packages（embeddable 默认关闭）
    pth = os.path.join(py_dir, "python38._pth")
    with open(pth, "w", encoding="utf-8") as f:
        f.write("python38.zip\n.\nLib\\site-packages\n\nimport site\n")
    print("  [配置] python38._pth 启用 site-packages")

    # 交叉安装 Windows 依赖
    site_pkgs = os.path.join(py_dir, "Lib", "site-packages")
    os.makedirs(site_pkgs, exist_ok=True)
    print("  [pip] 交叉下载安装依赖（win_amd64 / py38）...")
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
            "--upgrade",
            "-r",
            os.path.join(BASE_DIR, "requirements-portable.txt"),
        ]
    )
    print("  [pip] 依赖安装完成")


def step_chrome():
    """Chrome 109 + chromedriver"""
    chrome_dir = os.path.join(PKG_DIR, "runtime", "chrome")
    os.makedirs(chrome_dir, exist_ok=True)

    cache_zip = os.path.join(RUNTIME_DIR, "chrome-win-109.zip")
    download(CHROME_URL, cache_zip, "Chromium 109 (Win_x64 snapshot 1070094)")
    with zipfile.ZipFile(cache_zip) as z:
        z.extractall(os.path.join(RUNTIME_DIR, "chrome109"))
    src = os.path.join(RUNTIME_DIR, "chrome109", "chrome-win")
    for item in os.listdir(src):
        shutil.move(os.path.join(src, item), os.path.join(chrome_dir, item))
    print("  [解压] Chrome 109")

    cache_drv = os.path.join(RUNTIME_DIR, "chromedriver-109.zip")
    download(CHROMEDRIVER_URL, cache_drv, "chromedriver 109.0.5414.74")
    with zipfile.ZipFile(cache_drv) as z:
        z.extractall(chrome_dir)
    print("  [解压] chromedriver")


def step_vcredist():
    cache_exe = os.path.join(RUNTIME_DIR, "vc_redist.x64.exe")
    download(VC_REDIST_URL, cache_exe, "VC++ 运行库 (vc_redist.x64)")
    shutil.copy(cache_exe, os.path.join(PKG_DIR, "runtime", "vc_redist.x64.exe"))
    print("  [复制] vc_redist")


def step_code():
    for f in CODE_FILES:
        src = os.path.join(BASE_DIR, f)
        if not os.path.isfile(src):
            print(f"  [警告] 缺少文件: {f}")
            continue
        shutil.copy2(src, os.path.join(PKG_DIR, f))
    # 空目录占位
    for d in ["data", "cookies"]:
        os.makedirs(os.path.join(PKG_DIR, d), exist_ok=True)
    print(f"  [复制] {len(CODE_FILES)} 个项目文件")


def step_zip():
    zip_path = os.path.join(DIST_DIR, "就业服务平台-校园版.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    print("  [打包] 生成 zip ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(DIST_DIR):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, DIST_DIR)
                if full == zip_path:
                    continue
                z.write(full, rel)
    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print(f"\n✅ 构建完成: {zip_path} ({size_mb:.0f} MB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-downloads",
        action="store_true",
        help="跳过运行库下载/安装（runtime 缓存已存在时刷新代码用）",
    )
    args = parser.parse_args()

    os.makedirs(PKG_DIR, exist_ok=True)

    print("=" * 56)
    print("  校园版便携包构建")
    print("=" * 56)

    if not args.skip_downloads:
        print("\n[1/4] 内嵌 Python + 依赖")
        step_python()
        print("\n[2/4] Chrome 109 + chromedriver")
        step_chrome()
        print("\n[3/4] VC++ 运行库")
        step_vcredist()
    else:
        print("\n[跳过] 运行库（--skip-downloads）")

    print("\n[4/4] 项目代码 + 打包")
    step_code()
    step_zip()


if __name__ == "__main__":
    main()
