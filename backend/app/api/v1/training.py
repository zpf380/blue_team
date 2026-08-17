"""训练子系统 API：智能体/场景/沙箱命令/提交结算/排行/统计/徽章。"""
import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_client_ip, get_user_agent, require_permission
from app.core.exceptions import AppError, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_VALIDATION, ok_response
from app.db.session import get_db
from app.models import Department, Role, SandboxSession, ScoreRecord, TrainingAgent, TrainingProgress, TrainingScenario, User, UserBadge, Badge
from app.schemas.training import SandboxCommandIn
from app.services import badge_service, sandbox_service
from app.services.audit_log import record

router = APIRouter(tags=["训练中心"])


def _session_id() -> str:
    return f"sbx_{uuid.uuid4().hex[:12]}"


async def _scenario_or_404(session: AsyncSession, scenario_id: int) -> TrainingScenario:
    sc = await session.get(TrainingScenario, scenario_id)
    if not sc:
        raise AppError(code=ERR_NOT_FOUND, message="场景不存在")
    return sc


async def _sandbox_or_404(session: AsyncSession, user: User, sid: str) -> SandboxSession:
    s = await session.get(SandboxSession, sid)
    if not s:
        raise AppError(code=ERR_NOT_FOUND, message="沙箱会话不存在")
    if s.user_id != user.id:
        raise AppError(code=ERR_FORBIDDEN, message="无权访问该沙箱会话")
    return s


def _progress_out(p: TrainingProgress | None) -> dict | None:
    if not p:
        return None
    return {
        "id": p.id,
        "status": p.status,
        "score": p.score,
        "attempts": p.attempts,
        "sandbox_session_id": p.sandbox_session_id,
        "started_at": p.started_at,
        "completed_at": p.completed_at,
    }


# ---------- 智能体 / 场景 ----------
@router.get("/training/agents")
async def list_agents(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:agent:view")),
):
    agents = (await session.execute(
        select(TrainingAgent).where(TrainingAgent.status == "published").order_by(TrainingAgent.order_index, TrainingAgent.id)
    )).scalars().all()
    scenario_counts = {
        a_id: c
        for a_id, c in (
            await session.execute(
                select(TrainingScenario.agent_id, func.count())
                .where(TrainingScenario.agent_id.in_([a.id for a in agents]))
                .group_by(TrainingScenario.agent_id)
            )
        ).all()
    }
    done_counts = {
        a_id: c
        for a_id, c in (
            await session.execute(
                select(TrainingScenario.agent_id, func.count(TrainingProgress.id))
                .join(TrainingProgress, TrainingProgress.scenario_id == TrainingScenario.id)
                .where(
                    TrainingScenario.agent_id.in_([a.id for a in agents]),
                    TrainingProgress.user_id == user.id,
                    TrainingProgress.status == "completed",
                )
                .group_by(TrainingScenario.agent_id)
            )
        ).all()
    }
    return ok_response(data=[
        {
            "id": a.id, "name": a.name, "code": a.code, "description": a.description,
            "icon_url": a.icon_url, "difficulty": a.difficulty, "prerequisites": a.prerequisites,
            "order_index": a.order_index, "status": a.status, "published_at": a.published_at,
            "scenario_count": scenario_counts.get(a.id, 0),
            "completed_count": done_counts.get(a.id, 0),
        }
        for a in agents
    ])


@router.get("/training/agents/{agent_id}")
async def agent_detail(
    agent_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:agent:view")),
):
    agent = await session.get(TrainingAgent, agent_id)
    if not agent or agent.status != "published":
        raise AppError(code=ERR_NOT_FOUND, message="智能体不存在")
    scenarios = (await session.execute(
        select(TrainingScenario).where(TrainingScenario.agent_id == agent_id).order_by(TrainingScenario.order_index, TrainingScenario.id)
    )).scalars().all()
    progress_map = {
        p.scenario_id: p
        for p in (await session.execute(
            select(TrainingProgress).where(TrainingProgress.user_id == user.id, TrainingProgress.scenario_id.in_([s.id for s in scenarios]))
        )).scalars()
    }
    return ok_response(data={
        "agent": {
            "id": agent.id, "name": agent.name, "code": agent.code, "description": agent.description,
            "icon_url": agent.icon_url, "difficulty": agent.difficulty, "prerequisites": agent.prerequisites,
            "status": agent.status, "published_at": agent.published_at,
        },
        "scenarios": [
            {
                "id": s.id, "title": s.title, "description": s.description, "scenario_type": s.scenario_type,
                "points": s.points, "penalty_points": s.penalty_points, "time_limit": s.time_limit,
                "order_index": s.order_index, "task_count": len((s.content or {}).get("tasks", [])),
                "my_progress": _progress_out(progress_map.get(s.id)),
            }
            for s in scenarios
        ],
    })


