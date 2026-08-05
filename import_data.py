#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_data.py — 一次性数据导入脚本
将 jobs_latest.json 和 gk_jobs_latest.json 导入 SQLite

用法:
    python import_data.py          # 全量导入（如数据库不存在则新建）
    python import_data.py --reset  # 清空重建
"""

import json
import sqlite3
import os
import sys

from match_utils import parse_salary, extract_city

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "jobs.db")
JOBS_JSON = os.path.join(BASE_DIR, "data", "jobs_latest.json")
GK_JSON = os.path.join(BASE_DIR, "data", "gk_jobs_latest.json")


# ══════════════════════════════════════════════════════
# 建表 SQL
# ══════════════════════════════════════════════════════

SCHEMA_SQL = """
-- ======================================================
-- 社招岗位表 (jobs)
-- ======================================================
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    salary_raw      TEXT,
    salary_min      REAL,
    salary_max      REAL,
    salary_type     TEXT DEFAULT 'monthly',
    location        TEXT,
    city            TEXT,
    education       TEXT,
    platform        TEXT,
    pub_date        TEXT,
    link            TEXT,
    keywords        TEXT,
    first_seen      TEXT,
    job_type        TEXT DEFAULT '社招',
    search_text     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ======================================================
-- 公考岗位表 (gk_jobs)
-- ======================================================
CREATE TABLE IF NOT EXISTS gk_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    region          TEXT,
    company         TEXT,
    department      TEXT,
    org_type        TEXT,
    position_id     TEXT,
    title           TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    headcount       INTEGER DEFAULT 1,
    education       TEXT,
    major_req       TEXT,
    political       TEXT,
    province        TEXT,
    source          TEXT,
    exam_year       TEXT,
    search_keyword  TEXT,
    collect_time    TEXT,
    job_type        TEXT DEFAULT '公考',
    search_text     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ======================================================
-- 匹配缓存表 (match_cache)
-- ======================================================
CREATE TABLE IF NOT EXISTS match_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_hash     TEXT NOT NULL,
    preference_hash TEXT NOT NULL,
    job_type        TEXT,
    result_json     TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cache_lookup
    ON match_cache(resume_hash, preference_hash, job_type);

-- ======================================================
-- 索引
-- ======================================================
CREATE INDEX IF NOT EXISTS idx_jobs_city       ON jobs(city);
CREATE INDEX IF NOT EXISTS idx_jobs_salary     ON jobs(salary_min, salary_max);
CREATE INDEX IF NOT EXISTS idx_jobs_education  ON jobs(education);
CREATE INDEX IF NOT EXISTS idx_jobs_platform   ON jobs(platform);
CREATE INDEX IF NOT EXISTS idx_jobs_pub_date   ON jobs(pub_date);

CREATE INDEX IF NOT EXISTS idx_gk_province     ON gk_jobs(province);
CREATE INDEX IF NOT EXISTS idx_gk_education    ON gk_jobs(education);
CREATE INDEX IF NOT EXISTS idx_gk_category     ON gk_jobs(category);
CREATE INDEX IF NOT EXISTS idx_gk_political    ON gk_jobs(political);

-- ======================================================
-- FTS5 全文搜索
-- ======================================================
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    title, company, keywords, search_text,
    content='jobs', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS gk_jobs_fts USING fts5(
    title, description, major_req, search_text,
    content='gk_jobs', content_rowid='id'
);

-- ======================================================
-- FTS5 同步触发器
-- ======================================================
CREATE TRIGGER IF NOT EXISTS jobs_ai AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, title, company, keywords, search_text)
    VALUES (new.id, new.title, new.company, new.keywords, new.search_text);
END;

CREATE TRIGGER IF NOT EXISTS jobs_ad AFTER DELETE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, keywords, search_text)
    VALUES ('delete', old.id, old.title, old.company, old.keywords, old.search_text);
END;

CREATE TRIGGER IF NOT EXISTS jobs_au AFTER UPDATE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, keywords, search_text)
    VALUES ('delete', old.id, old.title, old.company, old.keywords, old.search_text);
    INSERT INTO jobs_fts(rowid, title, company, keywords, search_text)
    VALUES (new.id, new.title, new.company, new.keywords, new.search_text);
END;

CREATE TRIGGER IF NOT EXISTS gk_jobs_ai AFTER INSERT ON gk_jobs BEGIN
    INSERT INTO gk_jobs_fts(rowid, title, description, major_req, search_text)
    VALUES (new.id, new.title, new.description, new.major_req, new.search_text);
END;

CREATE TRIGGER IF NOT EXISTS gk_jobs_ad AFTER DELETE ON gk_jobs BEGIN
    INSERT INTO gk_jobs_fts(gk_jobs_fts, rowid, title, description, major_req, search_text)
    VALUES ('delete', old.id, old.title, old.description, old.major_req, old.search_text);
