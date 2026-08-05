#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
admin_api.py — 管理后台 API 路由

包含:
  - 用户管理
  - CDK 管理
  - 热力图管理
  - 数据库管理
  - 财务统计
  - 爬虫管理
"""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Optional

# 数据导入（爬虫完成后自动同步到数据库）
from import_data import import_jobs_incremental, import_gk_jobs_incremental

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import get_admin_user, generate_cdk, hash_password
from match_db import (
    get_db, get_users_list, get_cdk_list,
    get_api_cost, get_profit, get_recharge_records,
    get_hot_jobs, get_db_tables, get_table_data, exec_readonly_sql,
    get_stats,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ── 爬虫调度状态（内存中）──────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "schedule_config.json")
GK_CONFIG_FILE = os.path.join(BASE_DIR, "data", "gk_schedule_config.json")

scheduler_running = False
is_crawling = False
crawl_start_time = None  # 用于检测卡住的采集
last_crawl_time = None
last_crawl_count = 0

gk_is_crawling = False
gk_last_crawl_time = None
gk_last_crawl_count = 0
gk_crawl_start_time = None


# ══════════════════════════════════════════════════════
# Pydantic 模型
# ══════════════════════════════════════════════════════

class CdkGenerateRequest(BaseModel):
    credits: int
    price_yuan: float
    count: int = 1


class UserUpdateRequest(BaseModel):
    credits: Optional[int] = None
    role: Optional[str] = None
    is_disabled: Optional[int] = None
    password: Optional[str] = None


class HotJobUpdateRequest(BaseModel):
    weight: Optional[int] = None
    is_pinned: Optional[int] = None


class HotJobAddRequest(BaseModel):
    job_id: int
    job_type: str = "社招"
    is_pinned: int = 0
    weight: int = 0


class SqlQueryRequest(BaseModel):
    sql: str


class CrawlScheduleRequest(BaseModel):
    enabled: bool = False
    interval_hours: int = 12
    keywords: list = []


class GkCrawlScheduleRequest(BaseModel):
    enabled: bool = False
    interval_hours: int = 24
    keyword: str = "公务员"
    year: str = "2026"
    provinces: list = []


# ══════════════════════════════════════════════════════
# 仪表盘
# ══════════════════════════════════════════════════════

@router.get("/dashboard")
async def dashboard(admin: dict = Depends(get_admin_user)):
    """管理后台仪表盘数据"""
    stats = get_stats()
    cost = get_api_cost()
    profit = get_profit()

    # 用户统计
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    conn.close()

    # 今日数据（使用最近24小时，避免凌晨显示为0）
    from datetime import timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    # 先查今天，如果没有数据则查昨天（展示最近有活动的数据）
    today_cost = get_api_cost(start_date=today, end_date=today)
    if today_cost.get("total_calls", 0) == 0:
        today_cost = get_api_cost(start_date=yesterday, end_date=yesterday)
        display_date = yesterday
    else:
        display_date = today
    today_profit = get_profit(start_date=display_date, end_date=display_date)

    return {
        # 前端仪表盘需要的扁平字段
        "total_users": user_count,
        "total_jobs": stats.get("jobs", {}).get("total", 0),
        "total_gk_jobs": stats.get("gk_jobs", {}).get("total", 0),
        "today_api_calls": today_cost.get("total_calls", 0),
        "today_revenue": today_profit.get("revenue_yuan", 0),
        "today_cost": today_profit.get("cost_yuan", 0),
        # 保留原始嵌套数据供其他地方使用
        "stats": stats,
        "cost": cost,
        "profit": profit,
        "crawling": {
            "social": is_crawling,
            "gk": gk_is_crawling,
        }
    }


# ══════════════════════════════════════════════════════
# 用户管理
# ══════════════════════════════════════════════════════

@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    admin: dict = Depends(get_admin_user),
):
    """获取用户列表"""
    rows, total = get_users_list(page, page_size, keyword)
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    req: UserUpdateRequest,
    admin: dict = Depends(get_admin_user),
):
    """修改用户信息"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "用户不存在")

    updates = []
    params = []
    if req.credits is not None:
        updates.append("credits = ?")
        params.append(req.credits)
    if req.role is not None:
        updates.append("role = ?")
        params.append(req.role)
    if req.is_disabled is not None:
        updates.append("is_disabled = ?")
        params.append(req.is_disabled)
    if req.password:
        updates.append("password_hash = ?")
        params.append(hash_password(req.password))

    if not updates:
        conn.close()
        return {"ok": True, "message": "无更新"}

    params.append(user_id)
    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()

    return {"ok": True, "message": "更新成功"}


