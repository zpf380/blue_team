"""合规审计报告：操作日志聚合统计 + 报告快照生成。"""
import datetime as dt

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditReport, OperationLog

# 合规敏感操作：权限/配置变更、凭证变更、数据导入导出、关键处置
SENSITIVE_ACTIONS = (
    "auth:change_password",
    "user:create",
    "user:update",
    "user:delete",
    "user:import",
    "user:export",
    "role:create",
    "role:update",
    "role:delete",
    "role:grant",
    "ipam:subnet:create",
    "ipam:alloc:create",
    "ipam:alloc:release",
    "monitor:scan:review",
    "training:submit",
)

REPORT_TYPE_LABEL = {"daily": "日报", "weekly": "周报", "monthly": "月报", "on_demand": "按需"}


async def compute_audit_stats(
    session: AsyncSession,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> dict:
    """对操作日志做合规聚合统计，返回可落库快照的 dict。"""
    today = dt.date.today()
    date_from = date_from or (today - dt.timedelta(days=13))
    date_to = date_to or today
    start = dt.datetime.combine(date_from, dt.time.min).astimezone()
    end = dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min).astimezone()

    base = select(OperationLog).where(OperationLog.created_at >= start, OperationLog.created_at < end)

    async def _count(*extra):
        q = base.where(*extra)
        return (await session.execute(select(func.count()).select_from(q.subquery()))).scalar_one()

    total_ops = await _count()
    active_sub = base.where(OperationLog.user_id.is_not(None)).subquery()
    active_users = (
        await session.execute(select(func.count(func.distinct(active_sub.c.user_id))).select_from(active_sub))
    ).scalar_one()
    sensitive_ops = await _count(OperationLog.action.in_(SENSITIVE_ACTIONS))
    logins = await _count(OperationLog.action == "auth:login")

    # 每日趋势（补零）
    trend_map = {
        d: 0
        for d in [
            date_from + dt.timedelta(days=i)
            for i in range((date_to - date_from).days + 1)
        ]
    }
    for day, cnt in (
        await session.execute(
            select(func.date(OperationLog.created_at), func.count())
            .where(OperationLog.created_at >= start, OperationLog.created_at < end)
            .group_by(func.date(OperationLog.created_at))
        )
    ).all():
        trend_map[day] = cnt
    trend = [{"date": d.isoformat(), "count": trend_map[d]} for d in sorted(trend_map)]

    # 操作类型分布（Top 12）
    actions = [
        {"action": a, "count": c}
        for a, c in (
            await session.execute(
                select(OperationLog.action, func.count())
                .where(OperationLog.created_at >= start, OperationLog.created_at < end)
                .group_by(OperationLog.action)
                .order_by(func.count().desc())
                .limit(12)
            )
        ).all()
    ]

    # 用户活跃排行（Top 10）
    users = [
        {"username": u, "role_code": r, "count": c}
        for u, r, c in (
            await session.execute(
                select(OperationLog.username, OperationLog.role_code, func.count())
                .where(OperationLog.created_at >= start, OperationLog.created_at < end)
                .group_by(OperationLog.username, OperationLog.role_code)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
    ]

    # 角色操作分布
    roles = [
        {"role_code": r or "anonymous", "count": c}
        for r, c in (
            await session.execute(
                select(OperationLog.role_code, func.count())
                .where(OperationLog.created_at >= start, OperationLog.created_at < end)
                .group_by(OperationLog.role_code)
                .order_by(func.count().desc())
            )
        ).all()
    ]

    # 近期敏感操作明细
    sensitive = [
        {
            "id": r.id,
            "username": r.username,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "ip_address": str(r.ip_address) if r.ip_address else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in (
            await session.execute(
                select(OperationLog)
                .where(OperationLog.created_at >= start, OperationLog.created_at < end)
                .where(OperationLog.action.in_(SENSITIVE_ACTIONS))
                .order_by(OperationLog.id.desc())
                .limit(20)
            )
        ).scalars()
    ]

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total_ops": total_ops,
        "active_users": active_users,
        "sensitive_ops": sensitive_ops,
        "logins": logins,
        "trend": trend,
        "actions": actions,
        "users": users,
        "roles": roles,
        "sensitive": sensitive,
    }


async def generate_report(
    session: AsyncSession,
    user,
    report_type: str,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> AuditReport:
    """生成并落库一份合规审计报告快照。"""
    stats = await compute_audit_stats(session, date_from, date_to)
    label = REPORT_TYPE_LABEL.get(report_type, report_type)
    report = AuditReport(
        report_type=report_type,
        title=f"{label}合规审计报告（{stats['date_from']} ~ {stats['date_to']}）",
        date_from=dt.date.fromisoformat(stats["date_from"]),
        date_to=dt.date.fromisoformat(stats["date_to"]),
        summary=(
            f"统计周期 {stats['date_from']} ~ {stats['date_to']}：共记录操作 {stats['total_ops']} 次，"
            f"活跃用户 {stats['active_users']} 人，其中敏感操作 {stats['sensitive_ops']} 次、登录 {stats['logins']} 次。"
        ),
        report_data=stats,
        generated_by=user.id,
        generated_by_name=user.real_name or user.username,
    )
    session.add(report)
    return report