END;

CREATE TRIGGER IF NOT EXISTS gk_jobs_au AFTER UPDATE ON gk_jobs BEGIN
    INSERT INTO gk_jobs_fts(gk_jobs_fts, rowid, title, description, major_req, search_text)
    VALUES ('delete', old.id, old.title, old.description, old.major_req, old.search_text);
    INSERT INTO gk_jobs_fts(rowid, title, description, major_req, search_text)
    VALUES (new.id, new.title, new.description, new.major_req, new.search_text);
END;
"""


def create_tables(conn):
    """执行建表SQL"""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    print("✓ 数据表创建完成")


def import_jobs(conn):
    """导入社招数据"""
    if not os.path.exists(JOBS_JSON):
        print(f"⚠ 文件不存在: {JOBS_JSON}")
        return 0

    with open(JOBS_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    jobs = data.get('jobs', [])
    cursor = conn.cursor()

    count = 0
    for job in jobs:
        salary_info = parse_salary(job.get('薪资', ''))
        city = extract_city(job.get('工作地点', ''))
        search_text = f"{job.get('职位名称', '')} {job.get('公司名称', '')} {job.get('关键词', '')}"

        try:
            cursor.execute('''
                INSERT INTO jobs (title, company, salary_raw, salary_min, salary_max,
                    salary_type, location, city, education, platform, pub_date,
                    link, keywords, first_seen, search_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.get('职位名称', ''),
                job.get('公司名称', ''),
                job.get('薪资', ''),
                salary_info['salary_min'],
                salary_info['salary_max'],
                salary_info['salary_type'],
                job.get('工作地点', ''),
                city,
                job.get('学历要求', ''),
                job.get('来源平台', ''),
                job.get('发布日期', ''),
                job.get('链接', ''),
                job.get('关键词', ''),
                job.get('first_seen', ''),
                search_text
            ))
            count += 1
        except Exception as e:
            print(f"  跳过 (错误): {job.get('职位名称', '?')} — {e}")

    conn.commit()
    print(f"✓ 导入社招岗位: {count} 条")
    return count


def import_gk_jobs(conn):
    """导入公考数据"""
    if not os.path.exists(GK_JSON):
        print(f"⚠ 文件不存在: {GK_JSON}")
        return 0

    with open(GK_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # gk_jobs_latest.json 可能是列表或 dict
    if isinstance(data, list):
        jobs = data
    elif isinstance(data, dict):
        jobs = data.get('jobs', data.get('gk_jobs', []))
    else:
        jobs = []

    cursor = conn.cursor()
    count = 0

    for job in jobs:
        search_text = f"{job.get('职位名', '')} {job.get('职位简介', '')} {job.get('专业要求', '')}"

        try:
            cursor.execute('''
                INSERT INTO gk_jobs (region, company, department, org_type,
                    position_id, title, description, category, headcount,
                    education, major_req, political, province, source,
                    exam_year, search_keyword, collect_time, search_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.get('地区', ''),
                job.get('公司名', ''),
                job.get('用人部门', ''),
                job.get('机构性质', ''),
                job.get('职位ID', ''),
                job.get('职位名', ''),
                job.get('职位简介', ''),
                job.get('职位类别', ''),
                job.get('招收人数', 1),
                job.get('学历要求', ''),
                job.get('专业要求', ''),
                job.get('政治面貌', ''),
                job.get('省份', ''),
                job.get('来源', ''),
                job.get('考试年份', ''),
                job.get('搜索关键词', ''),
                job.get('采集时间', ''),
                search_text
            ))
            count += 1
        except Exception as e:
            print(f"  跳过 (错误): {job.get('职位名', '?')} — {e}")

    conn.commit()
    print(f"✓ 导入公考岗位: {count} 条")
    return count


def import_jobs_incremental(conn):
    """增量导入社招数据 —— 只插入数据库中不存在的岗位（按 title+company+link 去重）"""
    if not os.path.exists(JOBS_JSON):
        return 0

    # 确保表存在
    create_tables(conn)

    with open(JOBS_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    jobs = data.get('jobs', [])
    cursor = conn.cursor()
    count = 0

    for job in jobs:
        title = job.get('职位名称', '')
        company = job.get('公司名称', '')
        link = job.get('链接', '')

        # 检查是否已存在
        cursor.execute(
            "SELECT id FROM jobs WHERE title=? AND company=? AND link=?",
            (title, company, link)
        )
        if cursor.fetchone():
            continue

        salary_info = parse_salary(job.get('薪资', ''))
        city = extract_city(job.get('工作地点', ''))
        search_text = f"{title} {company} {job.get('关键词', '')}"

        try:
            cursor.execute('''
                INSERT INTO jobs (title, company, salary_raw, salary_min, salary_max,
                    salary_type, location, city, education, platform, pub_date,
                    link, keywords, first_seen, search_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                title,
                company,
                job.get('薪资', ''),
                salary_info['salary_min'],
                salary_info['salary_max'],
                salary_info['salary_type'],
                job.get('工作地点', ''),
                city,
                job.get('学历要求', ''),
                job.get('来源平台', ''),
                job.get('发布日期', ''),
                link,
                job.get('关键词', ''),
                job.get('first_seen', ''),
                search_text
            ))
            count += 1
        except Exception:
            pass

    conn.commit()
    return count


def import_gk_jobs_incremental(conn):
    """增量导入公考数据 —— 只插入数据库中不存在的岗位（按 position_id+title 去重）"""
    if not os.path.exists(GK_JSON):
        return 0

    # 确保表存在
    create_tables(conn)

    with open(GK_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, list):
        jobs = data
    elif isinstance(data, dict):
        jobs = data.get('jobs', data.get('gk_jobs', []))
    else:
        jobs = []

    cursor = conn.cursor()
    count = 0

    for job in jobs:
        title = job.get('职位名', '')
        position_id = job.get('职位ID', '')

        # 按 position_id 去重
        if position_id:
            cursor.execute(
                "SELECT id FROM gk_jobs WHERE position_id=? AND title=?",
                (position_id, title)
            )
            if cursor.fetchone():
                continue
        else:
            # 没有 position_id 的按标题去重（粗糙但可用）
            cursor.execute(
                "SELECT id FROM gk_jobs WHERE title=?",
                (title,)
            )
            if cursor.fetchone():
                continue

        search_text = f"{title} {job.get('职位简介', '')} {job.get('专业要求', '')}"

        try:
            cursor.execute('''
                INSERT INTO gk_jobs (region, company, department, org_type,
                    position_id, title, description, category, headcount,
                    education, major_req, political, province, source,
                    exam_year, search_keyword, collect_time, search_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.get('地区', ''),
                job.get('公司名', ''),
                job.get('用人部门', ''),
                job.get('机构性质', ''),
                position_id,
                title,
                job.get('职位简介', ''),
                job.get('职位类别', ''),
                job.get('招收人数', 1),
                job.get('学历要求', ''),
                job.get('专业要求', ''),
                job.get('政治面貌', ''),
                job.get('省份', ''),
                job.get('来源', ''),
                job.get('考试年份', ''),
                job.get('搜索关键词', ''),
                job.get('采集时间', ''),
                search_text
            ))
            count += 1
        except Exception:
            pass

    conn.commit()
    return count


def verify(conn):
    """验证导入数据"""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM jobs")
    jobs_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM gk_jobs")
    gk_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT city) FROM jobs WHERE city != ''")
    cities = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT platform) FROM jobs")
    platforms = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT province) FROM gk_jobs WHERE province != ''")
    provinces = cursor.fetchone()[0]

    # 薪资统计
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE salary_type != 'negotiable'")
    has_salary = cursor.fetchone()[0]

    cursor.execute("SELECT AVG(salary_max) FROM jobs WHERE salary_type != 'negotiable' AND salary_max > 0")
    avg_max = cursor.fetchone()[0] or 0

    print(f"\n{'='*50}")
    print(f"数据库验证报告")
    print(f"{'='*50}")
    print(f"  社招岗位: {jobs_count} 条")
    print(f"  公考岗位: {gk_count} 条")
    print(f"  覆盖城市: {cities} 个 (社招)")
    print(f"  来源平台: {platforms} 个")
    print(f"  覆盖省份: {provinces} 个 (公考)")
    print(f"  有薪资金额: {has_salary}/{jobs_count} 条")
    print(f"  平均薪资上限: {avg_max:.0f} 元/月")
    print(f"{'='*50}")


if __name__ == '__main__':
    # --reset 参数：删除重建
    if '--reset' in sys.argv:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print("✓ 已删除旧数据库")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # 检查是否已有数据
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs")
        existing = cursor.fetchone()[0]
        if existing > 0 and '--reset' not in sys.argv:
            print(f"数据库已有 {existing} 条社招记录，跳过导入。使用 --reset 重建。")
            verify(conn)
            conn.close()
            sys.exit(0)
    except sqlite3.OperationalError:
        pass  # 表不存在，继续导入

    create_tables(conn)
    import_jobs(conn)
    import_gk_jobs(conn)
    verify(conn)
    conn.close()
    print("\n✓ 数据导入完成!")
