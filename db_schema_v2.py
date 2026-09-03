#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_schema_v2.py — 数据库升级脚本 V2
在 jobs.db 中新增用户、CDK、充值、API日志、热力图、行为日志等6张表

用法:
    python db_schema_v2.py          # 升级数据库
    python db_schema_v2.py --check  # 仅检查表是否存在
"""

import sqlite3
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "jobs.db")


SCHEMA_V2_SQL = """
-- ======================================================
-- 用户表 (users)
-- ======================================================
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    credits         INTEGER DEFAULT 0,
    role            TEXT DEFAULT 'user',
    is_disabled     INTEGER DEFAULT 0,
    is_vip          INTEGER DEFAULT 0,
    vip_expired_at  TEXT DEFAULT NULL,
    notify_email    TEXT DEFAULT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- ======================================================
-- CDK 充值码表 (cdk_codes)
-- ======================================================
CREATE TABLE IF NOT EXISTS cdk_codes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT UNIQUE NOT NULL,
    credits         INTEGER NOT NULL,
    price_yuan      REAL NOT NULL,
    used_by         INTEGER DEFAULT NULL,
    used_at         TEXT DEFAULT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (used_by) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_cdk_code ON cdk_codes(code);
CREATE INDEX IF NOT EXISTS idx_cdk_used_by ON cdk_codes(used_by);

-- ======================================================
-- 充值记录 (recharge_records)
-- ======================================================
CREATE TABLE IF NOT EXISTS recharge_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    cdk_code        TEXT NOT NULL,
    credits         INTEGER NOT NULL,
    price_yuan      REAL NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_recharge_user ON recharge_records(user_id);
CREATE INDEX IF NOT EXISTS idx_recharge_time ON recharge_records(created_at);

-- ======================================================
-- API 调用日志 (api_call_logs)
-- ======================================================
CREATE TABLE IF NOT EXISTS api_call_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    api_type        TEXT NOT NULL,
    model           TEXT DEFAULT 'deepseek-chat',
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_yuan       REAL DEFAULT 0,
    credits_charged INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_api_log_user ON api_call_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_api_log_type ON api_call_logs(api_type);
CREATE INDEX IF NOT EXISTS idx_api_log_time ON api_call_logs(created_at);

-- ======================================================
-- 热力图/热门岗位配置 (hot_jobs)
-- ======================================================
CREATE TABLE IF NOT EXISTS hot_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL,
    job_type        TEXT DEFAULT '社招',
    weight          INTEGER DEFAULT 100,
    is_pinned       INTEGER DEFAULT 0,
    click_count     INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_hot_job ON hot_jobs(job_id, job_type);
CREATE INDEX IF NOT EXISTS idx_hot_weight ON hot_jobs(weight DESC);

-- ======================================================
-- 用户行为日志 (user_actions)
-- ======================================================
CREATE TABLE IF NOT EXISTS user_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    action          TEXT NOT NULL,
    detail          TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_action_user ON user_actions(user_id);
CREATE INDEX IF NOT EXISTS idx_action_type ON user_actions(action);
CREATE INDEX IF NOT EXISTS idx_action_time ON user_actions(created_at);

-- ======================================================
-- VIP 订阅订单 (vip_orders)
-- ======================================================
CREATE TABLE IF NOT EXISTS vip_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    credits_used    INTEGER NOT NULL DEFAULT 300,
    started_at      TEXT NOT NULL,
    expired_at      TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_vip_order_user ON vip_orders(user_id);

-- ======================================================
-- 会员简历存储 (member_resumes)
-- ======================================================
CREATE TABLE IF NOT EXISTS member_resumes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    resume_filename TEXT DEFAULT '',
    resume_text     TEXT DEFAULT '',
    parsed_json     TEXT DEFAULT '{}',
    analysis_json   TEXT DEFAULT '{}',
    uploaded_at     TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_member_resume_user ON member_resumes(user_id);

