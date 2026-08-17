"""组织架构接口：树查询 + 部门新增/编辑/删除。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_current_user, get_user_agent, require_role
from app.core.exceptions import AppError, ERR_CONFLICT, ERR_NOT_FOUND, ok_response
from app.db.session import get_db
from app.models import Department, Device, IPSubnet, User
from app.schemas.user import DepartmentCreate, DepartmentOut, DepartmentTreeNode, DepartmentUpdate
from app.services.audit_log import record
from app.services.data_scope import get_sub_department_ids

router = APIRouter(prefix="/departments", tags=["组织架构"])


@router.get("/tree")
async def department_tree(session: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await session.execute(select(Department).order_by(Department.id))).scalars().all()
    nodes = {d.id: DepartmentTreeNode(id=d.id, name=d.name, parent_id=d.parent_id, manager_id=d.manager_id, description=d.description, children=[]) for d in rows}
    roots: list[DepartmentTreeNode] = []
    for d in rows:
        node = nodes[d.id]
        if d.parent_id and d.parent_id in nodes:
            nodes[d.parent_id].children.append(node)
        else:
            roots.append(node)
    return ok_response(data=roots)


@router.post("")
async def create_department(
    data: DepartmentCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(require_role(["admin", "manager"])),
):
    # 防重名（DB 无 unique 约束，应用层校验）
    if (await session.execute(select(Department).where(Department.name == data.name))).scalar_one_or_none():
        raise AppError(code=ERR_CONFLICT, message="部门名称已存在")
    if data.parent_id and not await session.get(Department, data.parent_id):
        raise AppError(code=ERR_NOT_FOUND, message="上级部门不存在")
    if data.manager_id and not await session.get(User, data.manager_id):
        raise AppError(code=ERR_NOT_FOUND, message="主管用户不存在")
    dept = Department(
        name=data.name,
        parent_id=data.parent_id,
        manager_id=data.manager_id,
        description=data.description,
    )
    session.add(dept)
    await session.flush()
    await record(
        session, current, "department:create", target_type="department", target_id=str(dept.id),
        detail={"name": dept.name}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data=DepartmentOut.model_validate(dept))


@router.put("/{dept_id}")
async def update_department(
    dept_id: int,
    data: DepartmentUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(require_role(["admin", "manager"])),
):
    dept = await session.get(Department, dept_id)
    if not dept:
        raise AppError(code=ERR_NOT_FOUND, message="部门不存在")
    fields = data.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"] != dept.name:
        dup = (await session.execute(
            select(Department).where(Department.name == fields["name"], Department.id != dept_id)
        )).scalar_one_or_none()
        if dup:
            raise AppError(code=ERR_CONFLICT, message="部门名称已存在")

    if "parent_id" in fields and fields["parent_id"] is not None:
        new_parent = await session.get(Department, fields["parent_id"])
        if not new_parent:
            raise AppError(code=ERR_NOT_FOUND, message="上级部门不存在")
        # 循环检测：不能把自己设为自己的后代（get_sub_department_ids 含自身）
        if fields["parent_id"] in await get_sub_department_ids(session, dept_id):
            raise AppError(code=ERR_CONFLICT, message="上级部门不能是自身或其后代")

    if "manager_id" in fields and fields["manager_id"]:
        if not await session.get(User, fields["manager_id"]):
            raise AppError(code=ERR_NOT_FOUND, message="主管用户不存在")

    for k, v in fields.items():
        setattr(dept, k, v)
    await record(
        session, current, "department:update", target_type="department", target_id=str(dept_id),
        detail={"fields": list(fields.keys())}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data=DepartmentOut.model_validate(dept))


@router.delete("/{dept_id}")
async def delete_department(
    dept_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(require_role(["admin", "manager"])),
):
    dept = await session.get(Department, dept_id)
    if not dept:
        raise AppError(code=ERR_NOT_FOUND, message="部门不存在")
    refs = {
        "children": (await session.execute(select(func.count()).select_from(Department).where(Department.parent_id == dept_id))).scalar_one(),
        "users": (await session.execute(select(func.count()).select_from(User).where(User.department_id == dept_id))).scalar_one(),
        "devices": (await session.execute(select(func.count()).select_from(Device).where(Device.department_id == dept_id))).scalar_one(),
        "subnets": (await session.execute(select(func.count()).select_from(IPSubnet).where(IPSubnet.department_id == dept_id))).scalar_one(),
    }
    if sum(refs.values()) > 0:
        raise AppError(code=ERR_CONFLICT, message=(
            f"该部门已被引用（{refs['children']} 个子部门 / {refs['users']} 名用户 / "
            f"{refs['devices']} 台设备 / {refs['subnets']} 个子网），无法删除"), data=refs)
    await record(
        session, current, "department:delete", target_type="department", target_id=str(dept_id),
        detail={"name": dept.name}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.delete(dept)
    await session.commit()
    return ok_response(data={"deleted": dept_id})
