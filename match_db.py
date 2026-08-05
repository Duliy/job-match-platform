#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_db.py — 数据库操作封装

提供:
  - get_db()           获取数据库连接
  - query_jobs()       社招岗位查询 (分页+筛选)
  - query_gk_jobs()    公考岗位查询 (分页+筛选)
  - get_stats()        数据库统计信息
  - pre_filter()       匹配预筛选 (关键词+城市+薪资+学历)
  - get_hot_jobs()     获取热门岗位列表
  - record_hot_click() 记录热门岗位点击
  - get_api_cost()     获取API成本统计
  - get_profit()       获取利润统计
  - get_recharge_records() 获取充值记录
"""

import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "jobs.db")

# 延迟导入，避免循环依赖
_format_salary = None

def _get_format_salary():
    global _format_salary
    if _format_salary is None:
        from match_utils import format_salary_display
        _format_salary = format_salary_display
    return _format_salary


def add_salary_field(jobs):
    """为 job dict 列表添加 salary 显示字段"""
    fmt = _get_format_salary()
    if isinstance(jobs, list):
        for job in jobs:
            if isinstance(job, dict) and 'salary' not in job:
                job['salary'] = fmt(
                    job.get('salary_min', 0),
                    job.get('salary_max', 0),
                    job.get('salary_type', 'monthly')
                )
    return jobs


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def query_jobs(keyword: str = "", city: str = "", salary_min: float = 0,
               salary_max: float = 999999, page: int = 1, page_size: int = 20):
    """查询社招岗位 (分页+筛选)

    Returns:
        (rows: list[dict], total: int)
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if keyword:
        conditions.append("(title LIKE ? OR company LIKE ? OR keywords LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])

    if city:
        conditions.append("city LIKE ?")
        params.append(f"%{city}%")

    if salary_min > 0:
        conditions.append("(salary_type='negotiable' OR salary_max >= ?)")
        params.append(salary_min)

    if salary_max < 999999:
        conditions.append("(salary_type='negotiable' OR salary_min <= ?)")
        params.append(salary_max)

    where = " AND ".join(conditions)

    # 查询总数
    cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params)
    total = cursor.fetchone()[0]

    # 分页查询
    offset = (page - 1) * page_size
    cursor.execute(f"""
        SELECT * FROM jobs WHERE {where}
        ORDER BY pub_date DESC, salary_max DESC
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    add_salary_field(rows)
    return rows, total


def query_gk_jobs(keyword: str = "", province: str = "",
                  page: int = 1, page_size: int = 20):
    """查询公考岗位 (分页+筛选)

    Returns:
        (rows: list[dict], total: int)
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if keyword:
        conditions.append("(title LIKE ? OR description LIKE ? OR major_req LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])

    if province:
        conditions.append("province LIKE ?")
        params.append(f"%{province}%")

    where = " AND ".join(conditions)

    cursor.execute(f"SELECT COUNT(*) FROM gk_jobs WHERE {where}", params)
    total = cursor.fetchone()[0]

    offset = (page - 1) * page_size
    cursor.execute(f"""
        SELECT * FROM gk_jobs WHERE {where}
        ORDER BY collect_time DESC
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows, total


def pre_filter(skills: list = None, cities: list = None,
               salary_min: float = 0, salary_max: float = 999999,
               education: str = "", job_type: str = "社招",
               max_candidates: int = 100) -> list:
    """匹配预筛选：从数据库中筛选候选岗位

    策略:
    1. 关键词匹配（用技能词做 LIKE 查询）
    2. 城市过滤
    3. 薪资范围过滤
    4. 学历过滤
    5. 取 Top N

    Returns:
        list[dict] 候选岗位
    """
    conn = get_db()
    cursor = conn.cursor()

    if job_type == "公考":
        table = "gk_jobs"
    else:
        table = "jobs"

    conditions = ["1=1"]
    params = []

    # 关键词搜索 - 用技能词构建查询
    # 注意: jobs 表用 keywords, gk_jobs 表用 search_keyword
    keyword_col = "keywords" if table == "jobs" else "search_keyword"
    if skills:
        # 构建 OR 条件：任何技能词匹配 title/keyword_col/search_text
        skill_clauses = []
        for skill in skills[:15]:  # 最多15个技能词
            skill_clauses.append(f"(title LIKE ? OR {keyword_col} LIKE ? OR search_text LIKE ?)")
            params.extend([f"%{skill}%", f"%{skill}%", f"%{skill}%"])
        if skill_clauses:
            conditions.append(f"({' OR '.join(skill_clauses)})")

    # 城市过滤
    if cities:
        if table == "jobs":
            city_clause = " OR ".join(["city LIKE ?" for _ in cities])
            conditions.append(f"({city_clause})")
            for c in cities:
                params.append(f"%{c}%")
        else:
            prov_clause = " OR ".join(["province LIKE ?" for _ in cities])
            conditions.append(f"({prov_clause})")
            for c in cities:
                params.append(f"%{c}%")

    # 薪资范围 (仅社招)
    if table == "jobs" and salary_min > 0:
        conditions.append("(salary_type='negotiable' OR salary_max >= ?)")
        params.append(salary_min)

    if table == "jobs" and salary_max < 999999:
        conditions.append("(salary_type='negotiable' OR salary_min <= ?)")
        params.append(salary_max)

    # 学历过滤 (宽松匹配)
    if education and table == "jobs":
        # 不做严格过滤，只做加分，避免漏掉没写学历要求的岗位
        pass

    where = " AND ".join(conditions)

    # 不同表用不同排序方式：公考无薪资列，按采集时间降序
    if table == "jobs":
        order_clause = "ORDER BY CASE WHEN salary_type != 'negotiable' THEN salary_max ELSE 0 END DESC"
    else:
        order_clause = "ORDER BY collect_time DESC"

    sql = f"""
        SELECT * FROM {table}
        WHERE {where}
        {order_clause}
        LIMIT ?
    """
    params.append(max_candidates)

    cursor.execute(sql, params)
    columns = [desc[0] for desc in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    add_salary_field(results)
    return results


def get_stats():
    """获取数据库统计信息"""
    conn = get_db()
    cursor = conn.cursor()

    # 社招统计
    cursor.execute("SELECT COUNT(*) FROM jobs")
    jobs_total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT city) FROM jobs WHERE city != ''")
    jobs_cities = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT platform) FROM jobs")
    jobs_platforms = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM jobs WHERE salary_type != 'negotiable'")
    jobs_with_salary = cursor.fetchone()[0]

    # 公考统计
    cursor.execute("SELECT COUNT(*) FROM gk_jobs")
    gk_total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT province) FROM gk_jobs WHERE province != ''")
    gk_provinces = cursor.fetchone()[0]

    # 最近更新
    cursor.execute("SELECT MAX(updated_at) FROM jobs")
    jobs_updated = cursor.fetchone()[0] or ""

    cursor.execute("SELECT MAX(updated_at) FROM gk_jobs")
    gk_updated = cursor.fetchone()[0] or ""

    # 薪资分布 (社招)
    cursor.execute("""
        SELECT
            CASE
                WHEN salary_max < 5000 THEN '5K以下'
                WHEN salary_max < 10000 THEN '5-10K'
                WHEN salary_max < 15000 THEN '10-15K'
                WHEN salary_max < 20000 THEN '15-20K'
                WHEN salary_max < 30000 THEN '20-30K'
                ELSE '30K以上'
            END AS salary_range,
            COUNT(*) AS cnt
        FROM jobs
        WHERE salary_type != 'negotiable' AND salary_max > 0
        GROUP BY salary_range
        ORDER BY MIN(salary_max)
    """)
    salary_dist = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return {
        "jobs": {
            "total": jobs_total,
            "cities": jobs_cities,
            "platforms": jobs_platforms,
            "with_salary": jobs_with_salary,
        },
        "gk_jobs": {
            "total": gk_total,
            "provinces": gk_provinces,
        },
        "salary_distribution": salary_dist,
        "last_updated": max(jobs_updated, gk_updated),
    }


# ══════════════════════════════════════════════════════
# 热力图 / 热门岗位
# ══════════════════════════════════════════════════════

def get_hot_jobs(limit: int = 20) -> list:
    """获取热门岗位列表（按权重+点击排序）

    Returns:
        list[dict] 含岗位详情 + hot_jobs 字段
    """
    conn = get_db()
    cursor = conn.cursor()

    # 先查 hot_jobs 表
    cursor.execute('''
        SELECT hj.*, j.title, j.company, j.salary_raw, j.salary_min, j.salary_max,
               j.city, j.education, j.platform, j.link, j.keywords
        FROM hot_jobs hj
        LEFT JOIN jobs j ON hj.job_id = j.id AND hj.job_type = '社招'
        WHERE hj.job_type = '社招'
        ORDER BY hj.is_pinned DESC, hj.weight DESC, hj.click_count DESC
        LIMIT ?
    ''', (limit,))
    social_hot = [dict(row) for row in cursor.fetchall()]
    add_salary_field(social_hot)

    # 公考热门
    cursor.execute('''
        SELECT hj.*, g.title, g.company, g.department, g.education,
               g.major_req, g.political, g.province, g.headcount
        FROM hot_jobs hj
        LEFT JOIN gk_jobs g ON hj.job_id = g.id AND hj.job_type = '公考'
        WHERE hj.job_type = '公考'
        ORDER BY hj.is_pinned DESC, hj.weight DESC, hj.click_count DESC
        LIMIT ?
    ''', (limit,))
    gk_hot = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return {"social": social_hot, "gk": gk_hot}


def record_hot_click(job_id: int, job_type: str = "社招"):
    """记录热门岗位点击"""
    conn = get_db()
    cursor = conn.cursor()

    # 如果已在 hot_jobs 表中，增加点击
    cursor.execute('''
        UPDATE hot_jobs SET click_count = click_count + 1, updated_at = datetime('now')
        WHERE job_id = ? AND job_type = ?
    ''', (job_id, job_type))

    if cursor.rowcount == 0:
        # 不在 hot_jobs 表中，自动添加
        cursor.execute('''
            INSERT INTO hot_jobs (job_id, job_type, weight, click_count)
            VALUES (?, ?, 100, 1)
        ''', (job_id, job_type))

    conn.commit()
    conn.close()


def auto_generate_hot_jobs(top_n: int = 20):
    """自动生成热门岗位（基于用户点击统计）

    将 user_actions 中点击最多的岗位自动添加到 hot_jobs
    """
    conn = get_db()
    cursor = conn.cursor()

    # 统计最近30天的点击
    cursor.execute('''
        SELECT detail, COUNT(*) as cnt
        FROM user_actions
        WHERE action = 'click_job'
          AND created_at >= datetime('now', '-30 days')
          AND detail IS NOT NULL
        GROUP BY detail
        ORDER BY cnt DESC
        LIMIT ?
    ''', (top_n * 2,))

    for row in cursor.fetchall():
        try:
            import json
            detail = json.loads(row["detail"]) if row["detail"] else {}
            job_id = detail.get("job_id")
            job_type = detail.get("job_type", "社招")
            if job_id:
                # 只添加不在表中的
                cursor.execute('''
                    INSERT OR IGNORE INTO hot_jobs (job_id, job_type, weight, click_count)
                    VALUES (?, ?, ?, ?)
                ''', (job_id, job_type, 100, row["cnt"]))
        except (json.JSONDecodeError, TypeError):
            continue

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════
# 财务统计
# ══════════════════════════════════════════════════════

def get_api_cost(start_date: str = None, end_date: str = None) -> dict:
    """获取API调用成本统计

    Args:
        start_date: 开始日期 (YYYY-MM-DD)，默认当月1号
        end_date: 结束日期 (YYYY-MM-DD)，默认今天

    Returns:
        {
            "total_calls": int,
            "total_cost_yuan": float,
            "total_credits_charged": int,
            "by_type": [{"api_type": str, "calls": int, "cost_yuan": float, "credits": int}],
            "daily": [{"date": str, "calls": int, "cost_yuan": float}]
        }
    """
    conn = get_db()
    cursor = conn.cursor()

    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-01")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # 总计
    cursor.execute('''
        SELECT COUNT(*) as total_calls,
               COALESCE(SUM(cost_yuan), 0) as total_cost,
               COALESCE(SUM(credits_charged), 0) as total_credits
        FROM api_call_logs
        WHERE created_at >= ? AND created_at < ? || ' 23:59:59'
    ''', (start_date, end_date))
    summary = dict(cursor.fetchone())

    # 按类型
    cursor.execute('''
        SELECT api_type, COUNT(*) as calls,
               COALESCE(SUM(cost_yuan), 0) as cost_yuan,
               COALESCE(SUM(credits_charged), 0) as credits
        FROM api_call_logs
        WHERE created_at >= ? AND created_at < ? || ' 23:59:59'
        GROUP BY api_type
        ORDER BY calls DESC
    ''', (start_date, end_date))
    by_type = [dict(row) for row in cursor.fetchall()]

    # 按日
    cursor.execute('''
        SELECT DATE(created_at) as date, COUNT(*) as calls,
               COALESCE(SUM(cost_yuan), 0) as cost_yuan
        FROM api_call_logs
        WHERE created_at >= ? AND created_at < ? || ' 23:59:59'
        GROUP BY DATE(created_at)
        ORDER BY date
    ''', (start_date, end_date))
    daily = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return {
        "total_calls": summary.get("total_calls", 0),
        "total_cost_yuan": round(summary.get("total_cost", 0), 4),
        "total_credits_charged": summary.get("total_credits", 0),
        "by_type": by_type,
        "daily": daily,
    }


def get_profit(start_date: str = None, end_date: str = None) -> dict:
    """获取利润统计（充值收入 - API成本）

    Args:
        start_date: 开始日期，默认当月1号
        end_date: 结束日期，默认今天

    Returns:
        {
            "revenue_yuan": float,
            "cost_yuan": float,
            "profit_yuan": float,
            "recharge_count": int,
            "api_call_count": int
        }
    """
    conn = get_db()
    cursor = conn.cursor()

    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-01")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # 充值收入
    cursor.execute('''
        SELECT COALESCE(SUM(price_yuan), 0) as revenue,
               COUNT(*) as count
        FROM recharge_records
        WHERE created_at >= ? AND created_at < ? || ' 23:59:59'
    ''', (start_date, end_date))
    recharge = dict(cursor.fetchone())

    # API 成本
    cursor.execute('''
        SELECT COALESCE(SUM(cost_yuan), 0) as cost,
               COUNT(*) as count
        FROM api_call_logs
        WHERE created_at >= ? AND created_at < ? || ' 23:59:59'
    ''', (start_date, end_date))
    api_cost = dict(cursor.fetchone())

    conn.close()

    revenue = recharge.get("revenue", 0)
    cost = api_cost.get("cost", 0)

    return {
        "revenue_yuan": round(revenue, 2),
        "cost_yuan": round(cost, 4),
        "profit_yuan": round(revenue - cost, 2),
        "recharge_count": recharge.get("count", 0),
        "api_call_count": api_cost.get("count", 0),
    }


def get_recharge_records(start_date: str = None, end_date: str = None,
                         page: int = 1, page_size: int = 20) -> tuple:
    """获取充值记录

    Returns:
        (rows: list[dict], total: int)
    """
    conn = get_db()
    cursor = conn.cursor()

    if not start_date:
        start_date = "2000-01-01"
    if not end_date:
        end_date = "2099-12-31"

    cursor.execute('''
        SELECT COUNT(*) FROM recharge_records
        WHERE created_at >= ? AND created_at < ? || ' 23:59:59'
    ''', (start_date, end_date))
    total = cursor.fetchone()[0]

    offset = (page - 1) * page_size
    cursor.execute('''
        SELECT r.*, u.username
        FROM recharge_records r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.created_at >= ? AND r.created_at < ? || ' 23:59:59'
        ORDER BY r.created_at DESC
        LIMIT ? OFFSET ?
    ''', (start_date, end_date, page_size, offset))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows, total


def get_users_list(page: int = 1, page_size: int = 20, keyword: str = "") -> tuple:
    """获取用户列表

    Returns:
        (rows: list[dict], total: int)
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if keyword:
        conditions.append("username LIKE ?")
        params.append(f"%{keyword}%")

    where = " AND ".join(conditions)

    cursor.execute(f"SELECT COUNT(*) FROM users WHERE {where}", params)
    total = cursor.fetchone()[0]

    offset = (page - 1) * page_size
    cursor.execute(f'''
        SELECT id, username, credits, role, is_disabled, created_at
        FROM users WHERE {where}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', params + [page_size, offset])

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows, total


def get_cdk_list(page: int = 1, page_size: int = 20, used_filter: str = "") -> tuple:
    """获取CDK列表

    Args:
        used_filter: "used" / "unused" / ""

    Returns:
        (rows: list[dict], total: int)
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if used_filter == "used":
        conditions.append("used_by IS NOT NULL")
    elif used_filter == "unused":
        conditions.append("used_by IS NULL")

    where = " AND ".join(conditions)

    cursor.execute(f"SELECT COUNT(*) FROM cdk_codes WHERE {where}", params)
    total = cursor.fetchone()[0]

    offset = (page - 1) * page_size
    cursor.execute(f'''
        SELECT c.*, u.username as used_by_name
        FROM cdk_codes c
        LEFT JOIN users u ON c.used_by = u.id
        WHERE {where}
        ORDER BY c.created_at DESC
        LIMIT ? OFFSET ?
    ''', params + [page_size, offset])

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows, total


def get_db_tables() -> list:
    """获取数据库所有表名"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
    conn.close()
    return tables


def get_table_data(table_name: str, page: int = 1, page_size: int = 50) -> tuple:
    """获取指定表的数据（分页）

    Returns:
        (columns: list, rows: list[list], total: int)
    """
    # 安全校验：只允许查询已知表
    allowed = get_db_tables()
    if table_name not in allowed:
        return [], [], 0

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    total = cursor.fetchone()[0]

    offset = (page - 1) * page_size
    cursor.execute(f"SELECT * FROM [{table_name}] LIMIT ? OFFSET ?", (page_size, offset))
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    conn.close()
    return columns, [list(row) for row in rows], total


def exec_readonly_sql(sql: str) -> tuple:
    """执行只读SQL查询

    Returns:
        (columns: list, rows: list[list])
    """
    # 安全：只允许 SELECT 语句
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT"):
        raise ValueError("只允许 SELECT 查询")
    # 禁止危险关键字
    for kw in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "ATTACH", "DETACH"]:
        if kw in sql_stripped.split():
            raise ValueError(f"禁止使用 {kw} 语句")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = [list(row) for row in cursor.fetchall()]
    conn.close()
    return columns, rows
