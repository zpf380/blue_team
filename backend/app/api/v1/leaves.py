"""考勤 API：休假/外勤申请、审批、取消（申请由定时任务按时间自动生效/恢复）。"""
import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_user_agent, require_permission
from app.core.exceptions import AppError, ERR_CONFLICT, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_VALIDATION, ok_response
from app.db.session import get_db
from app.models import Department, LeaveRequest, Role, User
from app.schemas.common import Page
from app.schemas.leave import LeaveCreate, LeaveReviewIn
from app.services.audit_log import record
from app.services.data_scope import apply_data_scope

router = APIRouter(prefix="/leaves", tags=["考勤管理"])

# 申请在以下状态期间仍占用该时间段（不可重叠再申请）
_ACTIVE_LEAVE_STATUSES = ("pending", "approved", "in_progress")


def _as_utc(d: dt.datetime) -> dt.datetime:
    """归一化时间：无时区的按 UTC 解释（客户端常见），带时区的统一转 UTC。"""
    if d.tzinfo is None:
        return d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def _leave_out(lr: LeaveRequest, users: dict[int, str], depts: dict[int, str], user_dept: dict[int, int]) -> dict:
    """users: id→姓名（申请人与审批人）；depts: id→部门名；user_dept: user_id→department_id。"""
    return {
        "id": lr.id,
        "user_id": lr.user_id,
        "user_name": users.get(lr.user_id),
        "department_name": depts.get(user_dept.get(lr.user_id)),
        "leave_type": lr.leave_type,
        "start_at": lr.start_at,
        "end_at": lr.end_at,
        "reason": lr.reason,
        "status": lr.status,
        "approver_id": lr.approver_id,
        "approver_name": users.get(lr.approver_id) if lr.approver_id else None,
        "reviewed_note": lr.reviewed_note,
        "reviewed_at": lr.reviewed_at,
        "completed_at": lr.completed_at,
        "created_at": lr.created_at,
    }


async def _resolve_default_approver(session: AsyncSession, user: User) -> User | None:
    """解析展示用默认审批人（仅提示，不强制审批归属）：
    1) 本部门主管（Department.manager_id）2) 本部门 manager 角色用户 3) 任一 admin。"""
    active_where = User.status.notin_(("disabled", "archived"))

    # 1) 部门主管
    if user.department_id:
        dept = await session.get(Department, user.department_id)
        if dept and dept.manager_id:
            mgr = await session.get(User, dept.manager_id)
            if mgr and mgr.status not in ("disabled", "archived"):
                return mgr

    # 2) 本部门 manager 角色用户
    manager_role_id = (
        await session.execute(select(Role.id).where(Role.code == "manager").limit(1))
    ).scalar_one_or_none()
    if manager_role_id and user.department_id:
        same_dept = (
            await session.execute(
                select(User)
                .where(User.department_id == user.department_id, User.role_id == manager_role_id)
                .where(active_where)
                .limit(1)
            )
        ).scalar_one_or_none()
        if same_dept:
            return same_dept

    # 3) 任一 admin
    admin_role_id = (
        await session.execute(select(Role.id).where(Role.code == "admin").limit(1))
    ).scalar_one_or_none()
    if admin_role_id:
        admin = (
            await session.execute(
                select(User).where(User.role_id == admin_role_id).where(active_where).limit(1)
            )
        ).scalar_one_or_none()
        if admin:
            return admin
    return None


@router.post("")
async def create_leave(
    data: LeaveCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("leave:apply")),
):
    now = dt.datetime.now(dt.timezone.utc)
    start = _as_utc(data.start_at)
    end = _as_utc(data.end_at)
    if end <= start:
        raise AppError(code=ERR_VALIDATION, message="结束时间必须晚于开始时间")
    if start < now:
        raise AppError(code=ERR_VALIDATION, message="开始时间不能早于当前时间")

    # 时间段重叠冲突：本人已有待审批/生效/已生效未结束的申请占用了该时段
    overlap = (
        await session.execute(
            select(func.count())
            .select_from(LeaveRequest)
            .where(
                LeaveRequest.user_id == user.id,
                LeaveRequest.status.in_(_ACTIVE_LEAVE_STATUSES),
                LeaveRequest.start_at < data.end_at,
                LeaveRequest.end_at > data.start_at,
            )
        )
    ).scalar_one()
    if overlap:
        raise AppError(code=ERR_CONFLICT, message="该时间段已有待审批/生效的休假或外勤申请")

    payload = data.model_dump()
    payload["start_at"] = start
    payload["end_at"] = end
    lr = LeaveRequest(**payload, user_id=user.id)
    session.add(lr)
    await session.flush()
    await record(
        session, user, "leave:apply", target_type="leave_request", target_id=str(lr.id),
        detail={"leave_type": lr.leave_type, "start_at": lr.start_at.isoformat(), "end_at": lr.end_at.isoformat()},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"id": lr.id, "status": lr.status})


