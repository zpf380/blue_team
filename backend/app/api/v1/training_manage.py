"""训练中心：课程管理 API（AI 生成 / 草稿 / 发布 / 编辑，发布后实时推送给学员）。

全部端点要求 training:course:manage（manager / admin），审计写操作。
"""
import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_user_agent, require_permission
from app.core.exceptions import AppError, ERR_CONFLICT, ERR_NOT_FOUND, ERR_VALIDATION, ok_response
from app.db.session import get_db
from app.models import SandboxSession, TrainingAgent, TrainingProgress, TrainingScenario, User
from app.schemas.training_manage import CourseGenerateIn, CourseIn, CourseUpdate, ScenarioIn, ScenarioUpdate
from app.services.audit_log import record
from app.services.training_generator import ALLOWED_COMMANDS, CourseGenerationError, generate_course
from app.services.training_notify import push_course_published

router = APIRouter(tags=["训练中心"])


async def _agent_or_404(session: AsyncSession, course_id: int) -> TrainingAgent:
    agent = await session.get(TrainingAgent, course_id)
    if not agent:
        raise AppError(code=ERR_NOT_FOUND, message="课程不存在")
    return agent


async def _scenario_or_404(session: AsyncSession, scenario_id: int) -> TrainingScenario:
    sc = await session.get(TrainingScenario, scenario_id)
    if not sc:
        raise AppError(code=ERR_NOT_FOUND, message="场景不存在")
    return sc


async def _course_of_scenario(session: AsyncSession, sc: TrainingScenario) -> TrainingAgent | None:
    return await session.get(TrainingAgent, sc.agent_id) if sc.agent_id else None


def _guard_draft(agent: TrainingAgent, action: str) -> None:
    """发布态守卫：已发布课程不允许结构性修改/删除（需先下线，避免影响进行中的学员）。"""
    if agent.status == "published":
        raise AppError(code=ERR_CONFLICT, message=f"课程已发布，请先下线再{action}")


def _validate_content_check(content: dict | None, where: str) -> None:
    """编辑器写入时校验任务 check.cmd 必须在沙箱白名单内。"""
    if not content:
        return
    for t in content.get("tasks", []):
        check = t.get("check") if isinstance(t, dict) else None
        if isinstance(check, dict) and check.get("cmd") and str(check["cmd"]) not in ALLOWED_COMMANDS:
            raise AppError(
                code=ERR_VALIDATION,
                message=f"{where}任务「{t.get('title', t.get('id', ''))}」命令 {check['cmd']} 不在沙箱支持命令集内",
            )


def _scenario_summary(sc: TrainingScenario) -> dict:
    return {
        "id": sc.id,
        "title": sc.title,
        "description": sc.description,
        "scenario_type": sc.scenario_type,
        "points": sc.points,
        "penalty_points": sc.penalty_points,
        "time_limit": sc.time_limit,
        "order_index": sc.order_index,
        "task_count": len((sc.content or {}).get("tasks", [])),
    }


