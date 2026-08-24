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
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-Requested-With": "XMLHttpRequest"},
            json={"refresh_token": refresh_token},
        )
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


@pytest.mark.asyncio
async def test_delete_user_ref_protection(client, test_session):
    """删除引用保护（对齐部门 409 模式）：无引用的用户物理删除；被业务数据引用的用户 409+明细。"""
    from sqlalchemy import delete, select

    from app.models import Device, User

    admin = await _login(client, "admin", "admin123")
    tok = admin["access_token"]

    # 无引用、无审计日志的新用户 → 物理删除
    clean = await _create_user(client, tok, f"cln_{uuid.uuid4().hex[:8]}", "analyst")
    resp = await client.delete(f"/api/v1/users/{clean['id']}", headers=_h(tok))
    assert resp.json()["code"] == 0, resp.json()
    assert resp.json()["data"]["action"] == "deleted"

    # 被设备引用（owner_id）且无审计日志 → 409 + refs 明细，不再裸 500
    owned = await _create_user(client, tok, f"own_{uuid.uuid4().hex[:8]}", "analyst")
    dev_ip = f"10.9.{int(uuid.uuid4().hex[:4], 16) % 200 + 1}.7"
    resp = await client.post("/api/v1/monitor/devices", headers=_h(tok), json={
        "name": f"ref-{owned['id']}", "ip_address": dev_ip, "device_type": "server",
        "owner_id": owned["id"],
    })
    assert resp.json()["code"] == 0, resp.json()
    dev_id = resp.json()["data"]["id"]
    try:
        resp = await client.delete(f"/api/v1/users/{owned['id']}", headers=_h(tok))
        assert resp.json()["code"] == 40900, resp.json()
        assert resp.json()["data"]["devices"] >= 1
        # 清理引用后即可删除
        await test_session.execute(delete(Device).where(Device.id == dev_id))
        await test_session.commit()
        resp = await client.delete(f"/api/v1/users/{owned['id']}", headers=_h(tok))
        assert resp.json()["code"] == 0, resp.json()
    finally:
        await test_session.execute(delete(Device).where(Device.id == dev_id))
        await test_session.commit()
        (await test_session.execute(delete(User).where(User.id == owned["id"]))).rowcount
        await test_session.commit()


@pytest.mark.asyncio
async def test_workspace_stats_per_role(client):
    """角色工作台聚合接口：各角色返回对应统计字段，且不越权返回其他角色数据。"""
    cases = {
        "manager01": {"pending_reports", "unresolved_alerts", "pending_leaves", "training_top", "compliance"},
        "analyst01": {"open_alerts", "dept_alerts", "my_devices", "ai_conversations"},
        "trainee01": {"total_score", "badges", "completed_scenarios", "learning_days_30d"},
        "auditor01": {"today_ops", "anomalies", "compliance", "pending_reviews"},
    }
    for username, expected_keys in cases.items():
        d = await _login(client, username, "Bt@123456")
        resp = await client.get("/api/v1/stats/workspace", headers=_h(d["access_token"]))
        body = resp.json()
        assert body["code"] == 0, body
        data = body["data"]
        assert data["role"] == username.rstrip("01")
        assert set(data["stats"].keys()) == expected_keys, (username, data["stats"].keys())


@pytest.mark.asyncio
async def test_user_fk_validation(client):
    """外键存在性校验（批次3）：role_id / department_id 引用不存在 → 40400，不再裸 500。"""
    admin = await _login(client, "admin", "admin123")
    tok = admin["access_token"]

    # 创建用户时 role_id 不存在 → 40400
    resp = await client.post("/api/v1/users", headers=_h(tok), json={
        "username": f"fk_{uuid.uuid4().hex[:8]}", "password": "Bt@123456", "role_id": 999999,
    })
    assert resp.json()["code"] == 40400, resp.json()
    assert "角色不存在" in resp.json()["message"]

    # 更新用户时 department_id 不存在 → 40400
    name = f"fkd_{uuid.uuid4().hex[:8]}"
    tmp = await _create_user(client, tok, name, "analyst")
    try:
        resp = await client.put(f"/api/v1/users/{tmp['id']}", headers=_h(tok), json={"department_id": 999999})
        assert resp.json()["code"] == 40400, resp.json()
        assert "部门不存在" in resp.json()["message"]
    finally:
        await client.delete(f"/api/v1/users/{tmp['id']}", headers=_h(tok))


@pytest.mark.asyncio
async def test_pagination_size_boundaries(client):
    """分页 size 治理（批次3）：越界 size 由 FastAPI 校验拒绝（422 + 40001），含 size=-1。"""
    admin = await _login(client, "admin", "admin123")
    tok = admin["access_token"]

    for url, params in [
        ("/api/v1/users", {"size": 101}),
        ("/api/v1/users", {"size": 0}),
        ("/api/v1/users", {"page": 0}),
        ("/api/v1/audit/reports", {"size": 1000}),
        ("/api/v1/audit/logs", {"size": -1}),
    ]:
        resp = await client.get(url, headers=_h(tok), params=params)
        assert resp.status_code == 422, (url, params, resp.status_code)
        assert resp.json()["code"] == 40001, (url, params, resp.json())

    # 请假列表（leave:apply 权限，trainee01 可用）
    trainee = await _login(client, "trainee01", "Bt@123456")
    resp = await client.get("/api/v1/leaves/mine", headers=_h(trainee["access_token"]), params={"size": 200})
    assert resp.status_code == 422 and resp.json()["code"] == 40001
    # 审批列表（manager01）
    manager = await _login(client, "manager01", "Bt@123456")
    resp = await client.get("/api/v1/leaves", headers=_h(manager["access_token"]), params={"size": -1})
    assert resp.status_code == 422 and resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_import_users_corrupted_xlsx(client):
    """批量导入兜底（批次3）：损坏的 .xlsx 返回 40001 而非 500。"""
    admin = await _login(client, "admin", "admin123")
    resp = await client.post(
        "/api/v1/users/import",
        headers=_h(admin["access_token"]),
        files={"file": ("users.xlsx", b"\x50\x4b\x03\x04 broken-not-zip", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.json()["code"] == 40001, resp.json()
    assert "解析失败" in resp.json()["message"]
