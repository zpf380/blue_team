"""聊天子系统集成测试：群组加入制 / 联系人双向确认 / 私聊唯一 / 管理员监控豁免。

新规则：
- 群组需「输入名称加入」后才能通信，否则频道列表为空；
- 私聊需先添加联系人且对方同意，才可建立；同一对人只有一个私聊频道；
- 学员仅可添加/私聊学员、仅可加入学员社区；
- 管理员豁免：群组列表全量、无需联系人即可私聊、可监控全部频道。
"""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", settings.DATABASE_URL)

# 错误码
E_FORBIDDEN = 40301
E_FORBIDDEN_PERM = 40302
E_NOT_FOUND = 40400
E_CONFLICT = 40900


@pytest.fixture(autouse=True)
async def _clean_chat():
    """每个聊天测试前重置聊天数据：保证列表为空 / 私聊唯一 / 联系人干净的确定性断言。

    保留 3 个基础频道（应急响应组/安全公告/学员社区）与基础用户，仅清理
    消息、成员关系、联系人、私聊频道。
    """
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DELETE FROM messages"))
            await conn.execute(text("DELETE FROM ai_conversations"))
            await conn.execute(text("DELETE FROM channel_members"))
            await conn.execute(text("DELETE FROM contacts"))
            await conn.execute(text("DELETE FROM contact_requests"))
            await conn.execute(text("DELETE FROM channels WHERE type = 'private'"))
            await conn.commit()
    finally:
        await engine.dispose()
    yield


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def _login(client, username, password="Bt@123456"):
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]["access_token"]


async def _user_id(client, admin_t, username):
    users = (await client.get("/api/v1/users", headers=_h(admin_t), params={"size": 100})).json()["data"]["items"]
    return next(u for u in users if u["username"] == username)["id"]


async def _join(client, token, name):
    return await client.post("/api/v1/channels/join", headers=_h(token), json={"name": name})


async def _establish_contact(client, requester_tok, requester_id, target_tok, target_id):
    """requester 发起添加请求，target 同意，建立双向联系人。"""
    req = await client.post("/api/v1/chat/contacts/requests", headers=_h(requester_tok), json={"target_id": target_id})
    assert req.json()["code"] == 0, req.json()
    pending = (await client.get("/api/v1/chat/contacts/requests", headers=_h(target_tok))).json()["data"]
    req_id = next(r for r in pending if r["requester_id"] == requester_id)["id"]
    acc = await client.post(f"/api/v1/chat/contacts/requests/{req_id}/accept", headers=_h(target_tok))
    assert acc.json()["code"] == 0, acc.json()
    return req, acc


@pytest.mark.asyncio
async def test_channel_role_isolation(client):
    """群组加入制：admin 全量可见；普通角色未加入时列表为空；无权限角色被拒。"""
    admin_t = await _login(client, "admin", "admin123")
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")

    # admin 监控视图：全部基础频道可见
    resp = await client.get("/api/v1/channels", headers=_h(admin_t))
    names = {c["name"] for c in resp.json()["data"]}
    assert {"应急响应组", "安全公告", "学员社区"} <= names

    # 普通角色（主管/学员）未加入任何群组 → 列表为空
    for tok in (manager_t, trainee_t):
        resp = await client.get("/api/v1/channels", headers=_h(tok))
        assert resp.json()["data"] == [], resp.json()

    # 无聊天权限角色（审计员）→ 40302
    auditor_t = await _login(client, "auditor01")
    resp = await client.get("/api/v1/channels", headers=_h(auditor_t))
    assert resp.json()["code"] == E_FORBIDDEN_PERM

    # 学员未加入时访问公开频道 → 无权
    pub = next(c for c in (await client.get("/api/v1/channels", headers=_h(admin_t))).json()["data"] if c["name"] == "应急响应组")
    resp = await client.get(f"/api/v1/channels/{pub['id']}/messages", headers=_h(trainee_t))
    assert resp.json()["code"] == E_FORBIDDEN


