"""训练子系统集成测试：智能体/场景/沙箱命令/判分/排行/统计/徽章/权限。"""
import uuid

import pytest


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def _login(client, username, password="Bt@123456"):
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_agent_list_and_detail(client):
    t = await _login(client, "trainee01")
    resp = await client.get("/api/v1/training/agents", headers=_h(t))
    assert resp.json()["code"] == 0
    agents = resp.json()["data"]
    assert len(agents) >= 3
    foundation = next(a for a in agents if a["code"] == "foundation")
    assert foundation["scenario_count"] >= 1

    resp = await client.get(f"/api/v1/training/agents/{foundation['id']}", headers=_h(t))
    body = resp.json()["data"]
    assert len(body["scenarios"]) >= 1
    assert all("my_progress" in s for s in body["scenarios"])


@pytest.mark.asyncio
async def test_sandbox_flow_submit_and_badges(client):
    t = await _login(client, "trainee01")
    agents = (await client.get("/api/v1/training/agents", headers=_h(t))).json()["data"]
    foundation = next(a for a in agents if a["code"] == "foundation")
    detail = (await client.get(f"/api/v1/training/agents/{foundation['id']}", headers=_h(t))).json()["data"]
    sc = next(s for s in detail["scenarios"] if s["title"] == "日志分析入门：发现暴力破解")

    # 开始场景
    resp = await client.post(f"/api/v1/training/scenarios/{sc['id']}/start", headers=_h(t))
    body = resp.json()
    assert body["code"] == 0, body
    sid = body["data"]["session_id"]
    assert len(body["data"]["tasks"]) == 4

    # 按顺序执行解题命令
    for cmd in ["cat /var/log/auth.log", "grep 'Failed password' /var/log/auth.log",
                "grep '203.0.113.5' /var/log/auth.log", "iptables -A INPUT -s 203.0.113.5 -j DROP"]:
        resp = await client.post(f"/api/v1/training/sandbox/{sid}/command", headers=_h(t), json={"command": cmd})
        assert resp.json()["code"] == 0, resp.json()
    assert resp.json()["data"]["all_completed"] is True
    assert resp.json()["data"]["points"] == 60

    # 提交结算
    resp = await client.post(f"/api/v1/training/scenarios/{sc['id']}/submit", headers=_h(t))
    body = resp.json()["data"]
    assert body["status"] == "completed"
    assert body["score"] == 60
    # 徽章幂等：本跑刚授予，或此前已授予（累计到徽章墙）
    badges_resp = (await client.get("/api/v1/training/badges", headers=_h(t))).json()["data"]
    first_badge = next(b for b in badges_resp["badges"] if b["name"] == "初次告捷")
    assert first_badge["id"] in badges_resp["mine"]

    # 重新提交幂等
    resp = await client.post(f"/api/v1/training/scenarios/{sc['id']}/submit", headers=_h(t))
    assert resp.json()["data"]["already_submitted"] is True


@pytest.mark.asyncio
async def test_ranking_stats_and_badges(client):
    t = await _login(client, "trainee01")
    resp = await client.get("/api/v1/training/ranking", headers=_h(t))
    assert resp.json()["code"] == 0
    rows = resp.json()["data"]
    me = next(r for r in rows if r["username"] == "trainee01")
    assert me["total_points"] >= 60
    assert me["completed_scenarios"] >= 1

    resp = await client.get("/api/v1/training/stats", headers=_h(t))
    stats = resp.json()["data"]
    assert stats["personal"]["completed_scenarios"] >= 1
    assert stats["personal"]["total_points"] >= 60
    assert isinstance(stats["departments"], list)

    resp = await client.get("/api/v1/training/badges", headers=_h(t))
    body = resp.json()["data"]
    assert len(body["badges"]) >= 5
    first_badge = next(b for b in body["badges"] if b["name"] == "初次告捷")
    assert first_badge["id"] in body["mine"]


