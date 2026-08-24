"""操作审计表（只追加，禁止 UPDATE/DELETE）与合规审计报告。"""
import datetime as dt

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditReport(Base):
    """合规审计报告快照：生成时将统计聚合落库，报告只追加不修改。"""

    __tablename__ = "audit_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)  # daily/weekly/monthly/on_demand
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    date_from: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    report_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 统计聚合快照
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    generated_by_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperationLog(Base):
    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("idx_oplog_user_time", "user_id", "created_at"),
        Index("idx_oplog_action_time", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 只追加：禁止 UPDATE / DELETE（PostgreSQL RULE，逐条 DDL 避免 asyncpg 多语句预处理限制）
from sqlalchemy.event import listen  # noqa: E402
from sqlalchemy import DDL

listen(
    OperationLog.__table__,
    "after_create",
    DDL("CREATE OR REPLACE RULE prevent_update_oplog AS ON UPDATE TO operation_logs DO INSTEAD NOTHING;"),
)
listen(
    OperationLog.__table__,
    "after_create",
    DDL("CREATE OR REPLACE RULE prevent_delete_oplog AS ON DELETE TO operation_logs DO INSTEAD NOTHING;"),
)
