#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_portable_linux.py — Linux 便携包组装脚本（在构建机上运行）

理念与 Windows 便携包一致：所有运行时（Python 独立构建版 + 全部 pip 依赖
离线 wheel + Chrome for Testing + chromedriver）都打进 tar.gz，
目标服务器**零联网安装**——只需要解压 → 运行 install.sh。

用法：
  python3 build_portable_linux.py                  # 完整构建
  python3 build_portable_linux.py --skip-downloads # 仅刷新代码

产物：dist/就业服务平台-校园版-linux.tar.gz
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
PKG_DIR = os.path.join(DIST_DIR, "jobboard-linux")
CACHE_DIR = os.path.join(BASE_DIR, "dist_runtime_cache")

PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-x86_64-unknown-linux-gnu-install_only.tar.gz"
CFT_VERSION = "131.0.6778.204"
CHROME_URL = f"https://storage.googleapis.com/chrome-for-testing-public/{CFT_VERSION}/linux64/chrome-linux64.zip"
CHROMEDRIVER_URL = f"https://storage.googleapis.com/chrome-for-testing-public/{CFT_VERSION}/linux64/chromedriver-linux64.zip"

# 与 Windows 便携包共用同一份代码清单
from build_portable import CODE_FILES  # noqa: E402

LINUX_FILES = CODE_FILES + [
    "install.sh",
    "start.sh",
    "Linux部署.md",
]


def download(url, dest, desc):
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        print(f"  [缓存] {desc}")
        return
    print(f"  [下载] {desc}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    print(f"         -> {os.path.getsize(dest) / 1024 / 1024:.1f} MB")


def step_python():
    cache = os.path.join(CACHE_DIR, "python-3.12-linux-standalone.tar.gz")
    download(PYTHON_URL, cache, "Python 3.12 独立构建版 (linux x86_64)")
    py_dir = os.path.join(PKG_DIR, "runtime", "python")
    shutil.rmtree(py_dir, ignore_errors=True)
    os.makedirs(py_dir, exist_ok=True)
    with tarfile.open(cache) as t:
        t.extractall(py_dir, filter="data")
    # install_only 解压后是 python/ 子目录，拍平
    inner = os.path.join(py_dir, "python")
    if os.path.isdir(inner):
        for item in os.listdir(inner):
            shutil.move(os.path.join(inner, item), os.path.join(py_dir, item))
        os.rmdir(inner)
    print("  [解压] Python 运行时")


def step_wheels():
    """交叉下载 linux x86_64 / py3.12 的全部依赖 wheel（离线安装用）"""
    wheels_dir = os.path.join(PKG_DIR, "wheels")
    os.makedirs(wheels_dir, exist_ok=True)
    print("  [pip] 交叉下载依赖 wheel（manylinux_x86_64 / py312）...")
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--dest",
            wheels_dir,
            "--platform",
            "manylinux2014_x86_64",
            "--python-version",
            "3.12",
            "--implementation",
            "cp",
            "--abi",
            "cp312",
            "--only-binary=:all:",
            "-r",
            os.path.join(BASE_DIR, "requirements-linux.txt"),
        ]
    )
    print(f"  [pip] {len(os.listdir(wheels_dir))} 个 wheel 已就绪")


