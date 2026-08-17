"""考勤集成测试：休假/外勤申请、审批、取消、权限、定时状态切换。

定时切换测试不依赖真实时钟：直接调用 `_switch_due_leave_statuses` 并注入固定 `now`，
配合手工构造的 start_at/end_at 制造生效/到期场景，完全确定性。
"""
import datetime as dt

import pytest
from sqlalchemy import delete, select, update

from app.models import LeaveRequest, OperationLog, User
from app.services.leave_status import _switch_due_leave_statuses


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def _login(client, username, password="Bt@123456"):
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]["access_token"]


def _iso(days_ahead: int, hours: int = 0) -> str:
    t = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days_ahead, hours=hours))
    t = t.replace(microsecond=0, second=0)
    return t.isoformat()


def _payload(leave_type="on_leave", start=None, end=None, reason="休假测试"):
    return {
        "leave_type": leave_type,
        "start_at": start or _iso(2),
        "end_at": end or _iso(2, hours=24),
        "reason": reason,
    }


async def _cleanup(session, reset_users=()):
    """清空测试申请并恢复指定用户为 active，保证可重复运行。"""
    await session.execute(delete(LeaveRequest))
    if reset_users:
        await session.execute(update(User).where(User.username.in_(reset_users)).values(status="active"))
    await session.commit()


async def _user_id(session, username: str) -> int:
    return (await session.execute(select(User.id).where(User.username == username))).scalar_one()


@pytest.mark.asyncio
async def test_apply_approve_flow(client, test_session):
    await _cleanup(test_session)
    analyst_t = await _login(client, "analyst01")
    manager_t = await _login(client, "manager01")

    resp = await client.post("/api/v1/leaves", json=_payload(), headers=_h(analyst_t))
    assert resp.json()["code"] == 0, resp.json()
    leave_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["status"] == "pending"

    # 审批视角可见待审批申请，审批人未定
    resp = await client.get("/api/v1/leaves", headers=_h(manager_t))
    assert resp.json()["code"] == 0
    items = resp.json()["data"]["items"]
    assert any(i["id"] == leave_id and i["user_name"] == "分析师李" for i in items)

    # manager01 批准
    resp = await client.post(f"/api/v1/leaves/{leave_id}/approve", json={}, headers=_h(manager_t))
    assert resp.json()["code"] == 0, resp.json()
    assert resp.json()["data"]["status"] == "approved"
    mgr_id = await _user_id(test_session, "manager01")
    lr = await test_session.get(LeaveRequest, leave_id)
    assert lr.status == "approved" and lr.approver_id == mgr_id and lr.reviewed_at is not None
    await _cleanup(test_session, reset_users=("analyst01",))


@pytest.mark.asyncio
async def test_leave_validation(client, test_session):
    await _cleanup(test_session)
    analyst_t = await _login(client, "analyst01")

    # 结束早于开始
    resp = await client.post("/api/v1/leaves", json=_payload(start=_iso(2, hours=10), end=_iso(2)), headers=_h(analyst_t))
    assert resp.json()["code"] in (40001, 422)

    # 开始时间在过去
    resp = await client.post("/api/v1/leaves", json=_payload(start=_iso(-1), end=_iso(-1, hours=2)), headers=_h(analyst_t))
    assert resp.json()["code"] == 40001

    # 类型非法
    resp = await client.post("/api/v1/leaves", json=_payload(leave_type="vacation"), headers=_h(analyst_t))
    assert resp.json()["code"] in (40001, 422)
    await _cleanup(test_session, reset_users=("analyst01",))


@pytest.mark.asyncio
async def test_overlap_conflict(client, test_session):
    await _cleanup(test_session)
    analyst_t = await _login(client, "analyst01")

    resp = await client.post("/api/v1/leaves", json=_payload(start=_iso(2), end=_iso(2, hours=24)), headers=_h(analyst_t))
    assert resp.json()["code"] == 0
    # 与上一段重叠（晚 12 小时开始）
    resp = await client.post("/api/v1/leaves", json=_payload(start=_iso(2, hours=12), end=_iso(2, hours=36)), headers=_h(analyst_t))
    assert resp.json()["code"] == 40900
    # 相邻不重叠（紧接上一段结束之后开始）→ 允许
    resp = await client.post("/api/v1/leaves", json=_payload(start=_iso(2, hours=24), end=_iso(2, hours=48)), headers=_h(analyst_t))
    assert resp.json()["code"] == 0
    await _cleanup(test_session, reset_users=("analyst01",))