@pytest.mark.asyncio
async def test_join_channel_flow(client):
    """输入群组名称加入 → 列表出现 → 可通信；重复加入幂等；学员仅可加入学员社区。"""
    admin_t = await _login(client, "admin", "admin123")
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")

    # 加入不存在的群组 → 40400
    resp = await _join(client, manager_t, "不存在的群组")
    assert resp.json()["code"] == E_NOT_FOUND, resp.json()

    # 主管加入「应急响应组」→ 成功，列表出现
    resp = await _join(client, manager_t, "应急响应组")
    assert resp.json()["code"] == 0, resp.json()
    assert resp.json()["data"]["name"] == "应急响应组"
    channels = (await client.get("/api/v1/channels", headers=_h(manager_t))).json()["data"]
    assert [c["name"] for c in channels] == ["应急响应组"]

    # 重复加入幂等
    resp = await _join(client, manager_t, "应急响应组")
    assert resp.json()["code"] == 0, resp.json()

    # 加入后即可通信
    ch = resp.json()["data"]
    r = await client.post(f"/api/v1/channels/{ch['id']}/messages", headers=_h(manager_t), json={"content": "加入后发言"})
    assert r.json()["code"] == 0, r.json()

    # 学员加入公开群组 → 40301；加入学员社区 → 成功
    resp = await _join(client, trainee_t, "应急响应组")
    assert resp.json()["code"] == E_FORBIDDEN, resp.json()
    resp = await _join(client, trainee_t, "学员社区")
    assert resp.json()["code"] == 0, resp.json()
    assert resp.json()["data"]["type"] == "trainee"

    # 学员加入后列表仅含学员社区
    channels = (await client.get("/api/v1/channels", headers=_h(trainee_t))).json()["data"]
    assert [c["name"] for c in channels] == ["学员社区"]


@pytest.mark.asyncio
async def test_message_send_recall_search(client):
    """消息发送 / 历史 / 全文检索 / 撤回（admin 免加入即可访问）。"""
    admin_t = await _login(client, "admin", "admin123")
    channels = (await client.get("/api/v1/channels", headers=_h(admin_t))).json()["data"]
    ch = next(c for c in channels if c["name"] == "应急响应组")

    resp = await client.post(
        f"/api/v1/channels/{ch['id']}/messages",
        headers=_h(admin_t),
        json={"content": "测试消息 搜索关键字蓝队日志"},
    )
    assert resp.json()["code"] == 0
    msg = resp.json()["data"]

    # 历史列表包含
    resp = await client.get(f"/api/v1/channels/{ch['id']}/messages", headers=_h(admin_t))
    assert msg["id"] in [m["id"] for m in resp.json()["data"]["items"]]

    # 全文检索命中
    resp = await client.get("/api/v1/chat/search", headers=_h(admin_t), params={"q": "蓝队日志"})
    assert any(m["id"] == msg["id"] for m in resp.json()["data"])

    # 撤回
    resp = await client.post(f"/api/v1/messages/{msg['id']}/recall", headers=_h(admin_t))
    assert resp.json()["code"] == 0