def step_chrome():
    chrome_dir = os.path.join(PKG_DIR, "runtime", "chrome")
    os.makedirs(chrome_dir, exist_ok=True)

    cache_zip = os.path.join(CACHE_DIR, f"chrome-linux64-{CFT_VERSION}.zip")
    download(CHROME_URL, cache_zip, f"Chrome for Testing {CFT_VERSION} (linux64)")
    stage = os.path.join(CACHE_DIR, "chrome_cft")
    with zipfile.ZipFile(cache_zip) as z:
        z.extractall(stage)
    src = os.path.join(stage, "chrome-linux64")
    for item in os.listdir(src):
        shutil.move(os.path.join(src, item), os.path.join(chrome_dir, item))
    shutil.rmtree(stage, ignore_errors=True)
    print("  [解压] Chrome")

    cache_drv = os.path.join(CACHE_DIR, f"chromedriver-linux64-{CFT_VERSION}.zip")
    download(CHROMEDRIVER_URL, cache_drv, f"chromedriver {CFT_VERSION} (linux64)")
    with zipfile.ZipFile(cache_drv) as z:
        for name in z.namelist():
            if name.endswith("/chromedriver") or name == "chromedriver":
                with (
                    z.open(name) as f_in,
                    open(os.path.join(chrome_dir, "chromedriver"), "wb") as f_out,
                ):
                    shutil.copyfileobj(f_in, f_out)
    os.chmod(os.path.join(chrome_dir, "chromedriver"), 0o755)
    # 所有可执行文件加执行权限（chrome_crashpad_handler 等，tar 传输后可能丢）
    for root, _dirs, files in os.walk(chrome_dir):
        for fn in files:
            fp = os.path.join(root, fn)
            if os.path.isfile(fp):
                os.chmod(fp, 0o755)
    print("  [解压] chromedriver")


def step_code():
    for f in LINUX_FILES:
        src = os.path.join(BASE_DIR, f)
        if not os.path.isfile(src):
            print(f"  [警告] 缺少文件: {f}")
            continue
        dst = os.path.join(PKG_DIR, f)
        shutil.copy2(src, dst)
    # bat 文件对 Linux 无意义，剔除
    for f in os.listdir(PKG_DIR):
        if f.endswith(".bat"):
            os.remove(os.path.join(PKG_DIR, f))
    for d in ["data", "cookies"]:
        os.makedirs(os.path.join(PKG_DIR, d), exist_ok=True)
    # 种子数据
    seed_db = os.path.join(BASE_DIR, "data", "jobs.db")
    if os.path.isfile(seed_db):
        import sqlite3 as _sq

        _conn = _sq.connect(seed_db)
        try:
            n = _conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            g = _conn.execute("SELECT COUNT(*) FROM gk_jobs").fetchone()[0]
        except Exception:
            n = g = 0
        _conn.close()
        if n + g > 0:
            dst = os.path.join(PKG_DIR, "data", "jobs.db")
            s = _sq.connect(seed_db)
            d = _sq.connect(dst)
            s.backup(d)
            d.close()
            s.close()
            print(f"  [种子数据] 社招 {n} 条 + 公考 {g} 条")
    os.chmod(os.path.join(PKG_DIR, "install.sh"), 0o755)
    os.chmod(os.path.join(PKG_DIR, "start.sh"), 0o755)
    print(f"  [复制] {len(LINUX_FILES)} 个项目文件")


def step_tar():
    out = os.path.join(DIST_DIR, "就业服务平台-校园版-linux.tar.gz")
    if os.path.exists(out):
        os.remove(out)
    print("  [打包] 生成 tar.gz ...")
    with tarfile.open(out, "w:gz", compresslevel=6) as t:
        t.add(PKG_DIR, arcname="jobboard")
    size_mb = os.path.getsize(out) / 1024 / 1024
    print(f"\n✅ 构建完成: {out} ({size_mb:.0f} MB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-downloads", action="store_true")
    args = parser.parse_args()

    os.makedirs(PKG_DIR, exist_ok=True)
    print("=" * 56)
    print("  Linux 便携包构建（目标服务器零联网安装）")
    print("=" * 56)

    if not args.skip_downloads:
        print("\n[1/4] Python 独立构建版")
        step_python()
        print("\n[2/4] 依赖 wheel（离线）")
        step_wheels()
        print("\n[3/4] Chrome for Testing + chromedriver")
        step_chrome()
    else:
        print("\n[跳过] 运行库（--skip-downloads）")

    print("\n[4/4] 项目代码 + 打包")
    step_code()
    step_tar()


if __name__ == "__main__":
    main()
