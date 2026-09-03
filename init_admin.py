#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_admin.py — 首次运行初始化向导

首次启动时强制设置管理员密码（废弃默认 admin123），
写入 data/.initialized 标记。非首次运行直接退出。
"""

import getpass
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
INIT_FLAG = os.path.join(DATA_DIR, ".initialized")
DB_PATH = os.path.join(DATA_DIR, "jobs.db")


def main():
    if os.path.exists(INIT_FLAG):
        return  # 已初始化

    print()
    print("=" * 56)
    print("  首次运行初始化 —— 设置管理员密码")
    print("=" * 56)
    print()
    print("  管理后台用于配置采集、查看数据、管理用户。")
    print("  请为管理员账号 admin 设置一个密码（至少 6 位）。")
    print("  【重要】请妥善保管，并告诉需要使用后台的老师。")
    print()

    while True:
        try:
            pwd = getpass.getpass("  请输入管理员密码（输入时不显示）: ")
        except (EOFError, KeyboardInterrupt):
            print("\n  已取消。下次启动时会再次询问。")
            sys.exit(1)
        if len(pwd) < 6:
            print("  密码太短，至少 6 位，请重新输入。")
            continue
        try:
            pwd2 = getpass.getpass("  请再次输入确认: ")
        except (EOFError, KeyboardInterrupt):
            print("\n  已取消。下次启动时会再次询问。")
            sys.exit(1)
        if pwd != pwd2:
            print("  两次输入不一致，请重新输入。")
            continue
        break

    # 初始化数据库并设置密码
    import sqlite3
    from import_data import create_tables
    from db_schema_v2 import upgrade_schema
    from auth import hash_password

    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    conn.close()
    upgrade_schema()

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = 'admin'",
        (hash_password(pwd),),
    )
    conn.commit()
    conn.close()

    with open(INIT_FLAG, "w", encoding="utf-8") as f:
        f.write("initialized\n")

    print()
    print("  ✅ 管理员密码设置成功！")
    print("     后台地址: http://服务器地址/admin.html  账号: admin")
    print()


if __name__ == "__main__":
    main()
