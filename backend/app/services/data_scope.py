"""数据范围过滤：all / sub_dept / dept / self 四档。

- admin 角色 data_scope 恒为 all。
- 具体模型需具备 department_id 或 owner_id 列；`self` 档对 users 使用 id 列。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ERR_VALIDATION
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
            # sub_dept 档位未启用（无角色使用），业务报错而非裸 500
            raise AppError(code=ERR_VALIDATION, message="sub_dept 数据范围未启用（预留功能，请联系管理员配置）")
        return query
    return query


def apply_device_data_scope(query, user: User, model) -> object:
    """对经 device_id 归属设备的模型（Alert/ScanReport）做数据范围过滤。

    Alert/ScanReport 无 department_id/owner_id 列，只能外连 Device 后按设备归属过滤：
    - all / admin：不变
    - dept：Device.department_id == user.department_id（外连自然排除无设备关联的全局记录）
    - self：Device.owner_id == user.id
    - sub_dept：未启用（无角色使用，命中 raise）
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
        raise AppError(code=ERR_VALIDATION, message="sub_dept 数据范围未启用（预留功能，请联系管理员配置）")
    if scope == "dept":
        return query.where(Device.department_id == user.department_id)
    return query