# ---------- 沙箱 ----------
@router.post("/training/scenarios/{scenario_id}/start")
async def start_scenario(
    scenario_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:sandbox")),
):
    sc = await _scenario_or_404(session, scenario_id)
    agent = await session.get(TrainingAgent, sc.agent_id) if sc.agent_id else None
    if not agent or agent.status != "published":
        raise AppError(code=ERR_NOT_FOUND, message="场景不存在")
    progress = (await session.execute(
        select(TrainingProgress).where(TrainingProgress.user_id == user.id, TrainingProgress.scenario_id == scenario_id)
    )).scalar_one_or_none()
    if progress and progress.status in ("completed", "failed"):
        # 已结算：重新开始 = 新一次尝试
        progress.status = "in_progress"
        progress.attempts += 1
        progress.started_at = dt.datetime.now(dt.timezone.utc)
        progress.completed_at = None
        progress.score = None
    elif progress:
        progress.status = "in_progress"
    else:
        progress = TrainingProgress(
            user_id=user.id, scenario_id=scenario_id, status="in_progress", attempts=1,
            started_at=dt.datetime.now(dt.timezone.utc),
        )
        session.add(progress)
    await session.flush()

    sid = _session_id()
    s = SandboxSession(
        id=sid, user_id=user.id, agent_id=sc.agent_id, scenario_id=scenario_id,
        state=sandbox_service.create_initial_state(sc),
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12),
        is_active=True,
    )
    session.add(s)
    progress.sandbox_session_id = sid
    await record(
        session, user, "training:start", target_type="scenario", target_id=str(scenario_id),
        detail={"session_id": sid}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()

    content = sc.content or {}
    return ok_response(data={
        "session_id": sid,
        "scenario": {"id": sc.id, "title": sc.title, "description": sc.description, "points": sc.points, "time_limit": sc.time_limit},
        "intro": content.get("intro", ""),
        "tasks": [{"id": t.get("id"), "title": t.get("title", ""), "points": t.get("points", 10)} for t in content.get("tasks", [])],
        "my_progress": _progress_out(progress),
    })


@router.post("/training/sandbox/{session_id}/command")
async def sandbox_command(
    session_id: str,
    data: SandboxCommandIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:sandbox")),
):
    s = await _sandbox_or_404(session, user, session_id)
    if not s.is_active:
        raise AppError(code=ERR_VALIDATION, message="沙箱会话已结束")
    sc = await session.get(TrainingScenario, s.scenario_id)
    if not sc:
        raise AppError(code=ERR_NOT_FOUND, message="场景不存在")
    result = sandbox_service.run_command(sc, s.state or {}, data.command)
    s.state = result
    await session.commit()
    return ok_response(data={**result, "session_id": session_id})


@router.post("/training/scenarios/{scenario_id}/submit")
async def submit_scenario(
    scenario_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:sandbox")),
):
    sc = await _scenario_or_404(session, scenario_id)
    progress = (await session.execute(
        select(TrainingProgress).where(TrainingProgress.user_id == user.id, TrainingProgress.scenario_id == scenario_id)
    )).scalar_one_or_none()
    if not progress:
        raise AppError(code=ERR_VALIDATION, message="请先开始该场景")
    if progress.status in ("completed", "failed"):
        return ok_response(data={"score": progress.score, "status": progress.status, "earned_badges": [], "already_submitted": True})

    s = await session.get(SandboxSession, progress.sandbox_session_id) if progress.sandbox_session_id else None
    state = s.state if s else sandbox_service.create_initial_state(sc)
    score, status = sandbox_service.calc_final_score(sc, state)
    progress.score = score
    progress.status = status
    progress.completed_at = dt.datetime.now(dt.timezone.utc)
    if s:
        s.is_active = False

    # 积分记录（仅 completed 计分）
    if status == "completed" and score > 0:
        existing = (await session.execute(
            select(ScoreRecord).where(ScoreRecord.user_id == user.id, ScoreRecord.source_type == "training", ScoreRecord.source_id == scenario_id)
        )).scalar_one_or_none()
        if not existing:
            session.add(ScoreRecord(
                user_id=user.id, source_type="training", source_id=scenario_id,
                points=score, description=f"完成训练：{sc.title}",
            ))

    await session.flush()
    earned = await badge_service.check_and_award(
        session, user,
        perfect=(status == "completed" and state.get("penalty", 0) == 0 and state.get("points", 0) >= (sc.points or 0)),
    )
    await record(
        session, user, "training:submit", target_type="scenario", target_id=str(scenario_id),
        detail={"score": score, "status": status}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"score": score, "status": status, "earned_badges": earned, "already_submitted": False})


