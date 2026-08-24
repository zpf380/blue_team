"""AI 助手接口：POST /ai/invoke —— 会话上下文持久化 + 频道内回复 + 降级展示。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.channels import _get_channel, create_message
from app.core.dependencies import get_client_ip, get_user_agent, require_permission
from app.core.exceptions import AppError, ERR_FORBIDDEN, ERR_NOT_FOUND, ok_response
from app.db.session import get_db
from app.models import AIConversation, User
from app.schemas.chat import AIChatIn, AIConversationDetail, AIConversationOut, MessageCreate
from app.services.ai_gateway import gateway, trim_history
from app.services.audit_log import record

router = APIRouter(tags=["AI 助手"])


@router.post("/ai/invoke")
async def ai_invoke(
    data: AIChatIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:ai")),
):
    channel = await _get_channel(session, data.channel_id, user) if data.channel_id else None

    conv = None
    if data.conversation_id:
        conv = await session.get(AIConversation, data.conversation_id)
        if conv and conv.user_id != user.id:
            raise AppError(code=ERR_FORBIDDEN, message="无权访问该会话")
    if not conv:
        conv = AIConversation(channel_id=data.channel_id, user_id=user.id, agent_name="DeepSeek", context_messages=[])
        session.add(conv)
        await session.flush()

    context = trim_history(conv.context_messages)
    reply, provider = await gateway.chat(context, data.query, data.model_pref)

    history = list(conv.context_messages or [])
    history.append({"role": "user", "content": data.query})
    history.append({"role": "assistant", "content": reply})
    conv.context_messages = trim_history(history)

    # 频道内回复：以 AI 身份写入频道并广播（含 WS 推送）
    if channel:
        await create_message(
            session, user, channel,
            MessageCreate(content=reply, message_type="text"),
            sender_type="ai_agent", ai_agent_name=provider,
        )
    else:
        await session.commit()

    return ok_response(data={"reply": reply, "provider": provider, "conversation_id": conv.id})


def _conv_title(conv: AIConversation) -> str:
    """会话标题 = 首条 user 消息预览。"""
    for m in conv.context_messages or []:
        if m.get("role") == "user" and m.get("content"):
            return str(m["content"])[:60]
    return "新会话"


@router.get("/ai/conversations")
async def list_ai_conversations(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:ai")),
):
    """我的 AI 助手会话列表（不含频道内 AI 回复会话），最近更新在前。"""
    rows = (
        await session.execute(
            select(AIConversation)
            .where(AIConversation.user_id == user.id, AIConversation.channel_id.is_(None))
            .order_by(AIConversation.updated_at.desc(), AIConversation.id.desc())
        )
    ).scalars().all()
    items = [
        AIConversationOut(
            id=c.id,
            title=_conv_title(c),
            message_count=len([m for m in (c.context_messages or []) if m.get("role") == "user"]),
            created_at=c.created_at,
            updated_at=c.updated_at,
        ).model_dump()
        for c in rows
    ]
    return ok_response(data={"items": items, "total": len(items)})


async def _get_own_conversation(session: AsyncSession, conversation_id: int, user: User) -> AIConversation:
    """取当前用户的可访问会话；不存在/他人/频道内会话一律 404（不泄露存在性）。"""
    conv = await session.get(AIConversation, conversation_id)
    if not conv or conv.user_id != user.id or conv.channel_id is not None:
        raise AppError(code=ERR_NOT_FOUND, message="会话不存在")
    return conv


@router.get("/ai/conversations/{conversation_id}")
async def get_ai_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:ai")),
):
    """会话详情：返回 context_messages（role/content 正序），前端据此还原对话。"""
    conv = await _get_own_conversation(session, conversation_id, user)
    return ok_response(
        data=AIConversationDetail(
            id=conv.id,
            title=_conv_title(conv),
            messages=conv.context_messages or [],
            created_at=conv.created_at,
            updated_at=conv.updated_at,
        ).model_dump()
    )


@router.delete("/ai/conversations/{conversation_id}")
async def delete_ai_conversation(
    conversation_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:ai")),
):
    """删除我的某个会话。"""
    conv = await _get_own_conversation(session, conversation_id, user)
    title = _conv_title(conv)
    await session.delete(conv)
    await record(
        session, user, "chat:ai:conversation:delete", target_type="ai_conversation",
        target_id=str(conversation_id), detail={"title": title},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"deleted": conversation_id})