@pytest.mark.asyncio
async def test_dm_and_ai_invoke(client):
    """私聊不可重复（需互为联系人，admin 与普通用户一致）；AI 调用兜底。"""
    admin_t = await _login(client, "admin", "admin123")
    admin_id = await _user_id(client, admin_t, "admin")
    target_id = await _user_id(client, admin_t, "analyst01")

    # 未添加联系人时私聊被拒（admin 与普通用户一致，无豁免）
    resp = await client.post("/api/v1/channels/dm", headers=_h(admin_t), json={"user_id": target_id})
    assert resp.json()["code"] == E_FORBIDDEN, resp.json()

    # 建立联系人后 admin 可与分析师私聊
    analyst_t = await _login(client, "analyst01")
    await _establish_contact(client, admin_t, admin_id, analyst_t, target_id)
    resp = await client.post("/api/v1/channels/dm", headers=_h(admin_t), json={"user_id": target_id})
    assert resp.json()["code"] == 0, resp.json()
    dm = resp.json()["data"]
    assert dm["type"] == "private"
    # 再次调用返回同一私聊频道（不可重复）
    resp = await client.post("/api/v1/channels/dm", headers=_h(admin_t), json={"user_id": target_id})
    assert resp.json()["data"]["id"] == dm["id"]

    # AI 调用（无 DeepSeek Key + Ollama 不可达 → 兜底）
    resp = await client.post("/api/v1/ai/invoke", headers=_h(admin_t), json={"query": "如何加固 SSH？"})
    assert resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["provider"] in ("ollama", "fallback")
    assert data["reply"]

    # 频道内 @AI：AI 回复以 ai_agent 身份写入频道
    channels = (await client.get("/api/v1/channels", headers=_h(admin_t))).json()["data"]
    ch = next(c for c in channels if c["name"] == "应急响应组")
    resp = await client.post("/api/v1/ai/invoke", headers=_h(admin_t), json={"query": "分析这个告警", "channel_id": ch["id"]})
    assert resp.json()["code"] == 0
    msgs = (await client.get(f"/api/v1/channels/{ch['id']}/messages", headers=_h(admin_t))).json()["data"]["items"]
    assert any(m["sender_type"] == "ai_agent" for m in msgs)


@pytest.mark.asyncio
async def test_contact_flow(client):
    """联系人双向确认：未同意前无法私聊；同意后建立联系人且私聊唯一；可拒绝。"""
    admin_t = await _login(client, "admin", "admin123")
    manager_t = await _login(client, "manager01")
    analyst_t = await _login(client, "analyst01")
    manager_id = await _user_id(client, admin_t, "manager01")
    analyst_id = await _user_id(client, admin_t, "analyst01")

    # 未添加联系人的情况下直接私聊 → 40301
    resp = await client.post("/api/v1/channels/dm", headers=_h(manager_t), json={"user_id": analyst_id})
    assert resp.json()["code"] == E_FORBIDDEN, resp.json()

    # 主管向分析师发起添加请求
    resp = await client.post("/api/v1/chat/contacts/requests", headers=_h(manager_t), json={"target_id": analyst_id})
    assert resp.json()["code"] == 0, resp.json()
    # 重复发起 → 40900（已有待处理请求）
    resp = await client.post("/api/v1/chat/contacts/requests", headers=_h(manager_t), json={"target_id": analyst_id})
    assert resp.json()["code"] == E_CONFLICT, resp.json()

    # 分析师收到请求，但反向未添加 → 仍无法私聊
    pending = (await client.get("/api/v1/chat/contacts/requests", headers=_h(analyst_t))).json()["data"]
    assert len(pending) == 1 and pending[0]["requester_username"] == "manager01"
    resp = await client.post("/api/v1/channels/dm", headers=_h(analyst_t), json={"user_id": manager_id})
    assert resp.json()["code"] == E_FORBIDDEN, resp.json()

    # 分析师同意 → 建立双向联系人
    req_id = pending[0]["id"]
    resp = await client.post(f"/api/v1/chat/contacts/requests/{req_id}/accept", headers=_h(analyst_t))
    assert resp.json()["code"] == 0
    for tok in (manager_t, analyst_t):
        contacts = (await client.get("/api/v1/chat/contacts", headers=_h(tok))).json()["data"]
        assert len(contacts) == 1, contacts

    # 同意后双方均可私聊，且为同一频道
    dm_m = (await client.post("/api/v1/channels/dm", headers=_h(manager_t), json={"user_id": analyst_id})).json()["data"]
    dm_a = (await client.post("/api/v1/channels/dm", headers=_h(analyst_t), json={"user_id": manager_id})).json()["data"]
    assert dm_m["id"] == dm_a["id"]
    assert dm_m["type"] == "private"

    # 第三方（学员，未加入）访问该私聊 → 无权
    trainee_t = await _login(client, "trainee01")
    resp = await client.get(f"/api/v1/channels/{dm_m['id']}/messages", headers=_h(trainee_t))
    assert resp.json()["code"] == E_FORBIDDEN

    # 拒绝流程：主管向学员发起 → 学员拒绝 → 请求消失
    t01_id = await _user_id(client, admin_t, "trainee01")
    resp = await client.post("/api/v1/chat/contacts/requests", headers=_h(manager_t), json={"target_id": t01_id})
    assert resp.json()["code"] == 0, resp.json()
    trainee_t = await _login(client, "trainee01")
    pending = (await client.get("/api/v1/chat/contacts/requests", headers=_h(trainee_t))).json()["data"]
    req_id = next(r for r in pending if r["requester_username"] == "manager01")["id"]
    resp = await client.post(f"/api/v1/chat/contacts/requests/{req_id}/reject", headers=_h(trainee_t))
    assert resp.json()["code"] == 0
    pending = (await client.get("/api/v1/chat/contacts/requests", headers=_h(trainee_t))).json()["data"]
    assert all(r["requester_username"] != "manager01" for r in pending)