@router.get("/training/sandbox/sessions")
async def my_sessions(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:sandbox")),
):
    rows = (await session.execute(
        select(SandboxSession, TrainingScenario, TrainingAgent)
        .outerjoin(TrainingScenario, TrainingScenario.id == SandboxSession.scenario_id)
        .outerjoin(TrainingAgent, TrainingAgent.id == SandboxSession.agent_id)
        .where(SandboxSession.user_id == user.id)
        .order_by(SandboxSession.created_at.desc())
        .limit(50)
    )).all()
    return ok_response(data=[
        {
            "session_id": s.id,
            "scenario_id": s.scenario_id,
            "scenario_title": sc.title if sc else None,
            "agent_name": ag.name if ag else None,
            "is_active": s.is_active,
            "expires_at": s.expires_at,
            "created_at": s.created_at,
            "intro": (sc.content or {}).get("intro", "") if sc else "",
            "tasks": [{"id": t.get("id"), "title": t.get("title", ""), "points": t.get("points", 10)} for t in ((sc.content or {}).get("tasks", []))] if sc else [],
            "completed_tasks": (s.state or {}).get("completed_tasks", []),
            "task_count": len(((sc.content or {}).get("tasks", []))) if sc else 0,
            "points": (s.state or {}).get("points", 0),
            "penalty": (s.state or {}).get("penalty", 0),
        }
        for s, sc, ag in rows
    ])


# ---------- 排行 / 统计 / 徽章 ----------
@router.get("/training/ranking")
async def training_ranking(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:ranking")),
):
    rows = (await session.execute(
        select(User, func.coalesce(func.sum(ScoreRecord.points), 0).label("points"), func.count(ScoreRecord.id).label("records"))
        .join(ScoreRecord, ScoreRecord.user_id == User.id)
        .group_by(User.id)
        .order_by(func.coalesce(func.sum(ScoreRecord.points), 0).desc())
        .limit(50)
    )).all()
    user_ids = [u.id for u, _, _ in rows]
    dept_map = {d.id: d.name for d in (await session.execute(select(Department))).scalars()} if rows else {}
    completed_map = {
        uid: c
        for uid, c in (
            await session.execute(
                select(TrainingProgress.user_id, func.count())
                .where(TrainingProgress.user_id.in_(user_ids), TrainingProgress.status == "completed")
                .group_by(TrainingProgress.user_id)
            )
        ).all()
    } if rows else {}
    return ok_response(data=[
        {
            "rank": i + 1,
            "user_id": u.id,
            "username": u.username,
            "real_name": u.real_name,
            "department_name": dept_map.get(u.department_id),
            "total_points": int(points),
            "records": records,
            "completed_scenarios": completed_map.get(u.id, 0),
        }
        for i, (u, points, records) in enumerate(rows)
    ])


@router.get("/training/stats")
async def training_stats(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:stats")),
):
    total_points = (await session.execute(
        select(func.coalesce(func.sum(ScoreRecord.points), 0)).where(ScoreRecord.user_id == user.id)
    )).scalar_one()
    completed = (await session.execute(
        select(func.count()).select_from(TrainingProgress).where(TrainingProgress.user_id == user.id, TrainingProgress.status == "completed")
    )).scalar_one()
    in_progress = (await session.execute(
        select(func.count()).select_from(TrainingProgress).where(TrainingProgress.user_id == user.id, TrainingProgress.status == "in_progress")
    )).scalar_one()
    failed = (await session.execute(
        select(func.count()).select_from(TrainingProgress).where(TrainingProgress.user_id == user.id, TrainingProgress.status == "failed")
    )).scalar_one()
    badges_count = (await session.execute(
        select(func.count()).select_from(UserBadge).where(UserBadge.user_id == user.id)
    )).scalar_one()
    avg_score = (await session.execute(
        select(func.coalesce(func.avg(TrainingProgress.score), 0)).where(
            TrainingProgress.user_id == user.id, TrainingProgress.status == "completed"
        )
    )).scalar_one()

    # 部门维度积分汇总
    dept_rows = (await session.execute(
        select(Department.name, func.coalesce(func.sum(ScoreRecord.points), 0).label("points"), func.count(func.distinct(User.id)).label("members"))
        .join(User, User.department_id == Department.id)
        .join(ScoreRecord, ScoreRecord.user_id == User.id)
        .group_by(Department.id, Department.name)
        .order_by(func.coalesce(func.sum(ScoreRecord.points), 0).desc())
    )).all()

    return ok_response(data={
        "personal": {
            "total_points": int(total_points),
            "completed_scenarios": completed,
            "in_progress": in_progress,
            "failed": failed,
            "badges_count": badges_count,
            "avg_score": round(float(avg_score), 1),
        },
        "departments": [{"name": name, "points": int(points), "members": members} for name, points, members in dept_rows],
    })


@router.get("/training/badges")
async def training_badges(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:stats")),
):
    badges = (await session.execute(select(Badge).order_by(Badge.id))).scalars().all()
    mine = set((await session.execute(select(UserBadge.badge_id).where(UserBadge.user_id == user.id))).scalars())
    return ok_response(data={
        "badges": [
            {"id": b.id, "name": b.name, "description": b.description, "icon_url": b.icon_url, "condition_type": b.condition_type}
            for b in badges
        ],
        "mine": sorted(mine),
    })
