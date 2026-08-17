"""数据范围过滤：all / sub_dept / dept / self 四档。

- admin 角色 data_scope 恒为 all。
- 具体模型需具备 department_id 或 owner_id 列；`self` 档对 users 使用 id 列。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, Device, Role, User


async def get_sub_department_ids(session: AsyncSession, dept_id: int) -> list[int]:
    """递归收集某部门及其全部子部门 id。"""
    result = [dept_id]
    queue = [dept_id]
    seen = {dept_id}
    while queue:
        parent = queue.pop(0)
        rows = (await session.execute(select(Department.id).where(Department.parent_id == parent))).scalars().all()
        for rid in rows:
            if rid not in seen:
                seen.add(rid)
                result.append(rid)
                queue.append(rid)
    return result


def apply_data_scope(query, user: User, model) -> object:
    """对查询追加数据范围条件（返回新 query）。模型需有 department_id / owner_id / id。"""
    role: Role | None = getattr(user, "_role", None)
    scope = role.data_scope if role else "self"
    role_code = role.code if role else ""

    if scope == "all" or role_code == "admin":
        return query
    if scope == "self":
        if hasattr(model, "owner_id"):
            return query.where(model.owner_id == user.id)
        return query.where(model.id == user.id)
    if scope == "dept":
        if hasattr(model, "department_id"):
            return query.where(model.department_id == user.department_id)
        return query
    if scope == "sub_dept":
        if hasattr(model, "department_id"):
            # 传入 session 做递归时由调用方先算好 ids
            raise ValueError("sub_dept 需调用 apply_data_scope_sub_dept")
        return query
    return query


def apply_data_scope_sub_dept(query, user: User, model, sub_dept_ids: list[int]):
    if hasattr(model, "department_id"):
        return query.where(model.department_id.in_(sub_dept_ids))
    return query


def apply_device_data_scope(query, user: User, model) -> object:
    """对经 device_id 归属设备的模型（Alert/ScanReport）做数据范围过滤。

    Alert/ScanReport 无 department_id/owner_id 列，只能外连 Device 后按设备归属过滤：
    - all / admin：不变
    - dept：Device.department_id == user.department_id（外连自然排除无设备关联的全局记录）
    - self：Device.owner_id == user.id
    - sub_dept：需先算好 ids 调用 apply_device_data_scope_sub_dept
    """
    role: Role | None = getattr(user, "_role", None)
    scope = role.data_scope if role else "self"
    role_code = role.code if role else ""

    if scope == "all" or role_code == "admin":
        return query
    query = query.outerjoin(Device, Device.id == model.device_id)
    if scope == "self":
        return query.where(Device.owner_id == user.id)
    if scope == "sub_dept":
        raise ValueError("sub_dept 需调用 apply_device_data_scope_sub_dept")
    if scope == "dept":
        return query.where(Device.department_id == user.department_id)
    return query


def apply_device_data_scope_sub_dept(query, user: User, model, sub_dept_ids: list[int]):
    return query.outerjoin(Device, Device.id == model.device_id).where(Device.department_id.in_(sub_dept_ids))