@router.get("/mine")
async def my_leaves(
    leave_type: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("leave:apply")),
):
    query = select(LeaveRequest).where(LeaveRequest.user_id == user.id)
    if leave_type:
        query = query.where(LeaveRequest.leave_type == leave_type)
    if status:
        query = query.where(LeaveRequest.status == status)

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(query.order_by(LeaveRequest.id.desc()).offset((page - 1) * size).limit(size))
    ).scalars().all()

    requester = await session.get(User, user.id)
    dept = await session.get(Department, requester.department_id) if requester and requester.department_id else None
    return ok_response(
        data=Page(
            items=[
                _leave_out(
                    lr,
                    {user.id: (requester.real_name or requester.username) if requester else user.username},
                    {dept.id: dept.name} if dept else {},
                    {user.id: dept.id} if dept else {},
                )
                for lr in rows
            ],
            total=total, page=page, size=size,
        )
    )


@router.post("/{leave_id}/cancel")
async def cancel_leave(
    leave_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("leave:apply")),
):
    lr = await session.get(LeaveRequest, leave_id)
    if not lr:
        raise AppError(code=ERR_NOT_FOUND, message="申请不存在")
    if lr.user_id != user.id:
        raise AppError(code=ERR_FORBIDDEN, message="只能取消自己的申请")
    if lr.status != "pending":
        raise AppError(code=ERR_VALIDATION, message="该申请已处理，无法取消")
    lr.status = "cancelled"
    await record(
        session, user, "leave:cancel", target_type="leave_request", target_id=str(leave_id),
        detail={"leave_type": lr.leave_type}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"id": leave_id, "status": lr.status})


@router.get("")
async def list_leaves(
    leave_type: str | None = None,
    status: str = "pending",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("leave:approve")),
):
    # 数据范围：按申请人（LeaveRequest.user_id → User）归属过滤，dept 审批人仅见本部门申请
    query = apply_data_scope(
        select(LeaveRequest).join(User, User.id == LeaveRequest.user_id), user, User
    )
    if leave_type:
        query = query.where(LeaveRequest.leave_type == leave_type)
    if status:
        query = query.where(LeaveRequest.status == status)

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(query.order_by(LeaveRequest.created_at.desc()).offset((page - 1) * size).limit(size))
    ).scalars().all()

    # 批量预取申请人与审批人姓名、所属部门
    id_set = {lr.user_id for lr in rows} | {lr.approver_id for lr in rows if lr.approver_id}
    requester_map: dict[int, User] = {}
    if id_set:
        for u in (await session.execute(select(User).where(User.id.in_(id_set)))).scalars():
            requester_map[u.id] = u
    dept_ids = {u.department_id for u in requester_map.values() if u.department_id}
    dept_map: dict[int, str] = {}
    if dept_ids:
        for d in (await session.execute(select(Department).where(Department.id.in_(dept_ids)))).scalars():
            dept_map[d.id] = d.name

    users = {u.id: (u.real_name or u.username) for u in requester_map.values()}
    user_dept = {u.id: u.department_id for u in requester_map.values()}
    return ok_response(
        data=Page(items=[_leave_out(lr, users, dept_map, user_dept) for lr in rows], total=total, page=page, size=size)
    )


async def _review_workflow(session: AsyncSession, user: User, request: Request, leave_id: int, action: str, note: str | None):
    lr = await session.get(LeaveRequest, leave_id)
    if not lr:
        raise AppError(code=ERR_NOT_FOUND, message="申请不存在")
    if lr.status != "pending":
        raise AppError(code=ERR_VALIDATION, message="该申请已处理")
    if lr.user_id == user.id:
        raise AppError(code=ERR_VALIDATION, message="不能审批自己的申请")

    # 审批数据范围：dept/self 角色不得审批范围外申请（当前仅 admin/manager 可审批，均为 all 范围）
    role = getattr(user, "_role", None)
    scope = role.data_scope if role else "self"
    if scope not in ("all",) and not (role and role.code == "admin"):
        requester = await session.get(User, lr.user_id)
        if scope == "self" and (not requester or requester.id != user.id):
            raise AppError(code=ERR_FORBIDDEN, message="无权审批该申请")
        if scope == "dept" and (not requester or requester.department_id != user.department_id):
            raise AppError(code=ERR_FORBIDDEN, message="无权审批其他部门的申请")

    lr.status = "approved" if action == "approve" else "rejected"
    lr.approver_id = user.id
    lr.reviewed_at = dt.datetime.now(dt.timezone.utc)
    lr.reviewed_note = note
    await record(
        session, user, f"leave:{action}", target_type="leave_request", target_id=str(leave_id),
        detail={"leave_type": lr.leave_type, "status": lr.status, "note": note},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"id": leave_id, "status": lr.status})


@router.post("/{leave_id}/approve")
async def approve_leave(
    leave_id: int,
    request: Request,
    data: LeaveReviewIn | None = None,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("leave:approve")),
):
    return await _review_workflow(session, user, request, leave_id, "approve", data.note if data else None)


@router.post("/{leave_id}/reject")
async def reject_leave(
    leave_id: int,
    request: Request,
    data: LeaveReviewIn | None = None,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("leave:approve")),
):
    return await _review_workflow(session, user, request, leave_id, "reject", data.note if data else None)
