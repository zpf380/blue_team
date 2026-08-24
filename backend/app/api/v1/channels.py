"""聊天频道与消息 API：角色隔离 / 收发 / 已读 / 撤回 / 全文检索 / 私聊(DM)。"""
import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_user_agent, require_permission
from app.core.exceptions import AppError, ERR_CONFLICT, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_RATE_LIMIT, ERR_VALIDATION, ok_response
from app.db.session import get_db
from app.models import Channel, ChannelMember, Contact, ContactRequest, Message, Role, User
from app.schemas.chat import (
    ChannelCreate,
    ChannelOut,
    ContactOut,
    ContactRequestIn,
    ContactRequestOut,
    DMIn,
    JoinChannelIn,
    MessageCreate,
    MessageOut,
)
from app.services.audit_log import record
from app.ws.manager import manager

router = APIRouter(tags=["聊天"])


def _role(user: User) -> str:
    return user._role.code if user._role else ""


async def _get_channel(session: AsyncSession, channel_id: int, user: User) -> Channel:
    """频道访问控制：
    - 管理员：可访问任意频道（含他人私聊），用于监控全部聊天记录；
    - 其他角色：必须为频道成员（群组经「输入名称加入」，私聊经联系人建立）。
    """
    channel = await session.get(Channel, channel_id)
    if not channel or channel.is_archived:
        raise AppError(code=ERR_NOT_FOUND, message="频道不存在")
    if _role(user) == "admin":
        return channel
    member = (
        await session.execute(
            select(ChannelMember).where(
                ChannelMember.channel_id == channel_id, ChannelMember.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise AppError(code=ERR_FORBIDDEN, message="无权访问该频道")
    return channel


def _message_out(m: Message, sender_name: str | None = None) -> dict:
    if not sender_name:
        sender_name = f"AI·{m.ai_agent_name}" if m.ai_agent_name else None
    return MessageOut(
        id=m.id,
        channel_id=m.channel_id,
        sender_id=m.sender_id,
        sender_name=sender_name,
        sender_type=m.sender_type,
        ai_agent_name=m.ai_agent_name,
        message_type=m.message_type,
        content=m.content,
        file_url=m.file_url,
        file_name=m.file_name,
        parent_id=m.parent_id,
        mentions=m.mentions,
        is_deleted=m.is_deleted,
        created_at=m.created_at,
    ).model_dump(mode="json")


async def create_message(
    session: AsyncSession, user: User, channel: Channel, data: MessageCreate, sender_type: str = "user", ai_agent_name: str | None = None,
) -> Message:
    """持久化消息 → 广播到频道 → @提及推送。REST 与 WS 共用。"""
    msg = Message(
        channel_id=channel.id,
        sender_id=user.id,
        sender_type=sender_type,
        ai_agent_name=ai_agent_name,
        message_type=data.message_type,
        content=data.content,
        file_url=data.file_url,
        file_name=data.file_name,
        parent_id=data.parent_id,
        mentions=data.mentions,
    )
    session.add(msg)
    await session.flush()
    out = _message_out(msg, user.real_name or user.username)
    await session.commit()
    await session.refresh(msg)
    out = _message_out(msg, user.real_name or user.username)
    await manager.broadcast(channel.id, {"type": "message", "data": out})
    if data.mentions and sender_type == "user":
        for uid in data.mentions:
            await manager.send_to_user(uid, {
                "type": "mention",
                "data": {
                    "channel_id": channel.id,
                    "channel_name": channel.name,
                    "message_id": msg.id,
                    "from": user.username,
                    "preview": (data.content or "")[:80],
                },
            })
    return msg


# ---------- 频道 ----------
@router.get("/channels")
async def list_channels(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    role = _role(user)
    if role == "admin":
        # 管理员监控：可见全部频道（含他人私聊频道）
        visible = select(Channel.id).where(Channel.is_archived.is_(False))
    else:
        # 普通角色：群组列表，仅显示已加入的群组（不含私聊；私聊经联系人建立）
        visible = select(Channel.id).where(
            Channel.is_archived.is_(False),
            Channel.type != "private",
            Channel.id.in_(select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)),
        )
    channels = (await session.execute(select(Channel).where(Channel.id.in_(visible)).order_by(Channel.id))).scalars().all()
    member_counts = {
        c.channel_id: c.cnt
        for c in (
            await session.execute(
                select(ChannelMember.channel_id, func.count().label("cnt"))
                .where(ChannelMember.channel_id.in_([ch.id for ch in channels]))
                .group_by(ChannelMember.channel_id)
            )
        ).all()
    }
    memberships = {
        m.channel_id: m
        for m in (
            await session.execute(select(ChannelMember).where(ChannelMember.user_id == user.id))
        ).scalars()
    }
    # 每条频道最新消息（预览 + 未读数）
    items: list[ChannelOut] = []
    for ch in channels:
        last = (
            await session.execute(
                select(Message)
                .where(Message.channel_id == ch.id, Message.is_deleted.is_(False))
                .order_by(Message.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        unread = 0
        mem = memberships.get(ch.id)
        if mem and mem.last_read_at:
            unread = (
                await session.execute(
                    select(func.count()).select_from(Message).where(
                        Message.channel_id == ch.id,
                        Message.created_at > mem.last_read_at,
                        Message.is_deleted.is_(False),
                        Message.sender_id != user.id,
                    )
                )
            ).scalar_one()
        items.append(ChannelOut(
            id=ch.id, name=ch.name, type=ch.type, description=ch.description,
            creator_id=ch.creator_id, member_count=member_counts.get(ch.id, 0),
            unread_count=unread,
            last_message=(last.content or "")[:60] if last else None,
            last_message_at=last.created_at if last else None,
            created_at=ch.created_at,
        ))
    return ok_response(data=items)


@router.post("/channels")
async def create_channel(
    data: ChannelCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:channel")),
):
    # 学员只能创建学员社区频道，防止绕过隔离规则
    if _role(user) == "trainee" and data.type != "trainee":
        raise AppError(code=ERR_FORBIDDEN, message="学员仅可创建学员社区频道")
    channel = Channel(name=data.name, type=data.type, description=data.description, creator_id=user.id)
    session.add(channel)
    await session.flush()
    session.add(ChannelMember(channel_id=channel.id, user_id=user.id, role="owner"))
    await record(
        session, user, "chat:channel:create", target_type="channel", target_id=str(channel.id),
        detail={"name": data.name, "type": data.type}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data=ChannelOut(id=channel.id, name=channel.name, type=channel.type, description=channel.description, creator_id=channel.creator_id, member_count=1).model_dump())


@router.post("/channels/join")
async def join_channel(
    data: JoinChannelIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    """输入群组名称加入：加入后出现在自己的频道列表，可查看/发送消息。"""
    name = data.name.strip()
    channel = (
        await session.execute(
            select(Channel).where(Channel.name == name, Channel.is_archived.is_(False))
        )
    ).scalar_one_or_none()
    if not channel:
        raise AppError(code=ERR_NOT_FOUND, message="未找到该群组")
    if _role(user) == "trainee" and channel.type != "trainee":
        raise AppError(code=ERR_FORBIDDEN, message="学员仅可加入学员社区")
    member = (
        await session.execute(
            select(ChannelMember).where(
                ChannelMember.channel_id == channel.id, ChannelMember.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if not member:
        session.add(ChannelMember(channel_id=channel.id, user_id=user.id, role="member"))
        await record(
            session, user, "chat:channel:join", target_type="channel", target_id=str(channel.id),
            detail={"name": channel.name, "type": channel.type},
            ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
        )
        await session.commit()
    member_count = (
        await session.execute(
            select(func.count()).select_from(ChannelMember).where(ChannelMember.channel_id == channel.id)
        )
    ).scalar_one()
    return ok_response(data=ChannelOut(
        id=channel.id, name=channel.name, type=channel.type, description=channel.description,
        creator_id=channel.creator_id, member_count=member_count,
    ).model_dump())


@router.get("/channels/{channel_id}/members")
async def channel_members(
    channel_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    await _get_channel(session, channel_id, user)
    rows = (
        await session.execute(
            select(User).join(ChannelMember, ChannelMember.user_id == User.id).where(ChannelMember.channel_id == channel_id)
        )
    ).scalars().all()
    return ok_response(data=[{"id": u.id, "username": u.username, "real_name": u.real_name, "role": u.role.name if u.role else None} for u in rows])


# ---------- 消息 ----------
@router.get("/channels/{channel_id}/messages")
async def list_messages(
    channel_id: int,
    before_id: int | None = None,
    size: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    await _get_channel(session, channel_id, user)
    # 自动加入（记录已读游标），不存在则创建成员记录
    member = (
        await session.execute(select(ChannelMember).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user.id))
    ).scalar_one_or_none()
    now = dt.datetime.now(dt.timezone.utc)
    if member:
        member.last_read_at = now
    else:
        session.add(ChannelMember(channel_id=channel_id, user_id=user.id, role="member", last_read_at=now))
    await session.commit()

    query = select(Message).where(Message.channel_id == channel_id)
    if before_id:
        query = query.where(Message.id < before_id)
    rows = (await session.execute(query.order_by(Message.id.desc()).limit(size))).scalars().all()
    rows.reverse()
    sender_ids = {m.sender_id for m in rows if m.sender_id}
    names = {}
    if sender_ids:
        names = {u.id: (u.real_name or u.username) for u in (await session.execute(select(User).where(User.id.in_(sender_ids)))).scalars()}
    return ok_response(data={"items": [_message_out(m, names.get(m.sender_id)) for m in rows]})


@router.post("/channels/{channel_id}/messages")
async def send_message(
    channel_id: int,
    data: MessageCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    channel = await _get_channel(session, channel_id, user)
    if not data.content and not data.file_url:
        raise AppError(code=ERR_VALIDATION, message="消息内容为空")
    msg = await create_message(session, user, channel, data)
    return ok_response(data=_message_out(msg, user.real_name or user.username))


@router.post("/channels/{channel_id}/read")
async def mark_read(
    channel_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    await _get_channel(session, channel_id, user)
    member = (
        await session.execute(select(ChannelMember).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user.id))
    ).scalar_one_or_none()
    if member:
        member.last_read_at = dt.datetime.now(dt.timezone.utc)
        await session.commit()
    return ok_response()


@router.post("/messages/{message_id}/recall")
async def recall_message(
    message_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    msg = await session.get(Message, message_id)
    if not msg or msg.is_deleted:
        raise AppError(code=ERR_NOT_FOUND, message="消息不存在")
    if msg.sender_id != user.id:
        raise AppError(code=ERR_FORBIDDEN, message="只能撤回自己的消息")
    if msg.created_at and (dt.datetime.now(dt.timezone.utc) - msg.created_at) > dt.timedelta(hours=24):
        raise AppError(code=ERR_FORBIDDEN, message="超过 24 小时无法撤回")
    msg.is_deleted = True
    msg.content = None
    await session.commit()
    await manager.broadcast(msg.channel_id, {"type": "recall", "data": {"message_id": message_id}})
    return ok_response()


@router.get("/chat/search")
async def search_messages(
    q: str,
    channel_id: int | None = None,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:view")),
):
    q = q.strip()
    if not q:
        return ok_response(data=[])
    if len(q) > 100:
        raise AppError(code=ERR_VALIDATION, message="搜索关键词过长（最长 100 字）")
    query = select(Message).where(Message.is_deleted.is_(False))
    if channel_id:
        await _get_channel(session, channel_id, user)
        query = query.where(Message.channel_id == channel_id)
    else:
        role = _role(user)
        if role == "admin":
            visible = select(Channel.id).where(Channel.is_archived.is_(False))
        else:
            # 普通角色：仅检索已加入的群组（不含私聊）
            visible = select(Channel.id).where(
                Channel.is_archived.is_(False),
                Channel.type != "private",
                Channel.id.in_(select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)),
            )
        query = query.where(Message.channel_id.in_(visible))
    # 中文子串用 ILIKE（simple 分词对 CJK 无效），拉丁词走 GIN tsvector
    tsquery = func.to_tsvector("simple", func.coalesce(Message.content, ""))
    query = query.where(
        or_(
            tsquery.op("@@", is_comparison=True)(func.plainto_tsquery("simple", q)),
            Message.content.ilike(f"%{q}%"),
        )
    )
    rows = (await session.execute(query.order_by(Message.created_at.desc()).limit(50))).scalars().all()
    sender_ids = {m.sender_id for m in rows if m.sender_id}
    names = {}
    if sender_ids:
        names = {u.id: (u.real_name or u.username) for u in (await session.execute(select(User).where(User.id.in_(sender_ids)))).scalars()}
    return ok_response(data=[_message_out(m, names.get(m.sender_id)) for m in rows])


# ---------- 私聊（DM） ----------
@router.get("/chat/users")
async def dm_candidates(
    keyword: str | None = None,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    """私聊候选用户：在职/休假用户，可排除自己；学员仅能选择学员。"""
    query = select(User).where(User.status.in_(["active", "on_leave"]), User.id != user.id)
    if _role(user) == "trainee":
        # 单向限制：学员只能私聊学员（非学员主动私聊学员不受限）
        query = query.join(Role, Role.id == User.role_id).where(Role.code == "trainee")
    if keyword:
        like = f"%{keyword}%"
        query = query.where(or_(User.username.ilike(like), User.real_name.ilike(like)))
    rows = (await session.execute(query.order_by(User.id).limit(200))).scalars().all()
    return ok_response(data=[{"id": u.id, "username": u.username, "real_name": u.real_name, "role": u.role.name if u.role else None} for u in rows])


@router.post("/channels/dm")
async def dm_channel(
    data: DMIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    if data.user_id == user.id:
        raise AppError(code=ERR_VALIDATION, message="不能与自己私聊")
    target = await session.get(User, data.user_id)
    if not target or target.status not in ("active", "on_leave"):
        raise AppError(code=ERR_NOT_FOUND, message="用户不存在")
    # 单向限制：学员不能主动与非学员建立私聊；非学员主动私聊学员不受限
    if _role(user) == "trainee":
        target_role = await session.get(Role, target.role_id) if target.role_id else None
        if not target_role or target_role.code != "trainee":
            raise AppError(code=ERR_FORBIDDEN, message="学员仅可与其他学员私聊")
    # 私聊需互为联系人（添加后经对方同意建立）；管理员与普通用户一致
    contact = (
        await session.execute(
            select(Contact).where(Contact.user_id == user.id, Contact.contact_id == data.user_id)
        )
    ).scalar_one_or_none()
    if not contact:
        raise AppError(code=ERR_FORBIDDEN, message="请先添加对方为联系人")
    my_channels = select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)
    candidates = (
        await session.execute(
            select(Channel).where(Channel.type == "private", Channel.is_archived.is_(False), Channel.id.in_(my_channels))
        )
    ).scalars().all()
    for ch in candidates:
        ids = set(
            (await session.execute(select(ChannelMember.user_id).where(ChannelMember.channel_id == ch.id))).scalars()
        )
        if ids == {user.id, data.user_id}:
            return ok_response(data={"id": ch.id, "name": ch.name, "type": "private", "member_count": 2})
    channel = Channel(name=f"私聊 {target.real_name or target.username}", type="private", creator_id=user.id)
    session.add(channel)
    await session.flush()
    session.add_all([
        ChannelMember(channel_id=channel.id, user_id=user.id, role="owner"),
        ChannelMember(channel_id=channel.id, user_id=data.user_id, role="member"),
    ])
    await session.commit()
    return ok_response(data={"id": channel.id, "name": channel.name, "type": "private", "member_count": 2})


# ---------- 联系人（添加需对方同意，同意后双向建立） ----------
@router.get("/chat/contacts")
async def list_contacts(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    rows = (
        await session.execute(
            select(Contact, User)
            .join(User, User.id == Contact.contact_id)
            .where(Contact.user_id == user.id)
            .order_by(Contact.id.desc())
        )
    ).all()
    return ok_response(data=[
        ContactOut(
            id=u.id, username=u.username, real_name=u.real_name,
            role_name=u.role.name if u.role else None, added_at=c.created_at,
        ).model_dump(mode="json")
        for c, u in rows
    ])


@router.post("/chat/contacts/requests")
async def send_contact_request(
    data: ContactRequestIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    if data.target_id == user.id:
        raise AppError(code=ERR_VALIDATION, message="不能添加自己为联系人")
    target = await session.get(User, data.target_id)
    if not target or target.status not in ("active", "on_leave"):
        raise AppError(code=ERR_NOT_FOUND, message="用户不存在")
    if _role(user) == "trainee":
        target_role = await session.get(Role, target.role_id) if target.role_id else None
        if not target_role or target_role.code != "trainee":
            raise AppError(code=ERR_FORBIDDEN, message="学员仅可添加学员为联系人")
    existing = (
        await session.execute(
            select(Contact).where(
                or_(
                    and_(Contact.user_id == user.id, Contact.contact_id == target.id),
                    and_(Contact.user_id == target.id, Contact.contact_id == user.id),
                )
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise AppError(code=ERR_CONFLICT, message="已是联系人")
    pending = (
        await session.execute(
            select(ContactRequest).where(
                ContactRequest.status == "pending",
                or_(
                    and_(ContactRequest.requester_id == user.id, ContactRequest.target_id == target.id),
                    and_(ContactRequest.requester_id == target.id, ContactRequest.target_id == user.id),
                ),
            )
        )
    ).scalar_one_or_none()
    if pending:
        raise AppError(code=ERR_CONFLICT, message="已有待处理的添加请求")
    # 频率限制：10 分钟内发出的添加请求不超过 20 条，防联系人轰炸
    recent_sent = (
        await session.execute(
            select(func.count()).select_from(ContactRequest).where(
                ContactRequest.requester_id == user.id,
                ContactRequest.created_at >= dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10),
            )
        )
    ).scalar_one()
    if recent_sent >= 20:
        raise AppError(code=ERR_RATE_LIMIT, message="添加联系人请求过于频繁，请稍后再试")
    req = ContactRequest(requester_id=user.id, target_id=target.id, status="pending")
    session.add(req)
    await record(
        session, user, "chat:contact:request", target_type="user", target_id=str(target.id),
        detail={"target": target.username},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"id": req.id, "status": "pending"})


@router.get("/chat/contacts/requests")
async def list_contact_requests(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    rows = (
        await session.execute(
            select(ContactRequest, User)
            .join(User, User.id == ContactRequest.requester_id)
            .where(ContactRequest.target_id == user.id, ContactRequest.status == "pending")
            .order_by(ContactRequest.id.desc())
        )
    ).all()
    return ok_response(data=[
        ContactRequestOut(
            id=req.id, requester_id=u.id, requester_username=u.username,
            requester_real_name=u.real_name,
            requester_role_name=u.role.name if u.role else None,
            status=req.status, created_at=req.created_at,
        ).model_dump(mode="json")
        for req, u in rows
    ])


@router.post("/chat/contacts/requests/{request_id}/accept")
async def accept_contact_request(
    request_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    req = await session.get(ContactRequest, request_id)
    if not req or req.target_id != user.id or req.status != "pending":
        raise AppError(code=ERR_NOT_FOUND, message="请求不存在")
    session.add(Contact(user_id=user.id, contact_id=req.requester_id))
    session.add(Contact(user_id=req.requester_id, contact_id=user.id))
    req.status = "accepted"
    await record(
        session, user, "chat:contact:accept", target_type="user", target_id=str(req.requester_id),
        detail={"requester": req.requester_id},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response()


@router.post("/chat/contacts/requests/{request_id}/reject")
async def reject_contact_request(
    request_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    req = await session.get(ContactRequest, request_id)
    if not req or req.target_id != user.id or req.status != "pending":
        raise AppError(code=ERR_NOT_FOUND, message="请求不存在")
    req.status = "rejected"
    await session.commit()
    return ok_response()


@router.delete("/chat/contacts/{contact_id}")
async def remove_contact(
    contact_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:dm")),
):
    contact = (
        await session.execute(
            select(Contact).where(Contact.user_id == user.id, Contact.contact_id == contact_id)
        )
    ).scalar_one_or_none()
    if not contact:
        raise AppError(code=ERR_NOT_FOUND, message="联系人不存在")
    await session.delete(contact)
    await record(
        session, user, "chat:contact:remove", target_type="user", target_id=str(contact_id),
        detail={}, ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response()
