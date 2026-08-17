"""认证与用户管理集成测试（需 PostgreSQL 可用，否则自动跳过）。

覆盖：登录 / MFA（TOTP）两段式 / 图形验证码（自适应） / HttpOnly Cookie 会话 / CSRF。
conftest 已关闭测试环境的「管理员强制 MFA」，存量 admin 登录用例不受影响；
MFA 功能用普通账号（trainee01 / manager01）专项验证。
"""
import uuid

import pytest
import pyotp
from redis import asyncio as aioredis
from sqlalchemy import select

from app.models import User

REDIS_URL = "redis://localhost:6379/0"


def _fake_ip() -> str:
    return f"10.99.{int(uuid.uuid4().hex[:4], 16) % 250}.{int(uuid.uuid4().hex[:4], 16) % 250}"


async def _force_captcha(client, ip: str) -> None:
    """用指定 IP 连输错 2 次，使该 IP 失败计数达到验证码阈值。"""
    for _ in range(2):
        r = await client.post(
            "/api/v1/auth/login",
            json={"username": f"ghost_{uuid.uuid4().hex[:6]}", "password": "wrong-password"},
            headers={"X-Forwarded-For": ip},
        )
        assert r.json()["code"] == 40100


async def _bind_mfa_trainee(client, test_session) -> str:
    """trainee01 登录并完成 MFA 绑定，返回 base32 密钥。"""
    login = await client.post("/api/v1/auth/login", json={"username": "trainee01", "password": "Bt@123456"})
    assert login.json()["code"] == 0
    token = login.json()["data"]["access_token"]
    bind = await client.post("/api/v1/auth/mfa/bind", headers={"Authorization": f"Bearer {token}"})
    assert bind.json()["code"] == 0
    secret = bind.json()["data"]["secret"]
    confirm = await client.post(
        "/api/v1/auth/mfa/bind-confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm.json()["code"] == 0
    return secret


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "no_such_user", "password": "definitely-wrong"},
    )
    body = resp.json()
    assert body["code"] != 0
    assert "用户名或密码错误" in body["message"]


@pytest.mark.asyncio
async def test_login_and_me_flow(client):
    # conftest 已关闭管理员强制 MFA → admin 可直接拿到会话
    resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["user"]["role"] == "admin"
    token = data["access_token"]

    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["username"] == "admin"

    # 清掉 cookie jar 后再访问受保护接口 → 401（无 header 亦无 cookie）
    client.cookies.clear()
    denied = await client.get("/api/v1/users/me")
    assert denied.json()["code"] == 40100


@pytest.mark.asyncio
async def test_trainee_cannot_manage_users(client):
    login = await client.post("/api/v1/auth/login", json={"username": "trainee01", "password": "Bt@123456"})
    assert login.json()["code"] == 0
    token = login.json()["data"]["access_token"]
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "x", "password": "Bt@123456"},
    )
    assert resp.json()["code"] == 40302


# ---------- 图形验证码 ----------

@pytest.mark.asyncio
async def test_captcha_endpoint(client):
    r = await client.get("/api/v1/auth/captcha")
    assert r.json()["code"] == 0
    data = r.json()["data"]
    assert data["captcha_id"]
    assert data["image"].startswith("data:image/svg+xml;base64,")


@pytest.mark.asyncio
async def test_captcha_required_after_failures(client):
    ip = _fake_ip()
    await _force_captcha(client, ip)
    # 密码正确也被验证码拦截
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "manager01", "password": "Bt@123456"},
        headers={"X-Forwarded-For": ip},
    )
    assert r.json()["code"] == 40001
    assert "验证码" in r.json()["message"]


@pytest.mark.asyncio
async def test_captcha_wrong_code(client):
    ip = _fake_ip()
    await _force_captcha(client, ip)
    c = await client.get("/api/v1/auth/captcha")
    cid = c.json()["data"]["captcha_id"]
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "manager01", "password": "Bt@123456", "captcha_id": cid, "captcha_code": "XXXX"},
        headers={"X-Forwarded-For": ip},
    )
    assert r.json()["code"] == 40001
    assert "验证码" in r.json()["message"]
    # 一次性使用：消费后再次提交报过期
    r2 = await client.post(
        "/api/v1/auth/login",
        json={"username": "manager01", "password": "Bt@123456", "captcha_id": cid, "captcha_code": "XXXX"},
        headers={"X-Forwarded-For": ip},
    )
    assert r2.json()["code"] == 40001


