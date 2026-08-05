#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth.py — 用户认证与积分管理模块

提供:
  - hash_password() / verify_password()  密码哈希与验证
  - create_access_token() / decode_token()  JWT 创建与解析
  - register_user()       注册新用户
  - authenticate_user()   登录验证
  - get_current_user()    FastAPI 依赖注入，获取当前用户
  - deduct_credits()      扣积分（事务内）
  - recharge_credits()    CDK 充值
  - generate_cdk()        批量生成 CDK
"""

import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import bcrypt as _bcrypt
from jose import JWTError, jwt

# ── 配置 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "jobs.db")

# JWT 配置
_env_path = os.path.join(BASE_DIR, ".env.match")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k and k not in os.environ:
                    os.environ[k] = v

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72  # token 有效期 72 小时

# 如果没有 JWT_SECRET，自动生成并写入 .env.match
if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(32)
    with open(_env_path, "a", encoding="utf-8") as f:
        f.write(f"\nJWT_SECRET={JWT_SECRET}\n")

# 积分定价
CREDITS_RESUME_PARSE = 10
CREDITS_JOB_MATCH = 15
CREDITS_RESUME_ANALYSIS = 20

# VIP 定价
CREDITS_VIP_MONTHLY = 300
VIP_DURATION_DAYS = 30

# DeepSeek 定价 (元/千token)
DEEPSEEK_INPUT_PRICE = 0.002   # V4-Pro: 2元/百万tokens = 0.002元/千tokens
DEEPSEEK_OUTPUT_PRICE = 0.008  # V4-Pro: 8元/百万tokens = 0.008元/千tokens


# ══════════════════════════════════════════════════════
# 密码哈希
# ══════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    """密码 bcrypt 哈希"""
    return _bcrypt.hashpw(password.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码"""
    try:
        return _bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


# ══════════════════════════════════════════════════════
# JWT
# ══════════════════════════════════════════════════════
def create_access_token(user_id: int, role: str = "user") -> str:
    """创建 JWT token"""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解析 JWT token，返回 payload 或 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


# ══════════════════════════════════════════════════════
# 数据库连接
# ══════════════════════════════════════════════════════
def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ══════════════════════════════════════════════════════
# 用户注册
# ══════════════════════════════════════════════════════
def register_user(username: str, password: str, role: str = "user") -> dict:
    """
    注册新用户

    Returns:
        {"ok": True, "user_id": int} 或 {"ok": False, "message": str}
    """
    if not username or len(username) < 2:
        return {"ok": False, "message": "用户名至少2个字符"}
    if not password or len(password) < 4:
        return {"ok": False, "message": "密码至少4个字符"}
    if len(username) > 32:
        return {"ok": False, "message": "用户名最长32个字符"}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        # 检查用户名是否已存在
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            return {"ok": False, "message": "用户名已存在"}

        password_hash = hash_password(password)
        cursor.execute('''
            INSERT INTO users (username, password_hash, credits, role)
            VALUES (?, ?, 0, ?)
        ''', (username, password_hash, role))
        conn.commit()
        user_id = cursor.lastrowid
        return {"ok": True, "user_id": user_id}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# 用户登录
