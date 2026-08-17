"""部门管理集成测试：新增 / 编辑 / 删除 / 权限 / 引用保护 / 审计。"""
import uuid

import pytest
from sqlalchemy import delete, select

from app.core.security import hash_password
from app.models import Department, Device, IPSubnet, OperationLog, User


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def _login(client, username, password="Bt@123456"):
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]["access_token"]


def _uniq_name(prefix="dept"):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _delete_dept(client, token, dept_id):
    """直接删部门（引用保护测试专用；测试自建部门应无引用，可安全删除）。"""
    resp = await client.delete(f"/api/v1/departments/{dept_id}", headers=_h(token))
    return resp.json()


@pytest.mark.asyncio
async def test_permission_roles(client):
    """admin / manager01 可创建；trainee01 / analyst01 被拒（40302）。"""
    admin_t = await _login(client, "admin", "admin123")
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")
    analyst_t = await _login(client, "analyst01")

    names = [_uniq_name(), _uniq_name()]
    created_ids = []
    try:
        for token in (admin_t, manager_t):
            resp = await client.post("/api/v1/departments", headers=_h(token), json={"name": names[len(created_ids)]})
            assert resp.json()["code"] == 0, resp.json()
            created_ids.append(resp.json()["data"]["id"])

        # 学员/分析师对新增、编辑、删除全部 40302
        target = created_ids[0]
        for token in (trainee_t, analyst_t):
            resp = await client.post("/api/v1/departments", headers=_h(token), json={"name": _uniq_name()})
            assert resp.json()["code"] == 40302
            resp = await client.put(f"/api/v1/departments/{target}", headers=_h(token), json={"name": _uniq_name()})
            assert resp.json()["code"] == 40302
            resp = await client.delete(f"/api/v1/departments/{target}", headers=_h(token))
            assert resp.json()["code"] == 40302
    finally:
        for did in created_ids:
            await _delete_dept(client, admin_t, did)


@pytest.mark.asyncio
async def test_create_and_tree(client):
    """创建根部门 + 子部门，tree 结构正确。"""
    admin_t = await _login(client, "admin", "admin123")
    root_name, child_name = _uniq_name("root"), _uniq_name("child")
    root_id = child_id = None
    try:
        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": root_name})
        assert resp.json()["code"] == 0, resp.json()
        root_id = resp.json()["data"]["id"]

        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": child_name, "parent_id": root_id})
        assert resp.json()["code"] == 0, resp.json()
        child_id = resp.json()["data"]["id"]

        tree = (await client.get("/api/v1/departments/tree", headers=_h(admin_t))).json()["data"]
        root = next((d for d in tree if d["id"] == root_id), None)
        assert root is not None
        assert [c["id"] for c in root["children"]] == [child_id]
    finally:
        if child_id:
            await _delete_dept(client, admin_t, child_id)
        if root_id:
            await _delete_dept(client, admin_t, root_id)


@pytest.mark.asyncio
async def test_create_duplicate_name(client):
    """部门名称重复 → 40900。"""
    admin_t = await _login(client, "admin", "admin123")
    name = _uniq_name()
    dept_id = None
    try:
        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": name})
        assert resp.json()["code"] == 0, resp.json()
        dept_id = resp.json()["data"]["id"]
        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": name})
        assert resp.json()["code"] == 40900
    finally:
        if dept_id:
            await _delete_dept(client, admin_t, dept_id)


@pytest.mark.asyncio
async def test_create_invalid_parent_and_manager(client):
    """上级部门不存在 → 40400；主管用户不存在 → 40400。"""
    admin_t = await _login(client, "admin", "admin123")
    resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name(), "parent_id": 99999999})
    assert resp.json()["code"] == 40400
    resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name(), "manager_id": 99999999})
    assert resp.json()["code"] == 40400


@pytest.mark.asyncio
async def test_update_department(client):
    """编辑改名 / 改描述成功；改名撞重名 → 40900。"""
    admin_t = await _login(client, "admin", "admin123")
    dname, ename = _uniq_name(), _uniq_name()
    dept_id = dup_id = None
    try:
        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": dname, "description": "旧描述"})
        assert resp.json()["code"] == 0, resp.json()
        dept_id = resp.json()["data"]["id"]

        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": ename})
        assert resp.json()["code"] == 0, resp.json()
        dup_id = resp.json()["data"]["id"]

        new_name = _uniq_name("renamed")
        resp = await client.put(f"/api/v1/departments/{dept_id}", headers=_h(admin_t), json={"name": new_name, "description": "新描述"})
        assert resp.json()["code"] == 0, resp.json()
        assert resp.json()["data"]["name"] == new_name
        assert resp.json()["data"]["description"] == "新描述"

        # 撞重名
        resp = await client.put(f"/api/v1/departments/{dept_id}", headers=_h(admin_t), json={"name": ename})
        assert resp.json()["code"] == 40900
    finally:
        if dept_id:
            await _delete_dept(client, admin_t, dept_id)
        if dup_id:
            await _delete_dept(client, admin_t, dup_id)