@pytest.mark.asyncio
async def test_sandbox_permission_and_isolation(client):
    trainee_t = await _login(client, "trainee01")
    analyst_t = await _login(client, "analyst01")
    auditor_t = await _login(client, "auditor01")

    # 审计员无训练权限
    resp = await client.get("/api/v1/training/agents", headers=_h(auditor_t))
    assert resp.json()["code"] == 40302

    # 学员开始一个场景，分析师不能操作其会话
    agents = (await client.get("/api/v1/training/agents", headers=_h(trainee_t))).json()["data"]
    foundation = next(a for a in agents if a["code"] == "foundation")
    detail = (await client.get(f"/api/v1/training/agents/{foundation['id']}", headers=_h(trainee_t))).json()["data"]
    sc = next(s for s in detail["scenarios"] if s["title"] == "日志分析入门：发现暴力破解")
    sid = (await client.post(f"/api/v1/training/scenarios/{sc['id']}/start", headers=_h(trainee_t))).json()["data"]["session_id"]

    resp = await client.post(f"/api/v1/training/sandbox/{sid}/command", headers=_h(analyst_t), json={"command": "ls"})
    assert resp.json()["code"] == 40301


# ---------- 课程管理（AI 生成 + 发布 + 学员侧门控） ----------

def _uniq(prefix="测试课程"):
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _mk_content(cmd="cat", args="/var/log/auth.log", points=20):
    return {
        "intro": "场景引言：请分析日志并定位攻击来源。",
        "files": {"/var/log/auth.log": "Aug 13 02:11:07 Failed password for root from 203.0.113.5\n"},
        "tasks": [
            {"id": "t1", "title": "查看日志", "points": points, "hint": "cat /var/log/auth.log", "check": {"cmd": cmd, "args": args}},
        ],
    }


_GEN_COURSE = {
    "name": "AI 生成演示课",
    "difficulty": 2,
    "description": "按主题生成。",
    "scenarios": [
        {
            "title": "生成场景",
            "description": "场景描述",
            "points": 30,
            "penalty_points": 5,
            "time_limit": 20,
            "order_index": 1,
            "content": {
                "intro": "分析日志定位攻击 IP。",
                "files": {"/var/log/auth.log": "Aug 13 02:11:07 Failed password for root from 203.0.113.5\n"},
                "tasks": [
                    {"id": "t1", "title": "查看日志", "points": 10, "hint": "cat /var/log/auth.log", "check": {"cmd": "cat", "args": "/var/log/auth.log"}},
                    {"id": "t2", "title": "封禁 IP", "points": 20, "hint": "iptables -A INPUT -s 203.0.113.5 -j DROP", "check": {"cmd": "iptables", "pattern": "203.0.113.5"}},
                ],
            },
        }
    ],
}


async def _purge_course(test_session, course_id):
    from sqlalchemy import delete, select

    from app.models import SandboxSession, TrainingAgent, TrainingProgress, TrainingScenario

    scids = list((await test_session.execute(select(TrainingScenario.id).where(TrainingScenario.agent_id == course_id))).scalars())
    if scids:
        await test_session.execute(delete(TrainingProgress).where(TrainingProgress.scenario_id.in_(scids)))
        await test_session.execute(delete(SandboxSession).where(SandboxSession.scenario_id.in_(scids)))
        await test_session.execute(delete(TrainingScenario).where(TrainingScenario.agent_id == course_id))
    await test_session.execute(delete(TrainingAgent).where(TrainingAgent.id == course_id))
    await test_session.commit()


@pytest.mark.asyncio
async def test_manage_permission_gate(client):
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")
    auditor_t = await _login(client, "auditor01")
    admin_t = await _login(client, "admin", "admin123")

    resp = await client.get("/api/v1/training/manage/courses", headers=_h(trainee_t))
    assert resp.json()["code"] == 40302
    resp = await client.get("/api/v1/training/manage/courses", headers=_h(auditor_t))
    assert resp.json()["code"] == 40302
    resp = await client.get("/api/v1/training/manage/courses", headers=_h(manager_t))
    assert resp.json()["code"] == 0
    resp = await client.get("/api/v1/training/manage/courses", headers=_h(admin_t))
    assert resp.json()["code"] == 0