-- ======================================================
-- VIP 自动匹配结果 (vip_match_results)
-- ======================================================
CREATE TABLE IF NOT EXISTS vip_match_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    resume_id       INTEGER DEFAULT 0,
    match_json      TEXT DEFAULT '[]',
    high_prob_count INTEGER DEFAULT 0,
    notified        INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_vip_match_user ON vip_match_results(user_id);
CREATE INDEX IF NOT EXISTS idx_vip_match_time ON vip_match_results(created_at);

-- ======================================================
-- 邮件配置 (email_config) — 单行配置表
-- ======================================================
CREATE TABLE IF NOT EXISTS email_config (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    smtp_host       TEXT DEFAULT '',
    smtp_port       INTEGER DEFAULT 465,
    smtp_user       TEXT DEFAULT '',
    smtp_pass       TEXT DEFAULT '',
    from_email      TEXT DEFAULT '',
    enabled         INTEGER DEFAULT 0
);
INSERT OR IGNORE INTO email_config (id) VALUES (1);
"""


def upgrade_schema(db_path: str = DB_PATH):
    """升级数据库 schema，新增 V2 表 + VIP 迁移"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查已有表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = {row[0] for row in cursor.fetchall()}

    # V2 新增的表
    new_tables = [
        "users",
        "cdk_codes",
        "recharge_records",
        "api_call_logs",
        "hot_jobs",
        "user_actions",
        "vip_orders",
        "member_resumes",
        "vip_match_results",
        "email_config",
    ]
    vip_tables = ["vip_orders", "member_resumes", "vip_match_results", "email_config"]

    # 执行建表
    conn.executescript(SCHEMA_V2_SQL)
    conn.commit()

    # 对已有 users 表补充 is_vip / vip_expired_at 列
    if "users" in existing:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_vip INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # 列已存在
        try:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN vip_expired_at TEXT DEFAULT NULL"
            )
        except sqlite3.OperationalError:
            pass  # 列已存在
        try:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN notify_email TEXT DEFAULT NULL"
            )
        except sqlite3.OperationalError:
            pass  # 列已存在
        conn.commit()

    # 创建默认管理员（如果 users 表刚创建）
    if "users" not in existing:
        import bcrypt as _bcrypt

        password_hash = _bcrypt.hashpw(
            "admin123".encode("utf-8"), _bcrypt.gensalt()
        ).decode("utf-8")
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, credits, role)
            VALUES (?, ?, ?, ?)
        """,
            ("admin", password_hash, 9999, "admin"),
        )
        conn.commit()
        print("  已创建默认管理员: admin / admin123")

    # 验证
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    all_tables = {row[0] for row in cursor.fetchall()}

    print(f"\n{'=' * 50}")
    print(f"数据库升级报告")
    print(f"{'=' * 50}")

    for table in new_tables:
        status = "[OK] 已存在" if table in existing else "[NEW] 新建"
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
        except Exception:
            count = 0
        print(f"  {table:25s} {status} ({count} 条记录)")

    # 检查所有表
    print(f"\n  全部数据表 ({len(all_tables)}):")
    for t in sorted(all_tables):
        cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
        c = cursor.fetchone()[0]
        print(f"    {t:25s} {c} 条")

    conn.close()
    print(f"\n[OK] 数据库升级完成!")


def check_schema(db_path: str = DB_PATH):
    """仅检查表状态"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    new_tables = [
        "users",
        "cdk_codes",
        "recharge_records",
        "api_call_logs",
        "hot_jobs",
        "user_actions",
        "vip_orders",
        "member_resumes",
        "vip_match_results",
        "email_config",
    ]

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = {row[0] for row in cursor.fetchall()}

    print("V2 表状态:")
    for table in new_tables:
        status = "[OK] 存在" if table in existing else "[X] 不存在"
        print(f"  {table:25s} {status}")

    conn.close()


if __name__ == "__main__":
    if "--check" in sys.argv:
        check_schema()
    else:
        upgrade_schema()