@pytest.mark.asyncio
async def test_update_cycle_detection(client):
    """上级不能是自身或后代（循环引用）→ 40900。"""
    admin_t = await _login(client, "admin", "admin123")
    ids = []
    try:
        root = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name("r")})
        assert root.json()["code"] == 0, root.json()
        root_id = root.json()["data"]["id"]
        ids.append(root_id)

        child = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name("c"), "parent_id": root_id})
        child_id = child.json()["data"]["id"]
        ids.append(child_id)

        grand = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name("g"), "parent_id": child_id})
        grand_id = grand.json()["data"]["id"]
        ids.append(grand_id)

        # 自身 → 拒绝
        resp = await client.put(f"/api/v1/departments/{root_id}", headers=_h(admin_t), json={"parent_id": root_id})
        assert resp.json()["code"] == 40900
        # 后代 → 拒绝
        resp = await client.put(f"/api/v1/departments/{root_id}", headers=_h(admin_t), json={"parent_id": grand_id})
        assert resp.json()["code"] == 40900
    finally:
        for did in sorted(ids, reverse=True):
            await _delete_dept(client, admin_t, did)


@pytest.mark.asyncio
async def test_delete_referenced_department(client, test_session):
    """有子部门/用户/设备/子网引用的部门禁止删除，返回 40900 与计数。"""
    admin_t = await _login(client, "admin", "admin123")
    dept_id = child_id = None
    user_id = device_id = subnet_id = None
    try:
        # 造部门
        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name("p")})
        assert resp.json()["code"] == 0, resp.json()
        dept_id = resp.json()["data"]["id"]

        # 1) 子部门引用
        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name("s"), "parent_id": dept_id})
        assert resp.json()["code"] == 0, resp.json()
        child_id = resp.json()["data"]["id"]
        r = await _delete_dept(client, admin_t, dept_id)
        assert r["code"] == 40900, r
        assert r["data"]["children"] == 1 and r["data"]["users"] == 0

        # 清掉子部门引用，继续测其他引用
        await _delete_dept(client, admin_t, child_id)
        child_id = None

        # 2) 用户引用（直插）
        user = User(username=_uniq_name("u"), password_hash=hash_password("Bt@123456"), department_id=dept_id)
        test_session.add(user)
        await test_session.commit()
        user_id = user.id
        r = await _delete_dept(client, admin_t, dept_id)
        assert r["code"] == 40900 and r["data"]["users"] == 1, r

        # 3) 设备引用（IP 用合法十进制，INET 拒绝十六进制）
        device = Device(name=_uniq_name("dev"), ip_address=f"10.0.98.{uuid.uuid4().int % 200 + 1}",
                        department_id=dept_id)
        test_session.add(device)
        await test_session.commit()
        device_id = device.id
        r = await _delete_dept(client, admin_t, dept_id)
        assert r["code"] == 40900 and r["data"]["devices"] == 1, r

        # 4) IP 子网引用
        subnet = IPSubnet(name=_uniq_name("net"), network="10.199.0.0/24", department_id=dept_id)
        test_session.add(subnet)
        await test_session.commit()
        subnet_id = subnet.id
        r = await _delete_dept(client, admin_t, dept_id)
        assert r["code"] == 40900 and r["data"]["subnets"] == 1, r
    finally:
        # 清理：先删引用者再删部门
        if user_id:
            await test_session.execute(delete(User).where(User.id == user_id))
        if device_id:
            await test_session.execute(delete(Device).where(Device.id == device_id))
        if subnet_id:
            await test_session.execute(delete(IPSubnet).where(IPSubnet.id == subnet_id))
        if child_id:
            await test_session.execute(delete(Department).where(Department.id == child_id))
        if dept_id:
            await test_session.execute(delete(Department).where(Department.id == dept_id))
        await test_session.commit()


@pytest.mark.asyncio
async def test_delete_leaf_department(client):
    """无引用叶子部门可删除。"""
    admin_t = await _login(client, "admin", "admin123")
    resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name("leaf")})
    assert resp.json()["code"] == 0, resp.json()
    dept_id = resp.json()["data"]["id"]

    r = await _delete_dept(client, admin_t, dept_id)
    assert r["code"] == 0, r
    tree = (await client.get("/api/v1/departments/tree", headers=_h(admin_t))).json()["data"]
    assert dept_id not in {d["id"] for d in tree}


@pytest.mark.asyncio
async def test_audit_logs(client, test_session):
    """新增/编辑/删除部门均落审计（department:create/update/delete）。"""
    admin_t = await _login(client, "admin", "admin123")
    dept_id = None
    try:
        resp = await client.post("/api/v1/departments", headers=_h(admin_t), json={"name": _uniq_name("audit")})
        assert resp.json()["code"] == 0, resp.json()
        dept_id = resp.json()["data"]["id"]

        await client.put(f"/api/v1/departments/{dept_id}", headers=_h(admin_t), json={"name": _uniq_name("renamed")})
        await _delete_dept(client, admin_t, dept_id)
        dept_id = None

        logs = (await test_session.execute(
            select(OperationLog).where(OperationLog.action.in_(["department:create", "department:update", "department:delete"]))
        )).scalars().all()
        actions = [l.action for l in logs]
        for expected in ("department:create", "department:update", "department:delete"):
            assert expected in actions, f"缺审计记录 {expected}，现有: {actions}"
        # 全部 target_type 为 department
        assert all(l.target_type == "department" for l in logs)
    finally:
        if dept_id:
            await test_session.execute(delete(Department).where(Department.id == dept_id))
            await test_session.commit()
