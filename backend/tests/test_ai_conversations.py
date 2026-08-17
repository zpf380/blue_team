"""AI 助手会话管理集成测试：列表 / 详情 / 删除 / 续接 / 权限隔离。

复用 test_chat_api.py 惯例：autouse 清理 ai_conversations，admin/analyst 有 chat:ai，
trainee 无。invoke 无 DEEPSEEK_API_KEY 时走 fallback，无需真实网络。
"""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", settings.DATABASE_URL)

E_FORBIDDEN = 40301
E_FORBIDDEN_PERM = 40302
E_NOT_FOUND = 40400


@pytest.fixture(autouse=True)
async def _clean_ai():
    """每个用例前清空 AI 会话，保证确定性断言。"""
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DELETE FROM ai_conversations"))
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


async def _invoke(client, token, query, conversation_id=None):
    body = {"query": query}
    if conversation_id:
        body["conversation_id"] = conversation_id
    resp = await client.post("/api/v1/ai/invoke", headers=_h(token), json=body)
    assert resp.json()["code"] == 0, resp.json()
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_permission_roles(client):
    """admin / analyst 可用会话接口；trainee 列表/详情/删除全部 40302。"""
    admin_t = await _login(client, "admin", "admin123")
    analyst_t = await _login(client, "analyst01")
    trainee_t = await _login(client, "trainee01")

    data = await _invoke(client, analyst_t, "测试权限")
    conv_id = data["conversation_id"]
    try:
        for token in (admin_t, analyst_t):
            assert (await client.get("/api/v1/ai/conversations", headers=_h(token))).json()["code"] == 0
        for path, method in (
            ("/api/v1/ai/conversations", client.get),
            (f"/api/v1/ai/conversations/{conv_id}", client.get),
            (f"/api/v1/ai/conversations/{conv_id}", client.delete),
        ):
            resp = await method(path, headers=_h(trainee_t))
            assert resp.json()["code"] == E_FORBIDDEN_PERM, (path, resp.json())
    finally:
        await client.delete(f"/api/v1/ai/conversations/{conv_id}", headers=_h(analyst_t))


@pytest.mark.asyncio
async def test_invoke_creates_and_lists(client):
    """首次提问创建会话：返回 conversation_id，列表出现，详情含 user+assistant。"""
    token = await _login(client, "analyst01")
    data = await _invoke(client, token, "如何加固 SSH？")
    conv_id = data["conversation_id"]
    assert conv_id and data["reply"]

    items = (await client.get("/api/v1/ai/conversations", headers=_h(token))).json()["data"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == conv_id
    assert item["title"] == "如何加固 SSH？"
    assert item["message_count"] == 1

    detail = (await client.get(f"/api/v1/ai/conversations/{conv_id}", headers=_h(token))).json()["data"]
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "如何加固 SSH？"
    assert detail["messages"][1]["content"] == data["reply"]


@pytest.mark.asyncio
async def test_invoke_resumes_conversation(client):
    """带 conversation_id 续接：列表仍 1 条但轮数增加，详情含全部历史。"""
    token = await _login(client, "analyst01")
    first = await _invoke(client, token, "第一问")
    conv_id = first["conversation_id"]

    second = await _invoke(client, token, "第二问", conversation_id=conv_id)
    assert second["conversation_id"] == conv_id

    items = (await client.get("/api/v1/ai/conversations", headers=_h(token))).json()["data"]["items"]
    assert len(items) == 1 and items[0]["message_count"] == 2

    detail = (await client.get(f"/api/v1/ai/conversations/{conv_id}", headers=_h(token))).json()["data"]
    assert [m["content"] for m in detail["messages"] if m["role"] == "user"] == ["第一问", "第二问"]
    assert len(detail["messages"]) == 4


@pytest.mark.asyncio
async def test_conversation_isolation(client):
    """他人会话：列表不可见，详情/删除 40400，带他人 id 续接 40301。"""
    admin_t = await _login(client, "admin", "admin123")
    analyst_t = await _login(client, "analyst01")

    conv_id = (await _invoke(client, admin_t, "管理员的秘密"))["conversation_id"]
    try:
        items = (await client.get("/api/v1/ai/conversations", headers=_h(analyst_t))).json()["data"]["items"]
        assert all(i["id"] != conv_id for i in items)

        for method in (client.get, client.delete):
            resp = await method(f"/api/v1/ai/conversations/{conv_id}", headers=_h(analyst_t))
            assert resp.json()["code"] == E_NOT_FOUND, resp.json()

        # 带他人会话 id 续接 → 40301 无权访问
        resp = await client.post(
            "/api/v1/ai/invoke", headers=_h(analyst_t), json={"query": "续接", "conversation_id": conv_id}
        )
        assert resp.json()["code"] == E_FORBIDDEN, resp.json()
    finally:
        await client.delete(f"/api/v1/ai/conversations/{conv_id}", headers=_h(admin_t))


@pytest.mark.asyncio
async def test_channel_ai_not_in_standalone_list(client):
    """频道内 AI 回复不产生独立助手会话，也不出现在列表。"""
    token = await _login(client, "admin", "admin123")
    channels = (await client.get("/api/v1/channels", headers=_h(token))).json()["data"]
    ch = next(c for c in channels if c["name"] == "应急响应组")

    # 频道内提问 → 复用既有逻辑，不入独立会话列表
    resp = await client.post(
        "/api/v1/ai/invoke", headers=_h(token), json={"query": "分析告警", "channel_id": ch["id"]}
    )
    assert resp.json()["code"] == 0
    data = resp.json()["data"]

    # 频道内会话（channel_id 非空）在列表不可见
    assert data.get("conversation_id")
    items = (await client.get("/api/v1/ai/conversations", headers=_h(token))).json()["data"]["items"]
    assert len(items) == 0

    # 但该频道内会话 id 对列表接口所属校验下不可用（详情/删除 404）
    detail = await client.get(f"/api/v1/ai/conversations/{data['conversation_id']}", headers=_h(token))
    assert detail.json()["code"] == E_NOT_FOUND, detail.json()


@pytest.mark.asyncio
async def test_delete_conversation(client):
    """删除会话后列表消失，详情 404，可再次新建。"""
    token = await _login(client, "analyst01")
    conv_id = (await _invoke(client, token, "将被删除"))["conversation_id"]

    resp = await client.delete(f"/api/v1/ai/conversations/{conv_id}", headers=_h(token))
    assert resp.json()["code"] == 0 and resp.json()["data"]["deleted"] == conv_id

    assert (await client.get("/api/v1/ai/conversations", headers=_h(token))).json()["data"]["items"] == []
    detail = await client.get(f"/api/v1/ai/conversations/{conv_id}", headers=_h(token))
    assert detail.json()["code"] == E_NOT_FOUND, detail.json()

    # 删除后可继续新建（新会话 id 不与旧冲突）
    new_id = (await _invoke(client, token, "新会话"))["conversation_id"]
    assert new_id != conv_id
    await client.delete(f"/api/v1/ai/conversations/{new_id}", headers=_h(token))
