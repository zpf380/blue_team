"""仪表盘统计接口：用户分布 / 部门 / 登录 / 审计概览（登录即可访问）。"""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.exceptions import ok_response
from app.db.session import get_db
from app.models import Department, OperationLog, Role, User

router = APIRouter(prefix="/stats", tags=["统计"])


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    now = dt.datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 用户状态分布
    status_rows = (await session.execute(
        select(User.status, func.count()).group_by(User.status)
    )).all()
    status_map = {s: c for s, c in status_rows}
    users = {
        "total": sum(status_map.values()),
        "active": status_map.get("active", 0),
        "on_leave": status_map.get("on_leave", 0),
        "business_trip": status_map.get("business_trip", 0),
        "disabled": status_map.get("disabled", 0),
        "archived": status_map.get("archived", 0),
    }

    # 角色分布
    role_rows = (await session.execute(
        select(Role.code, Role.name, func.count(User.id))
        .outerjoin(User, User.role_id == Role.id)
        .group_by(Role.id, Role.code, Role.name)
    )).all()
    role_distribution = [{"code": c, "name": n, "count": cnt} for c, n, cnt in role_rows]

    departments = (await session.execute(select(func.count()).select_from(Department))).scalar_one()
    today_logins = (await session.execute(
        select(func.count()).select_from(OperationLog)
        .where(OperationLog.action == "auth:login", OperationLog.created_at >= today_start)
    )).scalar_one()
    ops_logs = (await session.execute(select(func.count()).select_from(OperationLog))).scalar_one()

    return ok_response(data={
        "users": users,
        "role_distribution": role_distribution,
        "departments": departments,
        "today_logins": today_logins,
        "ops_logs": ops_logs,
        "generated_at": now.isoformat(),
    })
