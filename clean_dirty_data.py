#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_dirty_data.py — 存量数据清洗（一次性）
用 match_utils 的 normalize_city / normalize_education 清洗 jobs 表的脏数据：
  - city: '已上市' 等公司标签 → ''；'北京市' → '北京'
  - education: '可转正'/'4天/周' 等非学历值 → ''

用法: python3 clean_dirty_data.py [db_path]
默认清洗 ./data/jobs.db
"""

import os
import sqlite3
import sys

from match_utils import normalize_city, normalize_education

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "jobs.db"
)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, city, education FROM jobs")
    rows = cursor.fetchall()  # 先取完再写，避免迭代中执行新语句

    city_fixed = edu_fixed = 0
    for row in rows:
        new_city = normalize_city(row["city"] or "")
        new_edu = normalize_education(row["education"] or "")
        if new_city != (row["city"] or "") or new_edu != (row["education"] or ""):
            cursor.execute(
                "UPDATE jobs SET city=?, education=? WHERE id=?",
                (new_city, new_edu, row["id"]),
            )
            if new_city != (row["city"] or ""):
                city_fixed += 1
            if new_edu != (row["education"] or ""):
                edu_fixed += 1

    conn.commit()

    cursor.execute("SELECT DISTINCT city FROM jobs WHERE city != '' ORDER BY city")
    cities = [r[0] for r in cursor.fetchall()]
    cursor.execute("SELECT DISTINCT education FROM jobs WHERE education != '' ORDER BY education")
    edus = [r[0] for r in cursor.fetchall()]
    conn.close()

    print(f"✓ city 修正 {city_fixed} 条, education 修正 {edu_fixed} 条")
    print(f"  现存城市({len(cities)}): {cities}")
    print(f"  现存学历值: {edus}")


if __name__ == "__main__":
    main()
