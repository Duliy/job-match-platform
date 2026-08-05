#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_exe.py — 打包 launcher.py 为单文件 EXE
用法：  python build_exe.py
输出：  dist/JobBoard启动器.exe
"""

import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    print("=" * 55)
    print("  JobBoard 启动器 — EXE 打包工具")
    print("=" * 55)

    # 1. 确保 pyinstaller 已安装
    try:
        import PyInstaller
        print(f"✅ PyInstaller {PyInstaller.__version__} 已就绪")
    except ImportError:
        print("⚙️ 安装 PyInstaller ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "-q"])
        print("✅ PyInstaller 安装完成")

    # 2. 图标（可选，有 icon.ico 就用）
    icon_path = os.path.join(BASE_DIR, "icon.ico")
    icon_arg = ["--icon", icon_path] if os.path.exists(icon_path) else []

    # 3. 调用 PyInstaller
    dist_dir = os.path.join(BASE_DIR, "dist")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                        # 单文件
        "--windowed",                       # 无黑色控制台窗口（GUI 模式）
        "--name", "JobBoard启动器",
        "--distpath", dist_dir,
        "--workpath", os.path.join(BASE_DIR, "build"),
        "--specpath", BASE_DIR,
        # 把前端文件一起打包（仅打包 HTML/JS/CSS/图标，不打包 Python）
        "--add-data", f"{os.path.join(BASE_DIR, 'index.html')}{os.pathsep}.",
        "--add-data", f"{os.path.join(BASE_DIR, 'resume_match.html')}{os.pathsep}.",
        "--add-data", f"{os.path.join(BASE_DIR, 'admin.html')}{os.pathsep}.",
        "--add-data", f"{os.path.join(BASE_DIR, 'manifest.json')}{os.pathsep}.",
        "--add-data", f"{os.path.join(BASE_DIR, 'requirements.txt')}{os.pathsep}.",
        "--add-data", f"{os.path.join(BASE_DIR, 'requirements_match.txt')}{os.pathsep}.",
        "--add-data", f"{os.path.join(BASE_DIR, 'serve.js')}{os.pathsep}.",
    ] + icon_arg + [
        os.path.join(BASE_DIR, "launcher.py"),
    ]

    print("\n🏗️  开始打包（可能需要 1-3 分钟）...\n")
    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode == 0:
        exe_path = os.path.join(dist_dir, "JobBoard启动器.exe")
        size_mb = os.path.getsize(exe_path) / 1024 / 1024
        print("\n" + "=" * 55)
        print(f"✅  打包成功！")
        print(f"   文件: {exe_path}")
        print(f"   大小: {size_mb:.1f} MB")
        print("=" * 55)
        print("\n📦  使用说明：")
        print("   1. 将 JobBoard启动器.exe 与整个项目目录一起发给用户")
        print("   2. 确保 Python 和 Node.js 已安装（启动器会自动检测）")
        print("   3. 用户双击 JobBoard启动器.exe 即可")
    else:
        print("\n❌  打包失败，请检查以上错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