@pytest.mark.asyncio
async def test_course_publish_flow_and_push(client, test_session, monkeypatch):
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")
    course_id = None
    pushed = {}

    async def fake_push(cid, name, scenario_count, published_at=None):
        pushed["course_id"] = cid
        pushed["name"] = name
        pushed["scenario_count"] = scenario_count

    monkeypatch.setattr("app.api.v1.training_manage.push_course_published", fake_push)
    name = _uniq("发布门控")
    try:
        # 建草稿
        resp = await client.post("/api/v1/training/manage/courses", headers=_h(manager_t), json={"name": name})
        assert resp.json()["code"] == 0, resp.json()
        course_id = resp.json()["data"]["course_id"]

        # 空课程发布 → 40001
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/publish", headers=_h(manager_t))
        assert resp.json()["code"] == 40001

        # 加场景
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/scenarios", headers=_h(manager_t),
                                 json={"title": "场景A", "points": 20, "content": _mk_content()})
        assert resp.json()["code"] == 0, resp.json()
        scen_id = resp.json()["data"]["id"]

        # 学员不可见（草稿）：列表无、详情 404、start 404
        resp = await client.get("/api/v1/training/agents", headers=_h(trainee_t))
        assert all(a["id"] != course_id for a in resp.json()["data"])
        resp = await client.get(f"/api/v1/training/agents/{course_id}", headers=_h(trainee_t))
        assert resp.json()["code"] == 40400
        resp = await client.post(f"/api/v1/training/scenarios/{scen_id}/start", headers=_h(trainee_t))
        assert resp.json()["code"] == 40400

        # 发布 → 推送被调用
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/publish", headers=_h(manager_t))
        assert resp.json()["code"] == 0, resp.json()
        assert resp.json()["data"]["status"] == "published"
        assert pushed.get("course_id") == course_id
        assert pushed.get("scenario_count") == 1

        # 学员可见 + published_at + 内置 foundation 同样有 published_at
        resp = await client.get("/api/v1/training/agents", headers=_h(trainee_t))
        rows = resp.json()["data"]
        row = next(a for a in rows if a["id"] == course_id)
        assert row["published_at"] is not None
        assert any(a["code"] == "foundation" and a["published_at"] for a in rows)

        # 学员可 start（发布门控放行）
        resp = await client.post(f"/api/v1/training/scenarios/{scen_id}/start", headers=_h(trainee_t))
        assert resp.json()["code"] == 0, resp.json()

        # 下线后学员不可见
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/unpublish", headers=_h(manager_t))
        assert resp.json()["code"] == 0
        resp = await client.get("/api/v1/training/agents", headers=_h(trainee_t))
        assert all(a["id"] != course_id for a in resp.json()["data"])
    finally:
        if course_id:
            await _purge_course(test_session, course_id)


@pytest.mark.asyncio
async def test_course_generate_endpoint(client, test_session, monkeypatch):
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")
    course_id = None

    async def fake_generate(topic):
        return {k: (v if k != "name" else f"{_GEN_COURSE['name']}-{topic}") for k, v in _GEN_COURSE.items()}

    monkeypatch.setattr("app.api.v1.training_manage.generate_course", fake_generate)
    try:
        resp = await client.post("/api/v1/training/manage/generate", headers=_h(manager_t), json={"topic": "应急响应"})
        assert resp.json()["code"] == 0, resp.json()
        body = resp.json()["data"]
        course_id = body["course_id"]
        assert len(body["scenarios"]) == 1
        # 落库为草稿
        resp = await client.get("/api/v1/training/manage/courses", headers=_h(manager_t))
        row = next(c for c in resp.json()["data"] if c["id"] == course_id)
        assert row["status"] == "draft"
        assert row["scenario_count"] == 1
        # 学员不可见
        resp = await client.get("/api/v1/training/agents", headers=_h(trainee_t))
        assert all(a["id"] != course_id for a in resp.json()["data"])
    finally:
        if course_id:
            await _purge_course(test_session, course_id)