@pytest.mark.asyncio
async def test_trainee_contact_restrictions(client):
    """学员限制：仅可添加/私聊学员、仅可加入学员社区；同意后学员间私聊可用。"""
    admin_t = await _login(client, "admin", "admin123")
    trainee_t = await _login(client, "trainee01")
    manager_id = await _user_id(client, admin_t, "manager01")
    t01_id = await _user_id(client, admin_t, "trainee01")
    # 保证存在 trainee02（幂等）
    t02 = await _user_id(client, admin_t, "trainee02")

    # 学员添加主管为联系人 → 40301
    resp = await client.post("/api/v1/chat/contacts/requests", headers=_h(trainee_t), json={"target_id": manager_id})
    assert resp.json()["code"] == E_FORBIDDEN, resp.json()
    # 学员直接私聊主管 → 40301
    resp = await client.post("/api/v1/channels/dm", headers=_h(trainee_t), json={"user_id": manager_id})
    assert resp.json()["code"] == E_FORBIDDEN, resp.json()

    # 学员向学员发起添加 → 对方同意 → 建立联系人
    resp = await client.post("/api/v1/chat/contacts/requests", headers=_h(trainee_t), json={"target_id": t02})
    assert resp.json()["code"] == 0, resp.json()
    t02_t = await _login(client, "trainee02")
    pending = (await client.get("/api/v1/chat/contacts/requests", headers=_h(t02_t))).json()["data"]
    req_id = next(r for r in pending if r["requester_id"] == t01_id)["id"]
    resp = await client.post(f"/api/v1/chat/contacts/requests/{req_id}/accept", headers=_h(t02_t))
    assert resp.json()["code"] == 0

    # 同意前学员间私聊被拒（回归：需先建立联系人）→ 已在 contact_flow 覆盖；这里验证同意后可私聊
    resp = await client.post("/api/v1/channels/dm", headers=_h(trainee_t), json={"user_id": t02})
    assert resp.json()["code"] == 0, resp.json()
    dm = resp.json()["data"]

    # 学员群组列表不含私聊（群组列表仅含群组），但作为成员仍可访问该私聊频道
    channels = (await client.get("/api/v1/channels", headers=_h(trainee_t))).json()["data"]
    assert all(c["type"] != "private" for c in channels)
    assert dm["id"] not in [c["id"] for c in channels]
    r = await client.post(f"/api/v1/channels/{dm['id']}/messages", headers=_h(trainee_t), json={"content": "学员间私聊回归"})
    assert r.json()["code"] == 0, r.json()
    msgs = (await client.get(f"/api/v1/channels/{dm['id']}/messages", headers=_h(trainee_t))).json()["data"]["items"]
    assert any(m["content"] == "学员间私聊回归" for m in msgs)

    # 另一学员（trainee02）可访问该私聊（双方均为成员）
    msgs = (await client.get(f"/api/v1/channels/{dm['id']}/messages", headers=_h(t02_t))).json()["data"]["items"]
    assert isinstance(msgs, list)


