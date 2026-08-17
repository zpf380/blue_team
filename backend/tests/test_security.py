"""security 纯逻辑单元测试（不依赖数据库）。"""
import datetime as dt

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("Bt@123456")
    assert h != "Bt@123456"
    assert verify_password("Bt@123456", h)
    assert not verify_password("wrong", h)


def test_password_hash_salt_differs():
    assert hash_password("same") != hash_password("same")


def test_access_token_roundtrip():
    token = create_access_token(1, "admin", ["*"])
    payload = decode_token(token)
    assert payload["sub"] == "1"
    assert payload["role"] == "admin"
    assert payload["permissions"] == ["*"]
    assert payload["type"] == "access"


def test_refresh_token_type():
    token = create_refresh_token(1)
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_decode_garbage_returns_none():
    assert decode_token("not-a-token") is None


def test_expired_token_returns_none():
    token = jwt.encode(
        {
            "sub": "1",
            "type": "access",
            "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert decode_token(token) is None