@pytest.mark.asyncio
async def test_course_generate_error(client, monkeypatch):
    from app.services.training_generator import CourseGenerationError

    manager_t = await _login(client, "manager01")

    async def fake_generate(topic):
        raise CourseGenerationError("AI 服务暂不可用，请稍后再试")

    monkeypatch.setattr("app.api.v1.training_manage.generate_course", fake_generate)
    resp = await client.post("/api/v1/training/manage/generate", headers=_h(manager_t), json={"topic": "应急响应"})
    assert resp.json()["code"] == 40001
    assert "AI 服务暂不可用" in resp.json()["message"]


@pytest.mark.asyncio
async def test_manage_update_and_delete_protection(client, test_session):
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")
    course_id = None
    scen_id = None
    name = _uniq("更新保护")
    try:
        resp = await client.post("/api/v1/training/manage/courses", headers=_h(manager_t), json={"name": name})
        course_id = resp.json()["data"]["course_id"]
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/scenarios", headers=_h(manager_t),
                                 json={"title": "场景A", "points": 20, "content": _mk_content()})
        scen_id = resp.json()["data"]["id"]

        # 更新课程与场景
        resp = await client.put(f"/api/v1/training/manage/courses/{course_id}", headers=_h(manager_t),
                                json={"name": name + "改"})
        assert resp.json()["code"] == 0
        resp = await client.put(f"/api/v1/training/manage/scenarios/{scen_id}", headers=_h(manager_t),
                                json={"content": _mk_content(points=20), "points": 20})
        assert resp.json()["code"] == 0, resp.json()
        # 非法 check.cmd → 40001
        resp = await client.put(f"/api/v1/training/manage/scenarios/{scen_id}", headers=_h(manager_t),
                                json={"content": _mk_content(cmd="rm")})
        assert resp.json()["code"] == 40001

        # 发布并让学员开始 → 产生进度 → 删除保护
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/publish", headers=_h(manager_t))
        assert resp.json()["code"] == 0
        resp = await client.post(f"/api/v1/training/scenarios/{scen_id}/start", headers=_h(trainee_t))
        assert resp.json()["code"] == 0, resp.json()
        resp = await client.delete(f"/api/v1/training/manage/scenarios/{scen_id}", headers=_h(manager_t))
        assert resp.json()["code"] == 40900
        resp = await client.delete(f"/api/v1/training/manage/courses/{course_id}", headers=_h(manager_t))
        assert resp.json()["code"] == 40900
    finally:
        if course_id:
            await _purge_course(test_session, course_id)


