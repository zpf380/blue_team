"""仪表盘统计接口：用户分布 / 部门 / 登录 / 审计概览（登录即可访问）。"""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.exceptions import ok_response
from app.db.session import get_db
from app.models import (
    AIConversation, Alert, Department, Device, LeaveRequest, OperationLog, Role, ScanReport,
    ScoreRecord, TrainingProgress, User, UserBadge,
)
from app.services.data_scope import apply_device_data_scope

router = APIRouter(prefix="/stats", tags=["统计"])


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    now = dt.datetime.now(dt.timezone.utc)
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


async def _count(session: AsyncSession, model, *conds) -> int:
    return (await session.execute(select(func.count()).select_from(model).where(*conds))).scalar_one()


@router.get("/workspace")
async def workspace(session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """角色工作台聚合数据：按当前用户角色返回对应首页卡片统计。

    - manager：待审扫描报告 / 高危未解决告警 / 待审假条 / 团队训练排行 Top5
    - analyst：本部门待处理告警 / 负责设备 / 本部门告警总量 / AI 会话数
    - trainee：能力综合分 / 徽章数 / 完成场景 / 近 30 天学习天数
    - auditor：今日操作 / 近 7 天锁定（暴力破解）事件 / 报告合规评分 / 待核查报告
    """
    role = getattr(user, "_role", None)
    role_code = role.code if role else ""
    uid = user.id
    now = dt.datetime.now(dt.timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - dt.timedelta(days=7)

    stats: dict = {}
    if role_code == "manager":
        approved = await _count(session, ScanReport, ScanReport.status == "approved")
        rejected = await _count(session, ScanReport, ScanReport.status == "rejected")
        stats = {
            "pending_reports": await _count(session, ScanReport, ScanReport.status == "pending_review"),
            "unresolved_alerts": await _count(
                session, Alert,
                Alert.status.in_(("open", "acknowledged")), Alert.severity.in_(("critical", "high")),
            ),
            "pending_leaves": await _count(session, LeaveRequest, LeaveRequest.status == "pending"),
            "compliance": int(approved * 100 / (approved + rejected)) if (approved + rejected) else None,
            "training_top": [
                {"name": (u.real_name or u.username), "score": int(total)}
                for u, total in (await session.execute(
                    select(User, func.sum(ScoreRecord.points).label("total"))
                    .join(ScoreRecord, ScoreRecord.user_id == User.id)
                    .group_by(User.id).order_by(func.sum(ScoreRecord.points).desc()).limit(5)
                )).all()
            ],
        }
    elif role_code == "analyst":
        scope_query = apply_device_data_scope(select(Alert), user, Alert)
        stats = {
            "open_alerts": (await session.execute(
                select(func.count()).select_from(scope_query.where(Alert.status == "open").subquery())
            )).scalar_one(),
            "dept_alerts": (await session.execute(
                select(func.count()).select_from(scope_query.where(Alert.status.in_(("open", "acknowledged"))).subquery())
            )).scalar_one(),
            "my_devices": await _count(session, Device, Device.owner_id == uid),
            "ai_conversations": await _count(session, AIConversation, AIConversation.user_id == uid),
        }
    elif role_code == "trainee":
        total_score = (await session.execute(
            select(func.coalesce(func.sum(ScoreRecord.points), 0)).where(ScoreRecord.user_id == uid)
        )).scalar_one()
        stats = {
            "total_score": int(total_score),
            "badges": await _count(session, UserBadge, UserBadge.user_id == uid),
            "completed_scenarios": await _count(
                session, TrainingProgress, TrainingProgress.user_id == uid, TrainingProgress.status == "completed",
            ),
            "learning_days_30d": (await session.execute(
                select(func.count(func.distinct(func.date(ScoreRecord.created_at))))
                .where(ScoreRecord.user_id == uid, ScoreRecord.created_at >= week_start)
            )).scalar_one(),
        }
    elif role_code == "auditor":
        approved = await _count(session, ScanReport, ScanReport.status == "approved")
        rejected = await _count(session, ScanReport, ScanReport.status == "rejected")
        stats = {
            "today_ops": await _count(session, OperationLog, OperationLog.created_at >= today_start),
            "anomalies": await _count(session, OperationLog, OperationLog.action == "auth:lock", OperationLog.created_at >= week_start),
            "compliance": int(approved * 100 / (approved + rejected)) if (approved + rejected) else None,
            "pending_reviews": await _count(session, ScanReport, ScanReport.status == "pending_review"),
        }
    return ok_response(data={"role": role_code, "stats": stats})
