"""聊天子系统 Schema。"""
import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(default="public", pattern="^(public|private|trainee)$")
    description: Optional[str] = None


class ChannelOut(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    creator_id: Optional[int] = None
    member_count: int = 0
    unread_count: int = 0
    last_message: Optional[str] = None
    last_message_at: Optional[dt.datetime] = None
    created_at: Optional[dt.datetime] = None


class MessageCreate(BaseModel):
    content: str = Field(default="", max_length=20000)
    message_type: str = Field(default="text", pattern="^(text|image|file|alert|system)$")
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    parent_id: Optional[int] = None
    mentions: Optional[list[int]] = None  # 被 @ 的用户 id 列表


class MessageOut(BaseModel):
    id: int
    channel_id: Optional[int] = None
    sender_id: Optional[int] = None
    sender_name: Optional[str] = None
    sender_type: str = "user"  # user / ai_agent / system
    ai_agent_name: Optional[str] = None
    message_type: str = "text"
    content: Optional[str] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    parent_id: Optional[int] = None
    mentions: Optional[list] = None
    is_deleted: bool = False
    created_at: Optional[dt.datetime] = None


class DMIn(BaseModel):
    user_id: int


class ContactRequestIn(BaseModel):
    target_id: int


class JoinChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ContactOut(BaseModel):
    """我的联系人（对方用户信息）。"""

    id: int
    username: str
    real_name: Optional[str] = None
    role_name: Optional[str] = None
    added_at: Optional[dt.datetime] = None


class ContactRequestOut(BaseModel):
    """收到的添加联系人请求。"""

    id: int
    requester_id: int
    requester_username: str
    requester_real_name: Optional[str] = None
    requester_role_name: Optional[str] = None
    status: str = "pending"
    created_at: Optional[dt.datetime] = None


class AIChatIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    channel_id: Optional[int] = None  # 提供则在频道内回复 AI 消息
    conversation_id: Optional[int] = None  # 续接已有会话
    model_pref: Optional[str] = None  # deepseek / ollama


class AIConversationOut(BaseModel):
    """AI 助手会话列表项（仅独立助手会话，不含频道内 AI 回复）。"""

    id: int
    title: str = ""  # 首条 user 消息预览
    message_count: int = 0  # 已交互轮数（user/assistant 对数）
    created_at: Optional[dt.datetime] = None
    updated_at: Optional[dt.datetime] = None


class AIConversationDetail(BaseModel):
    """AI 助手会话详情（用于切回时还原对话）。"""

    id: int
    title: str = ""
    messages: list[dict] = []  # [{role: user|assistant, content}, ...] 按时间正序
    created_at: Optional[dt.datetime] = None
    updated_at: Optional[dt.datetime] = None