# ---------- 批次4：课程发布态守卫 ----------
@pytest.mark.asyncio
async def test_course_publish_state_machine(client, test_session):
    """发布态守卫：已发布课程禁止重复发布/下线草稿/修改/加场景/改删场景；下线后恢复可编辑。"""
    manager_t = await _login(client, "manager01")
    course_id = None
    scen_id = None
    name = _uniq("状态机")
    try:
        # 建草稿 + 加场景
        resp = await client.post("/api/v1/training/manage/courses", headers=_h(manager_t), json={"name": name})
        assert resp.json()["code"] == 0, resp.json()
        course_id = resp.json()["data"]["course_id"]
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/scenarios", headers=_h(manager_t),
                                 json={"title": "场景A", "points": 20, "content": _mk_content()})
        assert resp.json()["code"] == 0, resp.json()
        scen_id = resp.json()["data"]["id"]

        # 草稿不能下线
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/unpublish", headers=_h(manager_t))
        assert resp.json()["code"] == 40900 and "无需下线" in resp.json()["message"]

        # 发布
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/publish", headers=_h(manager_t))
        assert resp.json()["code"] == 0

        # 已发布：重复发布 / 修改课程 / 加场景 / 改场景 / 删场景 / 删课程 → 一律 409
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/publish", headers=_h(manager_t))
        assert resp.json()["code"] == 40900 and "请勿重复发布" in resp.json()["message"]
        resp = await client.put(f"/api/v1/training/manage/courses/{course_id}", headers=_h(manager_t), json={"name": name + "改"})
        assert resp.json()["code"] == 40900 and "请先下线" in resp.json()["message"]
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/scenarios", headers=_h(manager_t),
                                 json={"title": "场景B", "points": 10, "content": _mk_content()})
        assert resp.json()["code"] == 40900
        resp = await client.put(f"/api/v1/training/manage/scenarios/{scen_id}", headers=_h(manager_t), json={"points": 30})
        assert resp.json()["code"] == 40900
        resp = await client.delete(f"/api/v1/training/manage/scenarios/{scen_id}", headers=_h(manager_t))
        assert resp.json()["code"] == 40900
        resp = await client.delete(f"/api/v1/training/manage/courses/{course_id}", headers=_h(manager_t))
        assert resp.json()["code"] == 40900

        # 下线后恢复可编辑
        resp = await client.post(f"/api/v1/training/manage/courses/{course_id}/unpublish", headers=_h(manager_t))
        assert resp.json()["code"] == 0
        resp = await client.put(f"/api/v1/training/manage/courses/{course_id}", headers=_h(manager_t), json={"name": name + "改"})
        assert resp.json()["code"] == 0, resp.json()
    finally:
        if course_id:
            await _purge_course(test_session, course_id)


# ---------- 批次4：单活跃沙箱会话 ----------
@pytest.mark.asyncio
async def test_sandbox_single_active_session(client, test_session):
    """单活跃沙箱：再开新场景旧会话被停用；命令/提交被停用会话均被拒绝。"""
    from sqlalchemy import delete

    from app.models import SandboxSession, TrainingProgress

    t = await _login(client, "trainee01")
    agents = (await client.get("/api/v1/training/agents", headers=_h(t))).json()["data"]
    foundation = next(a for a in agents if a["code"] == "foundation")
    detail = (await client.get(f"/api/v1/training/agents/{foundation['id']}", headers=_h(t))).json()["data"]
    sc1, sc2 = detail["scenarios"][0], detail["scenarios"][1]
    me = (await client.get("/api/v1/users/me", headers=_h(t))).json()["data"]
    uid = me["id"]

    try:
        sid1 = (await client.post(f"/api/v1/training/scenarios/{sc1['id']}/start", headers=_h(t))).json()["data"]["session_id"]
        sid2 = (await client.post(f"/api/v1/training/scenarios/{sc2['id']}/start", headers=_h(t))).json()["data"]["session_id"]
        assert sid1 != sid2

        s1 = await test_session.get(SandboxSession, sid1)
        s2 = await test_session.get(SandboxSession, sid2)
        assert s1 is not None and s1.is_active is False
        assert s2 is not None and s2.is_active is True

        # 被停用会话：命令 / 提交 → 40001
        resp = await client.post(f"/api/v1/training/sandbox/{sid1}/command", headers=_h(t), json={"command": "ls"})
        assert resp.json()["code"] == 40001, resp.json()
        resp = await client.post(f"/api/v1/training/scenarios/{sc1['id']}/submit", headers=_h(t))
        assert resp.json()["code"] == 40001, resp.json()

        # 活跃会话仍可命令
        resp = await client.post(f"/api/v1/training/sandbox/{sid2}/command", headers=_h(t), json={"command": "cat /var/log/auth.log"})
        assert resp.json()["code"] == 0, resp.json()
    finally:
        await test_session.execute(delete(SandboxSession).where(SandboxSession.user_id == uid))
        await test_session.execute(delete(TrainingProgress).where(
            TrainingProgress.user_id == uid, TrainingProgress.scenario_id.in_([sc1["id"], sc2["id"]])
        ))
        await test_session.commit()