# ══════════════════════════════════════════════════════
def authenticate_user(username: str, password: str) -> dict:
    """
    验证用户凭据

    Returns:
        {"ok": True, "user_id": int, "role": str, "token": str}
        {"ok": False, "message": str}
    """
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, password_hash, role, is_disabled FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()

        if not row:
            return {"ok": False, "message": "用户名或密码错误"}
        if row["is_disabled"]:
            return {"ok": False, "message": "账号已被禁用"}
        if not verify_password(password, row["password_hash"]):
            return {"ok": False, "message": "用户名或密码错误"}

        token = create_access_token(row["id"], row["role"])
        return {
            "ok": True,
            "user_id": row["id"],
            "role": row["role"],
            "token": token,
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# 获取用户信息
# ══════════════════════════════════════════════════════
def get_user_by_id(user_id: int) -> Optional[dict]:
    """根据 ID 获取用户信息"""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, credits, role, is_disabled, is_vip, vip_expired_at, created_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_token(token: str) -> Optional[dict]:
    """根据 JWT token 获取用户信息"""
    payload = decode_token(token)
    if not payload:
        return None
    user_id = int(payload.get("sub", 0))
    return get_user_by_id(user_id)


# ══════════════════════════════════════════════════════
# 积分操作
# ══════════════════════════════════════════════════════
def deduct_credits(user_id: int, amount: int, api_type: str,
                   input_tokens: int = 0, output_tokens: int = 0,
                   model: str = "deepseek-chat") -> dict:
    """
    扣除积分（原子事务）

    Returns:
        {"ok": True} 或 {"ok": False, "message": str}
    """
    if amount <= 0:
        return {"ok": False, "message": "扣费金额必须大于0"}

    # 计算实际成本（元）
    cost_yuan = (input_tokens / 1000 * DEEPSEEK_INPUT_PRICE +
                 output_tokens / 1000 * DEEPSEEK_OUTPUT_PRICE)

    conn = _get_db()
    try:
        cursor = conn.cursor()

        # 检查余额
        cursor.execute("SELECT credits, is_disabled FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "message": "用户不存在"}
        if row["is_disabled"]:
            return {"ok": False, "message": "账号已被禁用"}
        if row["credits"] < amount:
            return {"ok": False, "message": f"积分不足（当前{row['credits']}积分，需{amount}积分）"}

        # 扣积分
        cursor.execute("UPDATE users SET credits = credits - ? WHERE id = ?", (amount, user_id))

        # 记录日志
        cursor.execute('''
            INSERT INTO api_call_logs (user_id, api_type, model, input_tokens, output_tokens, cost_yuan, credits_charged)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, api_type, model, input_tokens, output_tokens, cost_yuan, amount))

        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def recharge_with_cdk(user_id: int, cdk_code: str) -> dict:
    """
    使用 CDK 充值

    Returns:
        {"ok": True, "credits": int, "price_yuan": float} 或 {"ok": False, "message": str}
    """
    conn = _get_db()
    try:
        cursor = conn.cursor()

        # 查找 CDK
        cursor.execute("SELECT id, credits, price_yuan, used_by FROM cdk_codes WHERE code = ?", (cdk_code,))
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "message": "CDK 码无效"}
        if row["used_by"] is not None:
            return {"ok": False, "message": "CDK 码已被使用"}

        # 充值
        cursor.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (row["credits"], user_id))

        # 标记 CDK 已使用
        now = datetime.now().isoformat()
        cursor.execute("UPDATE cdk_codes SET used_by = ?, used_at = ? WHERE id = ?",
                       (user_id, now, row["id"]))

        # 充值记录
        cursor.execute('''
            INSERT INTO recharge_records (user_id, cdk_code, credits, price_yuan)
            VALUES (?, ?, ?, ?)
        ''', (user_id, cdk_code, row["credits"], row["price_yuan"]))

        conn.commit()
        return {
            "ok": True,
            "credits": row["credits"],
            "price_yuan": row["price_yuan"],
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# CDK 生成
# ══════════════════════════════════════════════════════
def generate_cdk(credits: int, price_yuan: float, count: int = 1) -> list:
    """
    批量生成 CDK 码

    Args:
        credits: 面值（积分）
        price_yuan: 售价（元）
        count: 生成数量

    Returns:
        list[str] 生成的 CDK 码列表
    """
    codes = []
    conn = _get_db()
    try:
        cursor = conn.cursor()
        for _ in range(count):
            code = secrets.token_urlsafe(24)  # ~32字符
            cursor.execute('''
                INSERT INTO cdk_codes (code, credits, price_yuan)
                VALUES (?, ?, ?)
            ''', (code, credits, price_yuan))
            codes.append(code)
        conn.commit()
        return codes
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# 行为日志
# ══════════════════════════════════════════════════════
def log_action(user_id: int, action: str, detail: str = None):
    """记录用户行为"""
    conn = _get_db()
    try:
        conn.execute('''
            INSERT INTO user_actions (user_id, action, detail)
            VALUES (?, ?, ?)
        ''', (user_id, action, detail))
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# FastAPI 依赖注入
# ══════════════════════════════════════════════════════
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    FastAPI 依赖注入：从 Authorization header 获取当前用户

    用法:
        @app.get("/api/xxx")
        async def xxx(user: dict = Depends(get_current_user)):
            user_id = user["id"]
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_token(credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
        )
    if user.get("is_disabled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )
    return user


async def get_admin_user(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI 依赖注入：仅管理员可用"""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


async def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    """FastAPI 依赖注入：可选登录（未登录返回 None）"""
    if not credentials:
        return None
    user = get_user_by_token(credentials.credentials)
    if user and not user.get("is_disabled"):
        return user
    return None


# ══════════════════════════════════════════════════════
# VIP 会员系统
# ══════════════════════════════════════════════════════

def check_vip_status(user: dict) -> dict:
    """检查用户 VIP 状态

    Returns:
        {"is_vip": bool, "expired_at": str|None, "days_left": int|None, "message": str}
    """
    is_vip = bool(user.get("is_vip"))
    expired_at = user.get("vip_expired_at")

    if not is_vip or not expired_at:
        return {"is_vip": False, "expired_at": None, "days_left": None, "message": "未开通会员"}

    try:
        expire_dt = datetime.fromisoformat(expired_at)
        if expire_dt > datetime.utcnow():
            days_left = (expire_dt - datetime.utcnow()).days
            return {"is_vip": True, "expired_at": expired_at, "days_left": days_left,
                    "message": f"会员有效，剩余 {days_left} 天"}
        else:
            return {"is_vip": False, "expired_at": expired_at, "days_left": 0, "message": "会员已过期"}
    except Exception:
        return {"is_vip": False, "expired_at": expired_at, "days_left": None, "message": "会员状态异常"}


def activate_vip(user_id: int) -> dict:
    """开通/续费包月会员（扣 300 积分，有效期 30 天）

    Returns:
        {"ok": True, "expired_at": str, "message": str}
        {"ok": False, "message": str}
    """
    conn = _get_db()
    try:
        cursor = conn.cursor()

        # 检查用户
        cursor.execute("SELECT id, credits, is_vip, vip_expired_at, is_disabled FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return {"ok": False, "message": "用户不存在"}
        if row["is_disabled"]:
            return {"ok": False, "message": "账号已被禁用"}
        if row["credits"] < CREDITS_VIP_MONTHLY:
            return {"ok": False, "message": f"积分不足，需要 {CREDITS_VIP_MONTHLY} 积分（当前 {row['credits']} 积分）"}

        # 计算到期时间：如果已有有效会员，在现有到期时间基础上 +30天；否则从今天 +30天
        now = datetime.utcnow()
        existing_expire = row["vip_expired_at"]
        if existing_expire:
            try:
                base = datetime.fromisoformat(existing_expire)
                if base > now:
                    now = base  # 续费：从当前到期日开始算
            except Exception:
                pass

        new_expire = now + timedelta(days=VIP_DURATION_DAYS)
        new_expire_str = new_expire.isoformat()

        # 扣积分 + 设置VIP
        cursor.execute("UPDATE users SET credits = credits - ?, is_vip = 1, vip_expired_at = ? WHERE id = ?",
                       (CREDITS_VIP_MONTHLY, new_expire_str, user_id))

        # 写入订单记录
        cursor.execute('''
            INSERT INTO vip_orders (user_id, credits_used, started_at, expired_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, CREDITS_VIP_MONTHLY, datetime.utcnow().isoformat(), new_expire_str))

        # 行为日志
        cursor.execute('''
            INSERT INTO user_actions (user_id, action, detail)
            VALUES (?, 'activate_vip', ?)
        ''', (user_id, f'credits={CREDITS_VIP_MONTHLY},expire={new_expire_str}'))

        conn.commit()

        days_left = (new_expire - datetime.utcnow()).days
        return {
            "ok": True,
            "expired_at": new_expire_str,
            "days_left": days_left,
            "message": f"会员开通成功！有效期至 {new_expire_str[:10]}，剩余 {days_left} 天",
        }
    finally:
        conn.close()


def record_vip_free_call(user_id: int, api_type: str, input_tokens: int = 0,
                          output_tokens: int = 0, model: str = "deepseek-chat"):
    """记录 VIP 免费调用（不扣积分，仅记录日志和成本）

    Returns:
        {"ok": True}
    """
    cost_yuan = (input_tokens / 1000 * DEEPSEEK_INPUT_PRICE +
                 output_tokens / 1000 * DEEPSEEK_OUTPUT_PRICE)

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO api_call_logs (user_id, api_type, model, input_tokens, output_tokens, cost_yuan, credits_charged)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (user_id, api_type, model, input_tokens, output_tokens, cost_yuan))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def get_email_config() -> dict:
    """获取邮件配置"""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT smtp_host, smtp_port, smtp_user, smtp_pass, from_email, enabled FROM email_config WHERE id=1")
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {"smtp_host": "", "smtp_port": 465, "smtp_user": "", "smtp_pass": "", "from_email": "", "enabled": 0}
    finally:
        conn.close()


def save_email_config(config: dict) -> dict:
    """更新邮件配置"""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE email_config
            SET smtp_host=?, smtp_port=?, smtp_user=?, smtp_pass=?, from_email=?, enabled=?
            WHERE id=1
        ''', (config.get("smtp_host", ""), config.get("smtp_port", 465),
              config.get("smtp_user", ""), config.get("smtp_pass", ""),
              config.get("from_email", ""), int(config.get("enabled", 0))))
        conn.commit()
        return {"ok": True, "message": "邮件配置已更新"}
    finally:
        conn.close()
