"""休假/外勤状态自动切换（后台定时任务调用）。

规则：
- 已生效且到期（in_progress 且 end_at<=now）：仅当用户当前状态恰为该申请的 leave_type 时，
  恢复 active 并标记申请 completed（用户被管理员改成 disabled/archived/其他 → 不覆盖，
  申请停留 in_progress 作为历史）。
- 已批准且到开始时间（approved 且 start_at<=now）：仅当用户当前为 active 时切换为该
  leave_type 并标记 in_progress。
- 先结束再开始，保证「上一段结束后紧接下一段开始」在同一个轮次内完成衔接。
"""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeaveRequest, User


async def _switch_due_leave_statuses(
    session: AsyncSession, now: dt.datetime | None = None
) -> tuple[int, int]:
    """切换到期的休假/外勤状态，返回 (生效条数, 结束恢复条数)。now 可注入以便测试。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    started = ended = 0

    # 一) 先结束：已生效且到期
    rows = (
        await session.execute(
            select(LeaveRequest).where(
                LeaveRequest.status == "in_progress",
                LeaveRequest.end_at <= now,
            )
        )
    ).scalars().all()
    for lr in rows:
        user = await session.get(User, lr.user_id)
        if not user or user.status != lr.leave_type:
            continue
        user.status = "active"
        lr.status = "completed"
        lr.completed_at = now
        ended += 1

    # 二) 再开始：已批准且到开始时间
    rows = (
        await session.execute(
            select(LeaveRequest).where(
                LeaveRequest.status == "approved",
                LeaveRequest.start_at <= now,
            )
        )
    ).scalars().all()
    for lr in rows:
        user = await session.get(User, lr.user_id)
        if not user or user.status != "active":
            continue
        user.status = lr.leave_type
        lr.status = "in_progress"
        started += 1

    if started or ended:
        await session.commit()
    return started, ended
