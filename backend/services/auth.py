"""
用户认证模块(第一批)

- bcrypt 密码散列 / 校验
- JWT(HS256)签发 / 解析
- 密码强度检测(弱/中/强)
- FastAPI 依赖 get_current_user:从 Authorization: Bearer <token> 还原当前用户

配置(环境变量):
  JWT_SECRET        签名密钥(生产必须改为随机强密钥)
  JWT_EXPIRE_HOURS  token 有效期(小时),默认 72
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException

# 注意:models 懒加载(避免认证模块在导入时强依赖数据库驱动;也便于单元测试)
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me-in-prod")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))
ALGORITHM = "HS256"


# ------------------------------------------------------------
# 密码散列
# ------------------------------------------------------------
def hash_password(password: str) -> str:
    """bcrypt 散列,返回 str(内含盐)"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码;格式异常返回 False(不抛异常)"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------
# 密码强度检测
# ------------------------------------------------------------
def password_strength(password: str) -> dict:
    """检测密码强度,返回 {score(0-4), label(弱/中/强), ok}"""
    if not password:
        return {"score": 0, "label": "未输入", "ok": False}
    score = 0
    if len(password) >= 8:
        score += 1
    if any(c.isupper() for c in password) and any(c.islower() for c in password):
        score += 1
    if any(c.isdigit() for c in password):
        score += 1
    if any(c in "!@#$%^&*()-_=+[]{};:,.?/" for c in password):
        score += 1
    if score <= 1:
        label = "弱"
    elif score == 2:
        label = "中"
    else:
        label = "强"
    return {"score": score, "label": label, "ok": score >= 2}


# ------------------------------------------------------------
# JWT
# ------------------------------------------------------------
def create_token(user: User) -> str:
    """为用户签发 JWT,payload 含 user_id/username/role"""
    payload = {
        "jti": uuid.uuid4().hex,
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解析 JWT,失败抛 jwt.PyJWTError(由调用方转 401)"""
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])


# ------------------------------------------------------------
# 用户查询辅助
# ------------------------------------------------------------
def get_user_by_id(user_id: int):
    """按 id 查用户(懒加载 models,避免导入期依赖数据库驱动)"""
    from ..models import SessionLocal, User
    with SessionLocal() as session:
        return session.get(User, user_id)


def get_user_by_name(username: str):
    """按用户名查用户"""
    from ..models import SessionLocal, User
    from sqlalchemy import select
    with SessionLocal() as session:
        return session.scalar(select(User).where(User.username == username))


# ------------------------------------------------------------
# FastAPI 依赖:还原当前用户
# ------------------------------------------------------------
def get_current_user(authorization: str = Header(default="")) -> User:
    """从请求头解析当前用户;无效/过期抛 401。用法:def f(user: User = Depends(get_current_user))"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization[7:]
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="登录已过期,请重新登录")
    user = get_user_by_id(int(payload.get("sub", 0)))
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