# ══════════════════════════════════════════════════════
# CDK 管理
# ══════════════════════════════════════════════════════

@router.post("/cdk/generate")
async def cdk_generate(req: CdkGenerateRequest, admin: dict = Depends(get_admin_user)):
    """批量生成 CDK 码"""
    if req.credits <= 0:
        raise HTTPException(400, "积分面值必须大于0")
    if req.count <= 0 or req.count > 100:
        raise HTTPException(400, "生成数量范围: 1-100")

    codes = generate_cdk(req.credits, req.price_yuan, req.count)
    return {"ok": True, "codes": codes, "count": len(codes)}


@router.get("/cdk/list")
async def cdk_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    used: str = Query(""),
    admin: dict = Depends(get_admin_user),
):
    """获取 CDK 列表"""
    rows, total = get_cdk_list(page, page_size, used)
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ══════════════════════════════════════════════════════
# 热力图管理
# ══════════════════════════════════════════════════════

@router.get("/hot/config")
async def hot_config(admin: dict = Depends(get_admin_user)):
    """获取热力图配置"""
    return get_hot_jobs(limit=100)


@router.post("/hot/add")
async def add_hot_job(req: HotJobAddRequest, admin: dict = Depends(get_admin_user)):
    """添加岗位到热门"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 检查是否已存在
    cursor.execute("SELECT id FROM hot_jobs WHERE job_id = ? AND job_type = ?", (req.job_id, req.job_type))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(400, "该岗位已在热门列表中")
    
    cursor.execute('''
        INSERT INTO hot_jobs (job_id, job_type, is_pinned, weight, click_count)
        VALUES (?, ?, ?, ?, 0)
    ''', (req.job_id, req.job_type, req.is_pinned, req.weight))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "已添加热门岗位"}


@router.put("/hot/{hot_id}")
async def update_hot_job(
    hot_id: int,
    req: HotJobUpdateRequest,
    admin: dict = Depends(get_admin_user),
):
    """调整热门岗位权重/置顶"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM hot_jobs WHERE id = ?", (hot_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "热门岗位记录不存在")

    updates = []
    params = []
    if req.weight is not None:
        updates.append("weight = ?")
        params.append(req.weight)
    if req.is_pinned is not None:
        updates.append("is_pinned = ?")
        params.append(req.is_pinned)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(hot_id)
        cursor.execute(f"UPDATE hot_jobs SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    return {"ok": True}


@router.delete("/hot/{hot_id}")
async def delete_hot_job(hot_id: int, admin: dict = Depends(get_admin_user)):
    """删除热门岗位"""
    conn = get_db()
    conn.execute("DELETE FROM hot_jobs WHERE id = ?", (hot_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ══════════════════════════════════════════════════════
# 财务统计
# ══════════════════════════════════════════════════════

@router.get("/cost")
async def api_cost(
    start_date: str = Query(""),
    end_date: str = Query(""),
    admin: dict = Depends(get_admin_user),
):
    """API成本统计"""
    d = get_api_cost(start_date or None, end_date or None)
    # 映射到前端期望的字段名
    return {
        "total_calls": d.get("total_calls", 0),
        "total_cost": d.get("total_cost_yuan", 0),
        "total_credits": d.get("total_credits_charged", 0),
        "details": [
            {
                "api_type": t.get("api_type", ""),
                "count": t.get("calls", 0),
                "total_cost": t.get("cost_yuan", 0),
                "total_credits": t.get("credits", 0),
            }
            for t in d.get("by_type", [])
        ],
        "chart": [
            {"date": day.get("date", ""), "cost": day.get("cost_yuan", 0)}
            for day in d.get("daily", [])
        ],
    }


@router.get("/profit")
async def profit(
    start_date: str = Query(""),
    end_date: str = Query(""),
    admin: dict = Depends(get_admin_user),
):
    """利润统计"""
    d = get_profit(start_date or None, end_date or None)
    # 映射到前端期望的字段名
    return {
        "revenue": d.get("revenue_yuan", 0),
        "cost": d.get("cost_yuan", 0),
        "profit": d.get("profit_yuan", 0),
        "recharge_count": d.get("recharge_count", 0),
        "api_call_count": d.get("api_call_count", 0),
    }


@router.get("/recharge/records")
async def recharge_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start_date: str = Query(""),
    end_date: str = Query(""),
    admin: dict = Depends(get_admin_user),
):
    """充值记录"""
    rows, total = get_recharge_records(
        start_date or None, end_date or None, page, page_size
    )
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ══════════════════════════════════════════════════════
# 数据库管理
# ══════════════════════════════════════════════════════

@router.get("/db/tables")
async def db_tables(admin: dict = Depends(get_admin_user)):
    """获取数据库表列表"""
    tables = get_db_tables()
    # 每张表的行数
    conn = get_db()
    cursor = conn.cursor()
    result = []
    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
            count = cursor.fetchone()[0]
            result.append({"name": t, "rows": count})
        except Exception:
            result.append({"name": t, "rows": -1})
    conn.close()
    return result


@router.get("/db/table/{table_name}")
async def db_table_data(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_admin_user),
):
    """获取表数据"""
    columns, rows, total = get_table_data(table_name, page, page_size)
    return {
        "table": table_name,
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/db/query")
async def db_query(req: SqlQueryRequest, admin: dict = Depends(get_admin_user)):
    """只读SQL查询"""
    try:
        columns, rows = exec_readonly_sql(req.sql)
        return {"columns": columns, "rows": rows, "count": len(rows)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"SQL执行错误: {str(e)}")


# ══════════════════════════════════════════════════════
# 爬虫管理（从 Flask 迁移）
# ══════════════════════════════════════════════════════

def _load_crawl_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False, "interval_hours": 12, "keywords": [], "last_run": None, "last_count": 0}


def _save_crawl_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _load_gk_config():
    if os.path.exists(GK_CONFIG_FILE):
        with open(GK_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False, "interval_hours": 24, "keyword": "公务员", "year": "2026", "provinces": [], "last_run": None, "last_count": 0}


def _save_gk_config(cfg):
    os.makedirs(os.path.dirname(GK_CONFIG_FILE), exist_ok=True)
    with open(GK_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _do_crawl(keywords):
    """执行社招采集 —— 弹出独立窗口显示实时进度"""
    global is_crawling, last_crawl_time, last_crawl_count
    if is_crawling:
        return {"success": False, "message": "采集正在进行中"}

    script = os.path.join(BASE_DIR, "login_helper.py")
    kw_str = ",".join(keywords)

    # 准备日志目录
    log_dir = os.path.join(BASE_DIR, "data", "crawl_logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"crawl_{ts}.log")

    try:
        is_crawling = True
        crawl_start_time = time.time()
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 用 PowerShell 在新窗口中运行，Tee 同时输出到窗口 + 日志文件
        ps_cmd = (
            f'chcp 65001 > $null; $OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); '
            f'& "{sys.executable}" "{script}" --keywords "{kw_str}" --auto 2>&1 | '
            f'Tee-Object -FilePath "{log_file}"; '
            f'Write-Host "`n=== 采集完成 ===" -ForegroundColor Green; '
            f'Write-Host "日志文件: {log_file}"'
        )
        proc = subprocess.Popen(
            ["powershell", "-NoExit", "-NoProfile", "-Command", ps_cmd],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        proc.wait(timeout=300)

        # 从日志文件解析结果条数
        count = 0
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if "当前累计" in line and "条" in line:
                        try:
                            count = int("".join(filter(str.isdigit, line.split("当前累计")[-1].split("条")[0].strip())))
                        except Exception:
                            pass
                    elif "本次新增" in line and "条" in line and count == 0:
                        try:
                            count = int("".join(filter(str.isdigit, line.split("本次新增")[-1].split("条")[0].strip())))
                        except Exception:
                            pass
        except Exception:
            pass

        # ── 将 JSON 数据同步到 SQLite 数据库 ──
        db_new = 0
        try:
            db_path = os.path.join(BASE_DIR, "data", "jobs.db")
            conn = sqlite3.connect(db_path)
            db_new = import_jobs_incremental(conn)
            conn.close()
            print(f"[Crawl] 数据库同步完成，新增 {db_new} 条社招岗位")
        except Exception as e:
            print(f"[Crawl] 数据库同步失败: {e}")

        # 以入库条数为主，日志解析为备用
        final_count = db_new if db_new > 0 else count
        last_crawl_time = start_time
        last_crawl_count = final_count

        cfg = _load_crawl_config()
        cfg["last_run"] = start_time
        cfg["last_count"] = final_count
        _save_crawl_config(cfg)

        return {"success": True, "count": final_count, "message": f"采集完成，共 {final_count} 条（日志: {log_file}）", "start_time": start_time}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "采集超时（5分钟）"}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        is_crawling = False
        crawl_start_time = None


def _do_gk_crawl(province_codes, keyword, year="2026", max_pages=None, delay=1.0):
    """执行考公考编采集 —— 弹出独立窗口显示实时进度"""
    global gk_is_crawling, gk_last_crawl_time, gk_last_crawl_count
    if gk_is_crawling:
        return {"success": False, "message": "考公采集正在进行中"}

    script = os.path.join(BASE_DIR, "gongkao_crawler.py")
    prov_str = ",".join(province_codes) if province_codes else "all"
    kw_str = keyword or "公务员"

    # 准备日志目录
    log_dir = os.path.join(BASE_DIR, "data", "crawl_logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"gk_{ts}.log")

    try:
        gk_is_crawling = True
        gk_crawl_start_time = time.time()
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 构建参数
        args_str_parts = []
        if province_codes:
            for p in province_codes:
                args_str_parts.append(f'--province "{p}"')
        else:
            args_str_parts.append("--all")
        args_str_parts.append(f'--keyword "{kw_str}"')
        args_str_parts.append(f'--year "{year}"')
        if max_pages:
            args_str_parts.append(f'--max-pages {max_pages}')
        args_str_parts.append(f'--delay {delay}')
        args_str = " ".join(args_str_parts)

        # 用 PowerShell 在新窗口中运行，Tee 同时输出到窗口 + 日志文件
        ps_cmd = (
            f'chcp 65001 > $null; $OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); '
            f'& "{sys.executable}" "{script}" {args_str} 2>&1 | '
            f'Tee-Object -FilePath "{log_file}"; '
            f'Write-Host "`n=== 考公采集完成 ===" -ForegroundColor Green; '
            f'Write-Host "日志文件: {log_file}"'
        )
        proc = subprocess.Popen(
            ["powershell", "-NoExit", "-NoProfile", "-Command", ps_cmd],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        proc.wait(timeout=600)

        # 从日志解析结果（爬虫输出 "[考公] 总耗时: Xs，总记录: N 条"）
        count = 0
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if "总记录:" in line and "条" in line:
                        try:
                            part = line.split("总记录:")[-1].split("条")[0].strip()
                            count = int("".join(filter(str.isdigit, part)))
                        except Exception:
                            pass
        except Exception:
            pass

        # ── 将 JSON 数据同步到 SQLite 数据库 ──
        db_new = 0
        try:
            db_path = os.path.join(BASE_DIR, "data", "jobs.db")
            conn = sqlite3.connect(db_path)
            db_new = import_gk_jobs_incremental(conn)
            conn.close()
            print(f"[Crawl] 数据库同步完成，新增 {db_new} 条公考岗位")
        except Exception as e:
            print(f"[Crawl] 数据库同步失败: {e}")

        gk_last_crawl_time = start_time
        # 以入库条数为主，日志解析为备用
        final_count = db_new if db_new > 0 else count
        gk_last_crawl_count = final_count

        cfg = _load_gk_config()
        cfg["last_run"] = start_time
        cfg["last_count"] = final_count
        _save_gk_config(cfg)

        return {"success": True, "count": final_count, "message": f"考公采集完成，共 {final_count} 条（日志: {log_file}）", "start_time": start_time}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "考公采集超时（10分钟）"}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        gk_is_crawling = False
        gk_crawl_start_time = None


@router.get("/crawl/schedule")
async def get_crawl_schedule(admin: dict = Depends(get_admin_user)):
    """获取社招爬虫调度配置"""
    cfg = _load_crawl_config()
    return {
        "enabled": cfg.get("enabled", False),
        "interval_hours": cfg.get("interval_hours", 12),
        "keywords": cfg.get("keywords", []),
        "last_run": last_crawl_time or cfg.get("last_run"),
        "last_count": last_crawl_count or cfg.get("last_count", 0),
        "is_running": is_crawling,
    }


@router.post("/crawl/schedule")
async def update_crawl_schedule(req: CrawlScheduleRequest, admin: dict = Depends(get_admin_user)):
    """更新社招爬虫调度配置"""
    if not req.keywords:
        raise HTTPException(400, "关键词不能为空")

    cfg = _load_crawl_config()
    cfg["keywords"] = req.keywords
    cfg["interval_hours"] = max(1, min(168, req.interval_hours))
    cfg["enabled"] = req.enabled
    _save_crawl_config(cfg)

    return {"ok": True, "message": f"配置已更新：{'启用' if req.enabled else '停用'}，每 {req.interval_hours} 小时"}


@router.post("/crawl/now")
async def trigger_crawl_now(admin: dict = Depends(get_admin_user)):
    """立即触发社招采集"""
    global is_crawling, crawl_start_time
    if is_crawling:
        # 如果采集已卡住超过 10 分钟，自动重置
        if crawl_start_time and (time.time() - crawl_start_time) > 600:
            is_crawling = False
            crawl_start_time = None
        else:
            raise HTTPException(409, "采集正在进行中，请稍后再试")

    cfg = _load_crawl_config()
    keywords = cfg.get("keywords", [])
    if not keywords:
        raise HTTPException(400, "请先配置关键词")

    kw_copy = list(keywords)
    threading.Thread(target=_do_crawl, args=(kw_copy,), daemon=True).start()
    return {"ok": True, "message": f"采集已启动，关键词：{keywords}"}


@router.get("/crawl/gk/schedule")
async def get_gk_schedule(admin: dict = Depends(get_admin_user)):
    """获取考公爬虫调度配置"""
    cfg = _load_gk_config()
    return {
        "enabled": cfg.get("enabled", False),
        "interval_hours": cfg.get("interval_hours", 24),
        "keyword": cfg.get("keyword", "公务员"),
        "year": cfg.get("year", "2026"),
        "provinces": cfg.get("provinces", []),
        "last_run": gk_last_crawl_time or cfg.get("last_run"),
        "last_count": gk_last_crawl_count or cfg.get("last_count", 0),
        "is_running": gk_is_crawling,
    }


@router.post("/crawl/gk/schedule")
async def update_gk_schedule(req: GkCrawlScheduleRequest, admin: dict = Depends(get_admin_user)):
    """更新考公爬虫调度配置"""
    cfg = _load_gk_config()
    cfg["keyword"] = req.keyword
    cfg["year"] = req.year
    cfg["provinces"] = req.provinces
    cfg["interval_hours"] = max(1, min(168, req.interval_hours))
    cfg["enabled"] = req.enabled
    _save_gk_config(cfg)

    return {"ok": True, "message": f"考公配置已更新：关键词={req.keyword}，省份={req.provinces or '全部'}"}


@router.post("/crawl/gk/now")
async def trigger_gk_crawl_now(admin: dict = Depends(get_admin_user)):
    """立即触发考公采集"""
    global gk_is_crawling, gk_crawl_start_time
    if gk_is_crawling:
        if gk_crawl_start_time and (time.time() - gk_crawl_start_time) > 1200:
            gk_is_crawling = False
            gk_crawl_start_time = None
        else:
            raise HTTPException(409, "考公采集正在进行中，请稍后再试")

    cfg = _load_gk_config()
    provinces = cfg.get("provinces", [])
    keyword = cfg.get("keyword", "公务员")
    year = cfg.get("year", "2026")

    threading.Thread(
        target=_do_gk_crawl,
        args=(provinces, keyword, year),
        kwargs={"max_pages": cfg.get("max_pages"), "delay": cfg.get("delay", 1.0)},
        daemon=True
    ).start()
    return {"ok": True, "message": f"考公采集已启动，省份：{provinces or '全部'}，关键词：{keyword}"}