# ---------- AI 生成课程 ----------
@router.post("/training/manage/generate")
async def generate_course_api(
    data: CourseGenerateIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    try:
        course = await generate_course(data.topic)
    except CourseGenerationError as exc:
        raise AppError(code=ERR_VALIDATION, message=str(exc)) from exc

    agent = TrainingAgent(
        name=course["name"],
        code=None,  # AI 生成课程不占用唯一 code，避免与内置智能体冲突
        description=course.get("description"),
        difficulty=course.get("difficulty", 1),
        prerequisites=None,
        order_index=0,
        status="draft",
        created_by=user.id,
    )
    session.add(agent)
    await session.flush()
    scenarios = []
    for i, sc in enumerate(course.get("scenarios", []), start=1):
        scenario = TrainingScenario(
            code=None,
            agent_id=agent.id,
            title=sc["title"],
            description=sc.get("description"),
            content=sc.get("content"),
            points=sc.get("points", 10),
            penalty_points=sc.get("penalty_points", 5),
            time_limit=sc.get("time_limit"),
            order_index=sc.get("order_index") or i,
        )
        session.add(scenario)
        scenarios.append(scenario)
    await session.flush()

    await record(
        session, user, "training:course:generate", target_type="course", target_id=str(agent.id),
        detail={"topic": data.topic, "name": agent.name, "scenario_count": len(scenarios)},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={
        "course_id": agent.id,
        "name": agent.name,
        "difficulty": agent.difficulty,
        "description": agent.description,
        "scenarios": [_scenario_summary(s) for s in scenarios],
    })


# ---------- 课程列表 / 详情 ----------
@router.get("/training/manage/courses")
async def list_courses(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agents = (await session.execute(
        select(TrainingAgent).order_by(TrainingAgent.created_at.desc(), TrainingAgent.id.desc())
    )).scalars().all()
    agent_ids = [a.id for a in agents]
    scenario_counts = {
        a_id: c
        for a_id, c in (
            await session.execute(
                select(TrainingScenario.agent_id, func.count())
                .where(TrainingScenario.agent_id.in_(agent_ids))
                .group_by(TrainingScenario.agent_id)
            )
        ).all()
    } if agent_ids else {}
    creator_ids = {a.created_by for a in agents if a.created_by}
    creators = {
        u.id: u.real_name or u.username
        for u in (await session.execute(select(User).where(User.id.in_(creator_ids)))).scalars()
    } if creator_ids else {}
    return ok_response(data=[
        {
            "id": a.id, "name": a.name, "code": a.code, "description": a.description,
            "difficulty": a.difficulty, "order_index": a.order_index,
            "status": a.status, "published_at": a.published_at, "created_at": a.created_at,
            "created_by": a.created_by, "creator_name": creators.get(a.created_by),
            "scenario_count": scenario_counts.get(a.id, 0),
        }
        for a in agents
    ])


@router.get("/training/manage/courses/{course_id}")
async def course_detail(
    course_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agent = await _agent_or_404(session, course_id)
    scenarios = (await session.execute(
        select(TrainingScenario).where(TrainingScenario.agent_id == course_id).order_by(TrainingScenario.order_index, TrainingScenario.id)
    )).scalars().all()
    return ok_response(data={
        "course": {
            "id": agent.id, "name": agent.name, "code": agent.code, "description": agent.description,
            "difficulty": agent.difficulty, "prerequisites": agent.prerequisites, "order_index": agent.order_index,
            "status": agent.status, "published_at": agent.published_at, "created_at": agent.created_at,
            "created_by": agent.created_by,
        },
        "scenarios": [
            {**_scenario_summary(s), "content": s.content}
            for s in scenarios
        ],
    })


# ---------- 手动建课程 / 更新 / 删除 ----------
@router.post("/training/manage/courses")
async def create_course(
    data: CourseIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agent = TrainingAgent(
        name=data.name,
        code=None,
        description=data.description,
        difficulty=data.difficulty,
        prerequisites=data.prerequisites,
        order_index=data.order_index,
        status="draft",
        created_by=user.id,
    )
    session.add(agent)
    await session.flush()
    await record(
        session, user, "training:course:create", target_type="course", target_id=str(agent.id),
        detail={"name": agent.name}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"course_id": agent.id, "status": agent.status})


@router.put("/training/manage/courses/{course_id}")
async def update_course(
    course_id: int,
    data: CourseUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agent = await _agent_or_404(session, course_id)
    _guard_draft(agent, "修改课程")
    if data.name is not None:
        agent.name = data.name
    if data.description is not None:
        agent.description = data.description
    if data.difficulty is not None:
        agent.difficulty = data.difficulty
    if data.prerequisites is not None:
        agent.prerequisites = data.prerequisites
    if data.order_index is not None:
        agent.order_index = data.order_index
    await record(
        session, user, "training:course:update", target_type="course", target_id=str(course_id),
        detail={"name": agent.name}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"course_id": course_id, "name": agent.name, "status": agent.status})


@router.delete("/training/manage/courses/{course_id}")
async def delete_course(
    course_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agent = await _agent_or_404(session, course_id)
    _guard_draft(agent, "删除课程")
    scenario_ids = list((await session.execute(
        select(TrainingScenario.id).where(TrainingScenario.agent_id == course_id)
    )).scalars())
    if scenario_ids:
        progress = (await session.execute(
            select(TrainingProgress.id).where(TrainingProgress.scenario_id.in_(scenario_ids)).limit(1)
        )).scalar_one_or_none()
        if progress:
            raise AppError(code=ERR_CONFLICT, message="该课程已有学员训练记录，不能删除")
        await session.execute(
            SandboxSession.__table__.delete().where(SandboxSession.scenario_id.in_(scenario_ids))
        )
        await session.execute(
            TrainingScenario.__table__.delete().where(TrainingScenario.agent_id == course_id)
        )
    await session.delete(agent)
    await record(
        session, user, "training:course:delete", target_type="course", target_id=str(course_id),
        detail={"name": agent.name}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"course_id": course_id})


# ---------- 发布 / 下线 ----------
@router.post("/training/manage/courses/{course_id}/publish")
async def publish_course(
    course_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agent = await _agent_or_404(session, course_id)
    if agent.status == "published":
        raise AppError(code=ERR_CONFLICT, message="课程已发布，请勿重复发布")
    scenario_count = (await session.execute(
        select(func.count()).select_from(TrainingScenario).where(TrainingScenario.agent_id == course_id)
    )).scalar_one()
    if scenario_count < 1:
        raise AppError(code=ERR_VALIDATION, message="课程至少包含 1 个场景才能发布")
    agent.status = "published"
    agent.published_at = dt.datetime.now(dt.timezone.utc)
    await record(
        session, user, "training:course:publish", target_type="course", target_id=str(course_id),
        detail={"name": agent.name, "scenario_count": scenario_count},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    await push_course_published(course_id, agent.name, scenario_count, agent.published_at)
    return ok_response(data={"course_id": course_id, "status": agent.status, "published_at": agent.published_at})


@router.post("/training/manage/courses/{course_id}/unpublish")
async def unpublish_course(
    course_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agent = await _agent_or_404(session, course_id)
    if agent.status != "published":
        raise AppError(code=ERR_CONFLICT, message="课程未发布，无需下线")
    agent.status = "draft"
    agent.published_at = None
    await record(
        session, user, "training:course:unpublish", target_type="course", target_id=str(course_id),
        detail={"name": agent.name}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"course_id": course_id, "status": agent.status})


# ---------- 场景维护 ----------
@router.post("/training/manage/courses/{course_id}/scenarios")
async def add_scenario(
    course_id: int,
    data: ScenarioIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    agent = await _agent_or_404(session, course_id)
    _guard_draft(agent, "添加场景")
    _validate_content_check(data.content, "场景「%s」" % data.title)
    sc = TrainingScenario(
        code=None,
        agent_id=course_id,
        title=data.title,
        description=data.description,
        scenario_type=data.scenario_type,
        content=data.content,
        points=data.points,
        penalty_points=data.penalty_points,
        time_limit=data.time_limit,
        order_index=data.order_index,
    )
    session.add(sc)
    await session.flush()
    await record(
        session, user, "training:scenario:create", target_type="scenario", target_id=str(sc.id),
        detail={"title": sc.title}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data=_scenario_summary(sc))


@router.put("/training/manage/scenarios/{scenario_id}")
async def update_scenario(
    scenario_id: int,
    data: ScenarioUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    sc = await _scenario_or_404(session, scenario_id)
    agent = await _course_of_scenario(session, sc)
    if agent:
        _guard_draft(agent, "修改场景")
    if data.title is not None:
        sc.title = data.title
    if data.description is not None:
        sc.description = data.description
    if data.scenario_type is not None:
        sc.scenario_type = data.scenario_type
    if data.content is not None:
        _validate_content_check(data.content, "场景「%s」" % sc.title)
        sc.content = data.content
    if data.points is not None:
        sc.points = data.points
    if data.penalty_points is not None:
        sc.penalty_points = data.penalty_points
    if data.time_limit is not None:
        sc.time_limit = data.time_limit
    if data.order_index is not None:
        sc.order_index = data.order_index
    await record(
        session, user, "training:scenario:update", target_type="scenario", target_id=str(scenario_id),
        detail={"title": sc.title}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data=_scenario_summary(sc))


@router.delete("/training/manage/scenarios/{scenario_id}")
async def delete_scenario(
    scenario_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("training:course:manage")),
):
    sc = await _scenario_or_404(session, scenario_id)
    agent = await _course_of_scenario(session, sc)
    if agent:
        _guard_draft(agent, "删除场景")
    progress = (await session.execute(
        select(TrainingProgress.id).where(TrainingProgress.scenario_id == scenario_id).limit(1)
    )).scalar_one_or_none()
    if progress:
        raise AppError(code=ERR_CONFLICT, message="该场景已有学员训练记录，不能删除")
    await session.execute(SandboxSession.__table__.delete().where(SandboxSession.scenario_id == scenario_id))
    await session.delete(sc)
    await record(
        session, user, "training:scenario:delete", target_type="scenario", target_id=str(scenario_id),
        detail={"title": sc.title}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"scenario_id": scenario_id})