@pytest.mark.asyncio
async def test_apply_while_on_leave(client, test_session):
    await _cleanup(test_session, reset_users=("trainee01",))
    await test_session.execute(update(User).where(User.username == "trainee01").values(status="on_leave"))
    await test_session.commit()

    trainee_t = await _login(client, "trainee01")
    resp = await client.post("/api/v1/leaves", json=_payload(), headers=_h(trainee_t))
    assert resp.json()["code"] == 0, resp.json()
    await _cleanup(test_session, reset_users=("trainee01",))


@pytest.mark.asyncio
async def test_cancel_flow(client, test_session):
    await _cleanup(test_session)
    analyst_t = await _login(client, "analyst01")
    trainee_t = await _login(client, "trainee01")

    resp = await client.post("/api/v1/leaves", json=_payload(), headers=_h(analyst_t))
    leave_id = resp.json()["data"]["id"]

    # 他人取消 → 越权
    resp = await client.post(f"/api/v1/leaves/{leave_id}/cancel", headers=_h(trainee_t))
    assert resp.json()["code"] == 40301

    # 本人取消成功
    resp = await client.post(f"/api/v1/leaves/{leave_id}/cancel", headers=_h(analyst_t))
    assert resp.json()["code"] == 0 and resp.json()["data"]["status"] == "cancelled"

    # 重复取消 → 已处理
    resp = await client.post(f"/api/v1/leaves/{leave_id}/cancel", headers=_h(analyst_t))
    assert resp.json()["code"] == 40001
    await _cleanup(test_session, reset_users=("analyst01",))


@pytest.mark.asyncio
async def test_review_permissions(client, test_session):
    await _cleanup(test_session)
    analyst_t = await _login(client, "analyst01")
    trainee_t = await _login(client, "trainee01")

    resp = await client.post("/api/v1/leaves", json=_payload(), headers=_h(analyst_t))
    leave_id = resp.json()["data"]["id"]

    # 学员无审批权限
    resp = await client.get("/api/v1/leaves", headers=_h(trainee_t))
    assert resp.json()["code"] == 40302
    resp = await client.post(f"/api/v1/leaves/{leave_id}/approve", json={}, headers=_h(trainee_t))
    assert resp.json()["code"] == 40302
    await _cleanup(test_session, reset_users=("analyst01",))


@pytest.mark.asyncio
async def test_self_review_forbidden(client, test_session):
    await _cleanup(test_session)
    manager_t = await _login(client, "manager01")

    resp = await client.post("/api/v1/leaves", json=_payload(), headers=_h(manager_t))
    assert resp.json()["code"] == 0
    leave_id = resp.json()["data"]["id"]

    # 主管不能审批自己的申请
    resp = await client.post(f"/api/v1/leaves/{leave_id}/approve", json={}, headers=_h(manager_t))
    assert resp.json()["code"] == 40001
    await _cleanup(test_session, reset_users=("manager01",))


@pytest.mark.asyncio
async def test_scheduler_switch(client, test_session):
    await _cleanup(test_session, reset_users=("analyst01",))
    analyst_id = await _user_id(test_session, "analyst01")
    now = dt.datetime.now(dt.timezone.utc)
    past = now - dt.timedelta(hours=1)
    future = now + dt.timedelta(hours=1)

    # 已批准的申请，开始时间已过 → 应生效
    lr = LeaveRequest(user_id=analyst_id, leave_type="on_leave", start_at=past, end_at=future, status="approved", reason="定时切换测试")
    test_session.add(lr)
    await test_session.commit()

    started, ended = await _switch_due_leave_statuses(test_session, now=now)
    assert (started, ended) == (1, 0)
    u = await test_session.get(User, analyst_id)
    assert u.status == "on_leave"
    lr = await test_session.get(LeaveRequest, lr.id)
    assert lr.status == "in_progress"

    # 结束时间已过 → 应恢复 active
    lr.end_at = past
    await test_session.commit()
    started, ended = await _switch_due_leave_statuses(test_session, now=now)
    assert (started, ended) == (0, 1)
    u = await test_session.get(User, analyst_id)
    assert u.status == "active"
    lr = await test_session.get(LeaveRequest, lr.id)
    assert lr.status == "completed" and lr.completed_at is not None

    await _cleanup(test_session, reset_users=("analyst01",))


