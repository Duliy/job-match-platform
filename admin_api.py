#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
admin_api.py — 管理后台 API 路由（校园交付版）

包含:
  - 用户管理
  - 热力图管理
  - 数据库管理
  - 爬虫调度管理（执行引擎在 scheduler.py，单进程内运行）
  - 数据源健康面板
  - Cookie 管理（辅导员在自己电脑的浏览器里直接上传，无需登录服务器）
  - 订阅推送管理（SQL 粗筛，无需 AI Key）

校园版已移除：CDK 充值、积分、成本/利润等商业化功能。
"""

import json
import os
import threading
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

import scheduler
from auth import get_admin_user, hash_password
from match_db import (
    get_db,
    get_users_list,
    get_hot_jobs,
    get_db_tables,
    get_table_data,
    exec_readonly_sql,
    get_stats,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_DIR = os.path.join(BASE_DIR, "cookies")

# 需要 Cookie 的平台（与 login_helper.py 的 PLATFORMS 保持一致）
# optional=True 表示该平台免登录也能采集，Cookie 只是锦上添花
COOKIE_PLATFORMS = [
    ("51job", "前程无忧", True),
    ("shixiseng", "实习僧", True),
    ("zhaopin", "智联招聘", False),
    ("liepin", "猎聘网", False),
]


# ══════════════════════════════════════════════════════
# Pydantic 模型
# ══════════════════════════════════════════════════════


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
    """管理后台仪表盘数据（校园版：去掉收入/成本等商业化指标）"""
    stats = get_stats()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    # 订阅用户数（绑定了通知邮箱的学生）
    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE notify_email IS NOT NULL AND notify_email != ''"
    )
    subscriber_count = cursor.fetchone()[0]
    conn.close()

    return {
        "total_users": user_count,
        "subscriber_count": subscriber_count,
        "total_jobs": stats.get("jobs", {}).get("total", 0),
        "total_gk_jobs": stats.get("gk_jobs", {}).get("total", 0),
        "stats": stats,
        "crawling": {
            "social": scheduler.social_running,
            "gk": scheduler.gk_running,
        },
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
    cursor.execute(
        "SELECT id FROM hot_jobs WHERE job_id = ? AND job_type = ?",
        (req.job_id, req.job_type),
    )
    if cursor.fetchone():
        conn.close()
        raise HTTPException(400, "该岗位已在热门列表中")

    cursor.execute(
        """
        INSERT INTO hot_jobs (job_id, job_type, is_pinned, weight, click_count)
        VALUES (?, ?, ?, ?, 0)
    """,
        (req.job_id, req.job_type, req.is_pinned, req.weight),
    )
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
    return scheduler.load_crawl_config()


def _save_crawl_config(cfg):
    scheduler.save_crawl_config(cfg)


def _load_gk_config():
    return scheduler.load_gk_config()


def _save_gk_config(cfg):
    scheduler.save_gk_config(cfg)


# 采集执行已统一收敛到 scheduler.py（headless 无弹窗，适合无人值守服务器）


@router.get("/crawl/schedule")
async def get_crawl_schedule(admin: dict = Depends(get_admin_user)):
    """获取社招爬虫调度配置"""
    cfg = _load_crawl_config()
    return {
        "enabled": cfg.get("enabled", False),
        "interval_hours": cfg.get("interval_hours", 12),
        "keywords": cfg.get("keywords", []),
        "last_run": scheduler.social_last_run or cfg.get("last_run"),
        "last_count": scheduler.social_last_count or cfg.get("last_count", 0),
        "last_error": cfg.get("last_error", ""),
        "is_running": scheduler.social_running,
    }


@router.post("/crawl/schedule")
async def update_crawl_schedule(
    req: CrawlScheduleRequest, admin: dict = Depends(get_admin_user)
):
    """更新社招爬虫调度配置"""
    if not req.keywords:
        raise HTTPException(400, "关键词不能为空")

    cfg = _load_crawl_config()
    cfg["keywords"] = req.keywords
    cfg["interval_hours"] = max(1, min(168, req.interval_hours))
    cfg["enabled"] = req.enabled
    _save_crawl_config(cfg)
    scheduler.reload_schedules()

    return {
        "ok": True,
        "message": f"配置已更新：{'启用' if req.enabled else '停用'}，每 {req.interval_hours} 小时",
    }


@router.post("/crawl/now")
async def trigger_crawl_now(admin: dict = Depends(get_admin_user)):
    """立即触发社招采集"""
    if scheduler.social_running:
        raise HTTPException(409, "采集正在进行中，请稍后再试")

    cfg = _load_crawl_config()
    keywords = cfg.get("keywords", [])
    if not keywords:
        raise HTTPException(400, "请先配置关键词")

    kw_copy = list(keywords)
    threading.Thread(
        target=scheduler.run_social_crawl, args=(kw_copy,), daemon=True
    ).start()
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
        "last_run": scheduler.gk_last_run or cfg.get("last_run"),
        "last_count": scheduler.gk_last_count or cfg.get("last_count", 0),
        "last_error": cfg.get("last_error", ""),
        "is_running": scheduler.gk_running,
    }


@router.post("/crawl/gk/schedule")
async def update_gk_schedule(
    req: GkCrawlScheduleRequest, admin: dict = Depends(get_admin_user)
):
    """更新考公爬虫调度配置"""
    cfg = _load_gk_config()
    cfg["keyword"] = req.keyword
    cfg["year"] = req.year
    cfg["provinces"] = req.provinces
    cfg["interval_hours"] = max(1, min(168, req.interval_hours))
    cfg["enabled"] = req.enabled
    _save_gk_config(cfg)
    scheduler.reload_schedules()

    return {
        "ok": True,
        "message": f"考公配置已更新：关键词={req.keyword}，省份={req.provinces or '全部'}",
    }


@router.post("/crawl/gk/now")
async def trigger_gk_crawl_now(admin: dict = Depends(get_admin_user)):
    """立即触发考公采集"""
    if scheduler.gk_running:
        raise HTTPException(409, "考公采集正在进行中，请稍后再试")

    cfg = _load_gk_config()
    provinces = cfg.get("provinces", [])
    keyword = cfg.get("keyword", "公务员")
    year = cfg.get("year", "2026")

    threading.Thread(
        target=scheduler.run_gk_crawl,
        args=(provinces, keyword, year),
        kwargs={"max_pages": cfg.get("max_pages"), "delay": cfg.get("delay", 1.0)},
        daemon=True,
    ).start()
    return {
        "ok": True,
        "message": f"考公采集已启动，省份：{provinces or '全部'}，关键词：{keyword}",
    }


# ══════════════════════════════════════════════════════
# 数据源健康面板
# ══════════════════════════════════════════════════════
def _cookie_status():
    """检查各平台 Cookie 文件状态（存在性 + 新旧程度）"""
    result = []
    for key, label, optional in COOKIE_PLATFORMS:
        path = os.path.join(COOKIE_DIR, f"{key}.json")
        if not os.path.exists(path):
            result.append(
                {
                    "key": key,
                    "label": label,
                    "optional": optional,
                    "status": "missing_optional" if optional else "missing",
                    "age_days": None,
                    "updated_at": None,
                }
            )
            continue
        mtime = os.path.getmtime(path)
        age_days = round((time.time() - mtime) / 86400, 1)
        updated_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        if age_days <= 5:
            status = "ok"
        elif age_days <= 8:
            status = "aging"
        else:
            status = "expired"
        result.append(
            {
                "key": key,
                "label": label,
                "optional": optional,
                "status": status,
                "age_days": age_days,
                "updated_at": updated_at,
            }
        )
    return result


@router.get("/health")
async def health(admin: dict = Depends(get_admin_user)):
    """数据源健康面板：采集状态 + Cookie 状态 + 数据量，一页看清系统死活"""
    st = scheduler.status()
    stats = get_stats()
    return {
        "ok": True,
        "crawl": st["social"],
        "gk": st["gk"],
        "subscription": st["subscription"],
        "cookies": _cookie_status(),
        "jobs_total": stats.get("jobs", {}).get("total", 0),
        "gk_jobs_total": stats.get("gk_jobs", {}).get("total", 0),
        "db_last_updated": stats.get("last_updated", ""),
    }


# ══════════════════════════════════════════════════════
# Cookie 管理（辅导员在自己电脑浏览器里操作，无需登录服务器）
# ══════════════════════════════════════════════════════
@router.get("/cookies")
async def cookie_list(admin: dict = Depends(get_admin_user)):
    """查看各平台 Cookie 状态"""
    return {"ok": True, "cookies": _cookie_status()}


@router.post("/cookies/upload")
async def cookie_upload(
    platform: str = Query(...),
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user),
):
    """上传某个平台的 Cookie 文件（由 Cookie 采集工具生成）"""
    valid_keys = {k for k, _, _ in COOKIE_PLATFORMS}
    if platform not in valid_keys:
        raise HTTPException(
            400, f"未知平台：{platform}（可选：{', '.join(valid_keys)}）"
        )

    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("Cookie 文件应为 JSON 数组")
    except Exception as e:
        raise HTTPException(400, f"Cookie 文件格式不正确：{e}")

    os.makedirs(COOKIE_DIR, exist_ok=True)
    path = os.path.join(COOKIE_DIR, f"{platform}.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))

    label = dict((k, lbl) for k, lbl, _ in COOKIE_PLATFORMS)[platform]
    return {"ok": True, "message": f"{label} Cookie 已更新（{len(data)} 条）"}


# ══════════════════════════════════════════════════════
# 订阅推送管理（SQL 粗筛推送，无需 AI Key）
# ══════════════════════════════════════════════════════
class SubscriptionScheduleRequest(BaseModel):
    enabled: bool = True
    interval_hours: int = 48


@router.get("/subscription/schedule")
async def get_subscription_schedule(admin: dict = Depends(get_admin_user)):
    """获取订阅推送配置"""
    cfg = scheduler.load_sub_config()
    return {
        "enabled": cfg.get("enabled", True),
        "interval_hours": cfg.get("interval_hours", 48),
        "last_run": scheduler.sub_last_run or cfg.get("last_run"),
        "last_scan_count": scheduler.sub_last_scan_count
        or cfg.get("last_scan_count", 0),
        "last_notify_count": scheduler.sub_last_notify_count
        or cfg.get("last_notify_count", 0),
        "last_error": cfg.get("last_error", ""),
        "is_running": scheduler.sub_running,
    }


@router.post("/subscription/schedule")
async def update_subscription_schedule(
    req: SubscriptionScheduleRequest, admin: dict = Depends(get_admin_user)
):
    """更新订阅推送配置"""
    cfg = scheduler.load_sub_config()
    cfg["enabled"] = req.enabled
    cfg["interval_hours"] = max(1, min(168, req.interval_hours))
    scheduler.save_sub_config(cfg)
    scheduler.reload_schedules()
    return {
        "ok": True,
        "message": f"订阅推送已{'启用' if req.enabled else '停用'}，每 {req.interval_hours} 小时扫描一次",
    }


@router.post("/subscription/scan-now")
async def trigger_subscription_scan(admin: dict = Depends(get_admin_user)):
    """立即执行一次订阅推送扫描"""
    if scheduler.sub_running:
        raise HTTPException(409, "订阅扫描正在进行中，请稍后再试")
    threading.Thread(target=scheduler.run_subscription_scan, daemon=True).start()
    return {"ok": True, "message": "订阅扫描已启动"}
