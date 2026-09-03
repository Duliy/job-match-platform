#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serve.py — 就业服务平台（校园版）一键启动器

职责：
  1. 环境自检（UCRT 运行库，缺失时尝试静默安装随包 vc_redist）
  2. 首次运行初始化（设置管理员密码）
  3. 防火墙放行（端口 8000，尽力而为）
  4. 计算局域网 IP（邮件链接用 PUBLIC_BASE_URL）
  5. 启动 FastAPI 服务（含前端页面 + API + 定时采集调度，单进程）
  6. 打印访问地址 / 自动打开浏览器（--background 模式跳过）

用法：
  python serve.py              # 前台运行（双击 启动系统.bat）
  python serve.py --background # 后台运行（开机自启计划任务用）
"""

import os
import socket
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

PORT = int(os.environ.get("PORT", "8000"))
BACKGROUND = "--background" in sys.argv


def info(msg):
    print(f"[OK] {msg}")


def warn(msg):
    print(f"[提示] {msg}")


def error(msg):
    print(f"[错误] {msg}")


def section(msg):
    print(f"\n{'=' * 56}\n  {msg}\n{'=' * 56}")


# ── 1. 环境自检 ──────────────────────────────────────────────
def check_runtime():
    """检查 UCRT 运行库（干净 Server 2012 上 Python 启动的硬依赖）"""
    if os.name != "nt":
        return
    ucrt = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"), "System32", "ucrtbase.dll"
    )
    if os.path.isfile(ucrt):
        return
    warn("检测到系统缺少 UCRT 运行库（老版本 Windows 常见）")
    redist = os.path.join(BASE_DIR, "runtime", "vc_redist.x64.exe")
    if os.path.isfile(redist):
        print("      正在静默安装随包自带的运行库（约 1 分钟）...")
        try:
            subprocess.run([redist, "/install", "/quiet", "/norestart"], timeout=300)
            if os.path.isfile(ucrt):
                info("运行库安装成功")
                return
        except Exception as e:
            warn(f"自动安装失败: {e}")
    error("请双击运行 runtime\\vc_redist.x64.exe 安装运行库后重试")
    input("按回车键退出...")
    sys.exit(1)


# ── 2. 首次初始化 ────────────────────────────────────────────
def ensure_initialized():
    flag = os.path.join(BASE_DIR, "data", ".initialized")
    if os.path.exists(flag):
        return
    if BACKGROUND:
        # 后台模式无法交互：使用临时密码并强制首次登录修改
        warn("后台模式跳过初始化向导。请尽快登录管理后台修改默认密码 admin/admin123！")
        return
    r = subprocess.call([sys.executable, os.path.join(BASE_DIR, "init_admin.py")])
    if r != 0:
        error("初始化未完成，请重新运行")
        sys.exit(1)


# ── 3. 防火墙放行 ────────────────────────────────────────────
def setup_firewall():
    if os.name != "nt":
        return
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=JobBoard-8000"],
            capture_output=True,
            timeout=15,
        )
        if r.returncode == 0 and b"JobBoard-8000" in r.stdout:
            return  # 规则已存在
        r2 = subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                "name=JobBoard-8000",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={PORT}",
            ],
            capture_output=True,
            timeout=15,
        )
        if r2.returncode == 0:
            info(f"防火墙已放行端口 {PORT}")
        else:
            warn("防火墙规则未能自动添加（需要管理员权限）")
            warn("若其他同学无法访问，请右键「启动系统.bat」→ 以管理员身份运行一次")
    except Exception as e:
        warn(f"防火墙配置跳过: {e}")


# ── 4. 局域网 IP ─────────────────────────────────────────────
def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ── 5. 启动服务 ──────────────────────────────────────────────
def open_browser_later(url, delay=3):
    def _open():
        time.sleep(delay)
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()


def main():
    section("就业服务平台 · 校园版")

    check_runtime()
    ensure_initialized()
    setup_firewall()

    lan_ip = get_lan_ip()
    os.environ["PUBLIC_BASE_URL"] = f"http://{lan_ip}:{PORT}"

    print()
    info("服务启动中，请稍候…")
    print()
    print("  ┌──────────────────────────────────────────────┐")
    print(f"  │  学生入口：http://{lan_ip}:{PORT}/".ljust(50) + "│")
    print(f"  │  管理后台：http://{lan_ip}:{PORT}/admin.html".ljust(50) + "│")
    print("  └──────────────────────────────────────────────┘")
    print()
    print("  把上面的「学生入口」地址发给同学即可。")
    print("  停止服务：直接关闭本窗口，或运行「停止服务.bat」。")
    print()

    if not BACKGROUND:
        open_browser_later(f"http://127.0.0.1:{PORT}/")

    import uvicorn
    from match_api import app

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