@pytest.mark.asyncio
async def test_scheduler_not_overwrite(client, test_session):
    await _cleanup(test_session, reset_users=("trainee01",))
    trainee_id = await _user_id(test_session, "trainee01")
    now = dt.datetime.now(dt.timezone.utc)
    past = now - dt.timedelta(hours=1)

    # 用户已归档：到期开始不生效
    await test_session.execute(update(User).where(User.id == trainee_id).values(status="archived"))
    lr = LeaveRequest(user_id=trainee_id, leave_type="business_trip", start_at=past, end_at=now + dt.timedelta(days=1), status="approved")
    test_session.add(lr)
    await test_session.commit()

    started, ended = await _switch_due_leave_statuses(test_session, now=now)
    assert (started, ended) == (0, 0)
    u = await test_session.get(User, trainee_id)
    assert u.status == "archived"
    lr = await test_session.get(LeaveRequest, lr.id)
    assert lr.status == "approved"

    # 生效中 + 用户被禁用：到期恢复不覆盖禁用
    u.status = "business_trip"
    lr.status = "in_progress"
    lr.end_at = past
    await test_session.commit()
    await test_session.execute(update(User).where(User.id == trainee_id).values(status="disabled"))
    await test_session.commit()
    started, ended = await _switch_due_leave_statuses(test_session, now=now)
    assert (started, ended) == (0, 0)
    u = await test_session.get(User, trainee_id)
    assert u.status == "disabled"
    lr = await test_session.get(LeaveRequest, lr.id)
    assert lr.status == "in_progress"

    await _cleanup(test_session, reset_users=("trainee01",))


@pytest.mark.asyncio
async def test_audit_logs(client, test_session):
    # 注意：operation_logs 有 prevent_delete/update 防篡改规则（审计合规），无法清理，
    # 因此只断言「本次创建的申请都留有对应动作」，不要求精确等于全部记录。
    await _cleanup(test_session)
    analyst_t = await _login(client, "analyst01")
    manager_t = await _login(client, "manager01")

    # apply → cancel
    resp = await client.post("/api/v1/leaves", json=_payload(), headers=_h(analyst_t))
    apply_id = resp.json()["data"]["id"]
    await client.post(f"/api/v1/leaves/{apply_id}/cancel", headers=_h(analyst_t))

    # apply → approve
    resp = await client.post("/api/v1/leaves", json=_payload(), headers=_h(analyst_t))
    approve_id = resp.json()["data"]["id"]
    await client.post(f"/api/v1/leaves/{approve_id}/approve", json={"note": "同意"}, headers=_h(manager_t))

    # apply → reject（用不同时间段，避免与已批准的申请重叠冲突）
    resp = await client.post(
        "/api/v1/leaves",
        json=_payload(leave_type="business_trip", start=_iso(5), end=_iso(5, hours=24)),
        headers=_h(analyst_t),
    )
    assert resp.json()["code"] == 0, resp.json()
    reject_id = resp.json()["data"]["id"]
    await client.post(f"/api/v1/leaves/{reject_id}/reject", json={"note": "人力不足"}, headers=_h(manager_t))

    rows = (await test_session.execute(
        select(OperationLog).where(OperationLog.target_type == "leave_request")
    )).scalars().all()
    actions = {r.action for r in rows}
    assert {"leave:apply", "leave:cancel", "leave:approve", "leave:reject"} <= actions
    # 审计目标 ID 覆盖本次三个申请（历史累积记录不影响子集断言）
    ids = {r.target_id for r in rows}
    assert {str(apply_id), str(approve_id), str(reject_id)} <= ids
    await _cleanup(test_session, reset_users=("analyst01",))
