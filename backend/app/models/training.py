"""训练子系统：智能体 / 场景 / 进度 / 沙箱会话 / 积分 / 徽章。"""
import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrainingAgent(Base):
    __tablename__ = "training_agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    prerequisites: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 前置智能体 code 列表
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")  # draft / published（学员仅见 published）
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingScenario(Base):
    __tablename__ = "training_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("training_agents.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sandbox_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 环境类型等
    points: Mapped[int] = mapped_column(Integer, default=10)
    penalty_points: Mapped[int] = mapped_column(Integer, default=5)
    time_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 分钟
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class TrainingProgress(Base):
    __tablename__ = "training_progress"
    __table_args__ = (UniqueConstraint("user_id", "scenario_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("training_scenarios.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="not_started")  # not_started/in_progress/completed/failed
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sandbox_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SandboxSession(Base):
    __tablename__ = "sandbox_sessions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("training_agents.id"), nullable=True)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("training_scenarios.id"), nullable=True)
    state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScoreRecord(Base):
    __tablename__ = "score_records"
    __table_args__ = (Index("idx_score_user_time", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    condition_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class UserBadge(Base):
    __tablename__ = "user_badges"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id"), primary_key=True)
    awarded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
