"""徽章判定与授予：根据训练行为给用户颁发徽章（幂等）。"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Badge, ScoreRecord, TrainingProgress, User, UserBadge


async def _total_points(session: AsyncSession, user_id: int) -> int:
    return (
        await session.execute(
            select(func.coalesce(func.sum(ScoreRecord.points), 0)).where(ScoreRecord.user_id == user_id)
        )
    ).scalar_one()


async def _completed_scenarios(session: AsyncSession, user_id: int) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(TrainingProgress)
            .where(TrainingProgress.user_id == user_id, TrainingProgress.status == "completed")
        )
    ).scalar_one()


async def _completed_all_of_agent(session: AsyncSession, user_id: int, agent_id: int) -> bool:
    """某智能体下所有场景是否全部完成。"""
    from app.models import TrainingScenario

    total = (
        await session.execute(select(func.count()).select_from(TrainingScenario).where(TrainingScenario.agent_id == agent_id))
    ).scalar_one()
    if total == 0:
        return False
    done = (
        await session.execute(
            select(func.count())
            .select_from(TrainingProgress)
            .join(TrainingScenario, TrainingProgress.scenario_id == TrainingScenario.id)
            .where(
                TrainingProgress.user_id == user_id,
                TrainingScenario.agent_id == agent_id,
                TrainingProgress.status == "completed",
            )
        )
    ).scalar_one()
    return done >= total


async def check_and_award(session: AsyncSession, user: User, *, perfect: bool = False) -> list[dict]:
    """在用户完成一次训练后调用，返回新授予的徽章列表。"""
    badges = (await session.execute(select(Badge))).scalars().all()
    mine = set(
        (await session.execute(select(UserBadge.badge_id).where(UserBadge.user_id == user.id))).scalars()
    )
    total_points = await _total_points(session, user.id)
    completed = await _completed_scenarios(session, user.id)
    awarded: list[dict] = []

    for b in badges:
        if b.id in mine:
            continue
        cond = b.condition_type or ""
        value = b.condition_value or {}
        ok = False
        if cond == "first_completion":
            ok = completed >= 1
        elif cond == "total_points":
            ok = total_points >= int(value.get("points", 0))
        elif cond == "perfect_score":
            ok = perfect
        elif cond == "complete_agent":
            agent_id = value.get("agent_id")
            if agent_id:
                ok = await _completed_all_of_agent(session, user.id, int(agent_id))
        if ok:
            session.add(UserBadge(user_id=user.id, badge_id=b.id))
            awarded.append({"id": b.id, "name": b.name, "description": b.description, "icon_url": b.icon_url})

    if awarded:
        await session.flush()
    return awarded