@pytest.mark.asyncio
async def test_captcha_correct_code(client):
    ip = _fake_ip()
    await _force_captcha(client, ip)
    c = await client.get("/api/v1/auth/captcha")
    cid = c.json()["data"]["captcha_id"]
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        code = await r.get(f"captcha:{cid}")
    finally:
        await r.aclose()
    assert code
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "manager01", "password": "Bt@123456", "captcha_id": cid, "captcha_code": code},
        headers={"X-Forwarded-For": ip},
    )
    assert resp.json()["code"] == 0


# ---------- MFA（TOTP） ----------

@pytest.mark.asyncio
async def test_mfa_bind_confirm_disable(client, test_session):
    login = await client.post("/api/v1/auth/login", json={"username": "trainee01", "password": "Bt@123456"})
    assert login.json()["code"] == 0
    token = login.json()["data"]["access_token"]
    bind = await client.post("/api/v1/auth/mfa/bind", headers={"Authorization": f"Bearer {token}"})
    assert bind.json()["code"] == 0
    secret = bind.json()["data"]["secret"]
    assert bind.json()["data"]["otpauth_url"].startswith("otpauth://")

    bad = await client.post("/api/v1/auth/mfa/bind-confirm", json={"code": "000000"}, headers={"Authorization": f"Bearer {token}"})
    assert bad.json()["code"] == 40100

    ok = await client.post("/api/v1/auth/mfa/bind-confirm", json={"code": pyotp.TOTP(secret).now()}, headers={"Authorization": f"Bearer {token}"})
    assert ok.json()["code"] == 0
    u = (await test_session.execute(select(User).where(User.username == "trainee01"))).scalar_one()
    assert u.totp_enabled is True

    dis = await client.post("/api/v1/auth/mfa/disable", json={"code": pyotp.TOTP(secret).now()}, headers={"Authorization": f"Bearer {token}"})
    assert dis.json()["code"] == 0
    # identity map：同一会话重新查询同一行会命中缓存实例，需 refresh 拿最新状态
    u2 = (await test_session.execute(select(User).where(User.username == "trainee01"))).scalar_one()
    await test_session.refresh(u2)
    assert u2.totp_enabled is False


@pytest.mark.asyncio
async def test_mfa_two_step_login(client, test_session):
    secret = await _bind_mfa_trainee(client, test_session)
    login = await client.post("/api/v1/auth/login", json={"username": "trainee01", "password": "Bt@123456"})
    assert login.json()["code"] == 0
    data = login.json()["data"]
    assert data["mfa_required"] is True
    assert data["mfa_setup"] is False
    assert data["access_token"] is None
    mfa_token = data["mfa_token"]

    bad = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"})
    assert bad.json()["code"] == 40100

    ok = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
    assert ok.json()["code"] == 0
    assert ok.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_mfa_admin_forced_in_production_logic(client, test_session):
    """管理员强制 MFA 逻辑：临时打开 settings.MFA_FORCE_ROLES 验证 admin 登录要求绑定。"""
    from app.core.config import settings
    saved = settings.MFA_FORCE_ROLES
    settings.MFA_FORCE_ROLES = ["admin"]
    try:
        login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        assert login.json()["code"] == 0
        data = login.json()["data"]
        assert data["mfa_required"] is True
        assert data["mfa_setup"] is True
        assert data["access_token"] is None
    finally:
        settings.MFA_FORCE_ROLES = saved


# ---------- 会话（HttpOnly Cookie + CSRF） ----------

@pytest.mark.asyncio
async def test_session_cookie_and_csrf(client):
    login = await client.post("/api/v1/auth/login", json={"username": "manager01", "password": "Bt@123456"})
    assert login.json()["code"] == 0
    # cookie jar 已自动保存 HttpOnly access/refresh cookie
    me = await client.get("/api/v1/users/me")
    assert me.json()["code"] == 0
    assert me.json()["data"]["username"] == "manager01"

    lst = await client.get("/api/v1/auth/sessions")
    assert lst.json()["code"] == 0
    sid = lst.json()["data"]["items"][0]["id"]
    # Cookie 认证的写操作缺少 CSRF 防护头 → 拒绝
    r = await client.post(f"/api/v1/auth/sessions/{sid}/revoke")
    assert r.json()["code"] == 40302
    # 携带 X-Requested-With → 通过
    r2 = await client.post(f"/api/v1/auth/sessions/{sid}/revoke", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r2.json()["code"] == 0


@pytest.mark.asyncio
async def test_sessions_list_and_current(client):
    login = await client.post("/api/v1/auth/login", json={"username": "auditor01", "password": "Bt@123456"})
    assert login.json()["code"] == 0
    lst = await client.get("/api/v1/auth/sessions")
    assert lst.json()["code"] == 0
    items = lst.json()["data"]["items"]
    assert len(items) >= 1
    assert [i for i in items if i["current"]]
