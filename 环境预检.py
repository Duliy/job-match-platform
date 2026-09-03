#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境预检.py — 部署前环境检查工具

在目标服务器上运行（双击 环境预检.bat），输出一份体检报告，
并把报告保存到 预检报告.txt，可截图发给技术支持。
"""

import os
import platform
import socket
import sys
import urllib.request
from datetime import datetime

REPORT_LINES = []


def out(line=""):
    print(line)
    REPORT_LINES.append(line)


def check(name, ok, detail=""):
    mark = "✅" if ok else "❌"
    out(f"  {mark} {name}: {detail}")
    return ok


def url_ok(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    out("=" * 56)
    out("  就业服务平台 · 环境预检报告")
    out(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out("=" * 56)
    out()

    # 1. 操作系统
    out("【系统信息】")
    ver = platform.version()
    release = platform.release()
    out(f"  系统: {platform.system()} {release} (版本号 {ver})")
    check("系统架构", platform.machine().endswith("64"), platform.machine())
    # NT 6.2 = Server 2012 / Win8；NT 6.3 = 2012 R2 / Win8.1
    parts = ver.split(".")
    is_supported = False
    if len(parts) >= 2:
        try:
            major, minor = int(parts[0]), int(parts[1])
            is_supported = (major, minor) >= (6, 2)
        except ValueError:
            pass
    check(
        "系统版本兼容性",
        is_supported,
        f"{'满足要求' if is_supported else '过旧，需要 Windows 8 / Server 2012 或更高'}",
    )
    out()

    # 2. 运行库
    out("【运行环境】")
    windir = os.environ.get("WINDIR", r"C:\Windows")
    ucrt = os.path.isfile(os.path.join(windir, "System32", "ucrtbase.dll"))
    check(
        "UCRT 运行库",
        ucrt,
        "已安装" if ucrt else "缺失（首次启动时会自动安装随包运行库，无需担心）",
    )
    check(
        "内嵌 Python",
        os.path.isfile(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "runtime",
                "python",
                "python.exe",
            )
        ),
        "就绪",
    )
    out()

    # 3. 网络
    out("【网络连通性】")
    check("外网（百度）", url_ok("https://www.baidu.com"), "")
    check("DeepSeek API", url_ok("https://api.deepseek.com"), "")
    check("前程无忧", url_ok("https://www.51job.com"), "")
    check("实习僧", url_ok("https://www.shixiseng.com"), "")
    out()

    # 4. 端口
    out("【端口】")
    check(
        "8000 端口可用",
        port_free(8000),
        "空闲" if port_free(8000) else "被占用（请先关闭占用程序）",
    )
    out()

    # 5. 磁盘
    out("【磁盘】")
    try:
        usage = __import__("shutil").disk_usage(
            os.path.dirname(os.path.abspath(__file__))
        )
        free_gb = usage.free / 1024**3
        check("剩余空间", free_gb > 2, f"{free_gb:.1f} GB")
    except Exception:
        out("  （无法检测磁盘空间）")
    out()

    out("=" * 56)
    out("  预检完成。如有 ❌ 项，请将本文件截图发给技术支持。")
    out("=" * 56)

    try:
        with open("预检报告.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(REPORT_LINES))
        print("\n报告已保存到: 预检报告.txt")
    except Exception:
        pass


if __name__ == "__main__":
    main()
    if os.name == "nt":
        input("\n按回车键退出...")
