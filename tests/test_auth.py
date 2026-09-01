"""
用户认证模块测试(第一批)

覆盖:密码散列/校验、密码强度检测、JWT 签发/解析/过期/篡改、前后端强度逻辑一致性。
说明:注册/登录 HTTP 接口的正确性在 Docker 端到端验证(单元层不连 PostgreSQL、不触发 akshare 导入)。

运行: pytest tests/test_auth.py -v
"""
import os
import time

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_EXPIRE_HOURS", "1")

from backend.services.auth import (  # noqa: E402
    create_token,
    decode_token,
    hash_password,
    password_strength,
    verify_password,
)


class _FakeUser:
    def __init__(self, uid, username="tester", role="user"):
        self.id = uid
        self.username = username
        self.role = role


# ------------------------------------------------------------
# 密码散列
# ------------------------------------------------------------
def test_hash_and_verify():
    h = hash_password("Admin@123")
    assert h != "Admin@123"                     # 不存明文
    assert verify_password("Admin@123", h)       # 正确密码通过
    assert not verify_password("wrong-pass", h)  # 错误密码拒绝


def test_hash_unique_salt():
    h1, h2 = hash_password("Admin@123"), hash_password("Admin@123")
    assert h1 != h2                              # 每次散列不同(含盐)


def test_verify_invalid_hash_returns_false():
    assert verify_password("x", "not-a-valid-hash") is False


# ------------------------------------------------------------
# 密码强度
# ------------------------------------------------------------
def test_password_strength_levels():
    assert password_strength("")["label"] == "未输入"
    assert password_strength("abc")["label"] == "弱"
    assert password_strength("abc12345")["label"] == "中"       # 长度+数字
    assert password_strength("Admin@123")["label"] == "强"      # 大小写+数字+符号


def test_password_strength_ok_threshold():
    assert password_strength("weak")["ok"] is False
    assert password_strength("Abc123456")["ok"] is True


# ------------------------------------------------------------
# JWT
# ------------------------------------------------------------
def test_token_roundtrip():
    token = create_token(_FakeUser(7, "tester", "admin"))
    payload = decode_token(token)
    assert payload["sub"] == "7"
    assert payload["username"] == "tester"
    assert payload["role"] == "admin"
    assert payload["exp"] > int(time.time())


def test_token_expiry():
    import backend.services.auth as auth_mod
    old = auth_mod.JWT_EXPIRE_HOURS
    auth_mod.JWT_EXPIRE_HOURS = 0  # 立即过期
    try:
        token = create_token(_FakeUser(1))
        with pytest.raises(Exception):  # jwt.ExpiredSignatureError 是 PyJWTError 子类
            decode_token(token)
    finally:
        auth_mod.JWT_EXPIRE_HOURS = old


def test_token_tampered_rejected():
    token = create_token(_FakeUser(1))
    # 改 payload 最后一个字符(去掉签名对齐的字符,再补一个合法 base64 字符)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(Exception):
        decode_token(tampered)


# ------------------------------------------------------------
# 前后端密码强度逻辑一致性(防止两处漂移)
# ------------------------------------------------------------
def test_frontend_backend_strength_parity():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "frontend"))
    from auth_ui import _strength

    for pw in ["", "abc", "abc12345", "Admin@123", "Abc123456!", "aA1!bbbb"]:
        assert _strength(pw)["ok"] == password_strength(pw)["ok"], pw
        assert _strength(pw)["label"] == password_strength(pw)["label"], pw