@pytest.mark.asyncio
async def test_admin_monitors_all_channels(client):
    """管理员监控：非成员也可查看他人私聊频道与消息；但私聊需联系人（与普通用户一致）。"""
    admin_t = await _login(client, "admin", "admin123")
    admin_id = await _user_id(client, admin_t, "admin")
    manager_t = await _login(client, "manager01")
    analyst_t = await _login(client, "analyst01")
    analyst_id = await _user_id(client, admin_t, "analyst01")
    manager_id = await _user_id(client, admin_t, "manager01")

    # 主管与分析师经联系人确认建立私聊并发言（管理员非成员）
    await _establish_contact(client, manager_t, manager_id, analyst_t, analyst_id)
    dm = (await client.post("/api/v1/channels/dm", headers=_h(manager_t), json={"user_id": analyst_id})).json()["data"]
    dm_id = dm["id"]
    await client.post(f"/api/v1/channels/{dm_id}/messages", headers=_h(manager_t), json={"content": "监控可见机密"})

    # 管理员频道列表包含该私聊（豁免：非成员可见全部）
    channels = (await client.get("/api/v1/channels", headers=_h(admin_t))).json()["data"]
    assert any(c["id"] == dm_id and c["type"] == "private" for c in channels)
    # 非管理员频道列表仅含群组（不含他人私聊）→ manager 列表不含该私聊
    channels = (await client.get("/api/v1/channels", headers=_h(manager_t))).json()["data"]
    assert all(c["type"] != "private" for c in channels)
    assert dm_id not in [c["id"] for c in channels]
    msgs = (await client.get(f"/api/v1/channels/{dm_id}/messages", headers=_h(admin_t))).json()["data"]["items"]
    assert any(m["content"] == "监控可见机密" for m in msgs)

    # 管理员与普通用户一致：未添加联系人不能私聊
    resp = await client.post("/api/v1/channels/dm", headers=_h(admin_t), json={"user_id": analyst_id})
    assert resp.json()["code"] == E_FORBIDDEN, resp.json()
    # 建立联系人后 admin 可与 analyst 私聊（独立于 manager-analyst 私聊）
    await _establish_contact(client, admin_t, admin_id, analyst_t, analyst_id)
    resp = await client.post("/api/v1/channels/dm", headers=_h(admin_t), json={"user_id": analyst_id})
    assert resp.json()["code"] == 0, resp.json()
    assert resp.json()["data"]["id"] != dm_id

    # 审计员（无聊天权限）尝试读取该私聊 → 40302
    auditor_t = await _login(client, "auditor01")
    resp = await client.get(f"/api/v1/channels/{dm_id}/messages", headers=_h(auditor_t))
    assert resp.json()["code"] == E_FORBIDDEN_PERM


@pytest.mark.asyncio
async def test_community_cross_role(client):
    """学员社区跨角色群聊：其他角色加入后可读可发；学员可读到。"""
    admin_t = await _login(client, "admin", "admin123")
    manager_t = await _login(client, "manager01")
    trainee_t = await _login(client, "trainee01")

    # 主管加入学员社区 → 可读取并可发言
    resp = await _join(client, manager_t, "学员社区")
    assert resp.json()["code"] == 0, resp.json()
    community = resp.json()["data"]
    assert community["type"] == "trainee"

    msgs = (await client.get(f"/api/v1/channels/{community['id']}/messages", headers=_h(manager_t))).json()["data"]["items"]
    assert isinstance(msgs, list)
    resp = await client.post(f"/api/v1/channels/{community['id']}/messages", headers=_h(manager_t), json={"content": "导师在社区发言"})
    assert resp.json()["code"] == 0

    # 学员加入学员社区 → 可读到主管的发言（跨角色可见）
    resp = await _join(client, trainee_t, "学员社区")
    assert resp.json()["code"] == 0, resp.json()
    trainee_channels = (await client.get("/api/v1/channels", headers=_h(trainee_t))).json()["data"]
    assert "学员社区" in {c["name"] for c in trainee_channels}
    tmsgs = (await client.get(f"/api/v1/channels/{community['id']}/messages", headers=_h(trainee_t))).json()["data"]["items"]
    assert any(m["content"] == "导师在社区发言" for m in tmsgs)
