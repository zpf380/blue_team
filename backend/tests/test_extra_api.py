"""M1 细节补齐接口的集成测试：roles / 修改密码 / 自我保护 / 统计 / 审计时间过滤。"""
import uuid

import pytest


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def _login(client, username, password):
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]


async def _create_user(client, admin_token, username, role_code, password="Bt@123456"):
    roles = (await client.get("/api/v1/roles", headers=_h(admin_token))).json()["data"]
    role_id = next(r["id"] for r in roles if r["code"] == role_code)
    resp = await client.post(
        "/api/v1/users",
        headers=_h(admin_token),
        json={"username": username, "password": password, "role_id": role_id},
    )
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_roles_list(client):
    d = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/roles", headers=_h(d["access_token"]))
    body = resp.json()
    assert body["code"] == 0
    assert {r["code"] for r in body["data"]} == {"admin", "manager", "analyst", "trainee", "auditor"}


@pytest.mark.asyncio
async def test_change_password_revokes_refresh(client):
    admin = await _login(client, "admin", "admin123")
    name = f"pw_{uuid.uuid4().hex[:8]}"
    tmp = await _create_user(client, admin["access_token"], name, "trainee")
    uid = tmp["id"]
    try:
        login = await _login(client, name, "Bt@123456")
        refresh_token = login["refresh_token"]

        # 原密码错误 → 拒绝
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=_h(login["access_token"]),
            json={"old_password": "WrongPass1", "new_password": "NewPass123"},
        )
        assert resp.json()["code"] == 40100

        # 修改成功
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=_h(login["access_token"]),
            json={"old_password": "Bt@123456", "new_password": "NewPass123"},
        )
        assert resp.json()["code"] == 0

        # 旧刷新令牌已吊销
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.json()["code"] == 40100

        # 新密码可登录
        await _login(client, name, "NewPass123")
    finally:
        await client.delete(f"/api/v1/users/{uid}", headers=_h(admin["access_token"]))


@pytest.mark.asyncio
async def test_admin_self_protection(client):
    d = await _login(client, "admin", "admin123")
    token = d["access_token"]
    me = (await client.get("/api/v1/users/me", headers=_h(token))).json()["data"]
    uid = me["id"]
    # 不能禁用自己
    resp = await client.put(f"/api/v1/users/{uid}", headers=_h(token), json={"status": "disabled"})
    assert resp.json()["code"] != 0
    # 不能删除自己
    resp = await client.delete(f"/api/v1/users/{uid}", headers=_h(token))
    assert resp.json()["code"] != 0


@pytest.mark.asyncio
async def test_last_admin_protection(client):
    """系统始终保留至少一名有效管理员：第二管理员可降级第一名，但不能自降级/自禁用。"""
    admin = await _login(client, "admin", "admin123")
    name = f"admin_{uuid.uuid4().hex[:6]}"
    second = await _create_user(client, admin["access_token"], name, "admin")
    uid = second["id"]
    try:
        admin2 = await _login(client, name, "Bt@123456")
        me_admin = (await client.get("/api/v1/users/me", headers=_h(admin["access_token"]))).json()["data"]

        roles = (await client.get("/api/v1/roles", headers=_h(admin2["access_token"]))).json()["data"]
        manager_role_id = next(r["id"] for r in roles if r["code"] == "manager")
        admin_role_id = next(r["id"] for r in roles if r["code"] == "admin")

        # 第二名管理员把第一名降级为 manager → 仍剩 1 名管理员，允许
        resp = await client.put(
            f"/api/v1/users/{me_admin['id']}",
            headers=_h(admin2["access_token"]),
            json={"role_id": manager_role_id},
        )
        assert resp.json()["code"] == 0

        # 恢复第一名
        resp = await client.put(
            f"/api/v1/users/{me_admin['id']}",
            headers=_h(admin2["access_token"]),
            json={"role_id": admin_role_id},
        )
        assert resp.json()["code"] == 0

        # 但 admin2 不能自降级 / 自禁用（自我保护）
        resp = await client.put(
            f"/api/v1/users/{uid}",
            headers=_h(admin2["access_token"]),
            json={"role_id": manager_role_id},
        )
        assert resp.json()["code"] != 0
        resp = await client.put(
            f"/api/v1/users/{uid}",
            headers=_h(admin2["access_token"]),
            json={"status": "disabled"},
        )
        assert resp.json()["code"] != 0
    finally:
        admin_again = await _login(client, "admin", "admin123")
        await client.delete(f"/api/v1/users/{uid}", headers=_h(admin_again["access_token"]))


@pytest.mark.asyncio
async def test_stats_overview(client):
    d = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/stats/overview", headers=_h(d["access_token"]))
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert "users" in data and "role_distribution" in data and "departments" in data
    assert data["users"]["total"] >= 1


@pytest.mark.asyncio
async def test_audit_date_filter(client):
    d = await _login(client, "admin", "admin123")
    resp = await client.get(
        "/api/v1/audit/logs",
        headers=_h(d["access_token"]),
        params={"date_from": "2000-01-01", "date_to": "2000-01-02"},
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["total"] == 0


@pytest.mark.asyncio
async def test_unknown_route_maps_to_404(client):
    """未知路径/方法应返回 40400（资源不存在），而非 50000（内部错误）。"""
    resp = await client.get("/api/v1/auth/me")
    body = resp.json()
    assert resp.status_code == 404
    assert body["code"] == 40400

    resp = await client.put("/api/v1/auth/me")
    body = resp.json()
    assert resp.status_code == 404
    assert body["code"] == 40400
