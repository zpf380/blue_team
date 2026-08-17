"""审计中心集成测试：合规报告统计 / 权限 / 生成 / 详情 / 导出。"""
import pytest


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def _login(client, username, password="Bt@123456"):
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_audit_stats_structure(client):
    auditor_t = await _login(client, "auditor01")
    resp = await client.get("/api/v1/audit/reports/stats", headers=_h(auditor_t))
    assert resp.json()["code"] == 0, resp.json()
    data = resp.json()["data"]
    # 结构完整性
    for key in ("total_ops", "active_users", "sensitive_ops", "logins", "trend", "actions", "users", "roles", "sensitive"):
        assert key in data, f"缺失字段 {key}"
    assert isinstance(data["total_ops"], int) and data["total_ops"] >= 0
    assert isinstance(data["trend"], list) and len(data["trend"]) == 14  # 默认近 14 天
    assert all({"date", "count"} <= set(d.keys()) for d in data["trend"])


@pytest.mark.asyncio
async def test_audit_report_permissions(client):
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")

    # manager / trainee 均无审计中心权限
    resp = await client.get("/api/v1/audit/reports/stats", headers=_h(manager_t))
    assert resp.json()["code"] == 40302
    resp = await client.post("/api/v1/audit/reports", headers=_h(trainee_t), json={"report_type": "on_demand"})
    assert resp.json()["code"] == 40302


@pytest.mark.asyncio
async def test_audit_report_lifecycle(client):
    auditor_t = await _login(client, "auditor01")

    # 生成报告（指定周期）
    resp = await client.post("/api/v1/audit/reports", headers=_h(auditor_t), json={
        "report_type": "weekly", "date_from": "2026-08-01", "date_to": "2026-08-14",
    })
    assert resp.json()["code"] == 0, resp.json()
    report_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["title"]

    # 列表包含
    resp = await client.get("/api/v1/audit/reports", headers=_h(auditor_t))
    assert any(r["id"] == report_id for r in resp.json()["data"]["items"])

    # 详情含快照数据
    resp = await client.get(f"/api/v1/audit/reports/{report_id}", headers=_h(auditor_t))
    detail = resp.json()["data"]
    assert isinstance(detail["report_data"]["total_ops"], int)
    assert detail["report_data"]["date_from"] == "2026-08-01"
    assert detail["date_from"] == "2026-08-01"

    # 导出 CSV
    resp = await client.get(f"/api/v1/audit/reports/{report_id}/export", headers=_h(auditor_t))
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "总操作数" in resp.text
    assert resp.headers["content-disposition"].startswith("attachment; filename=audit_report_")

    # 不存在的报告
    resp = await client.get("/api/v1/audit/reports/999999", headers=_h(auditor_t))
    assert resp.json()["code"] == 40400
