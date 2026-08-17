"""考勤子系统：休假/外勤申请（LeaveRequest）。

leave_type 直接复用 User.status 的业务取值（on_leave / business_trip），
审批通过后由定时任务按 start_at/end_at 自动切换用户状态。
状态机：pending → approved → in_progress → completed；pending → rejected / cancelled
"""
import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        Index("ix_leave_req_user_status", "user_id", "status"),
        Index("ix_leave_req_status_start", "status", "start_at"),  # 定时任务扫描用
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)  # on_leave / business_trip
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requester: Mapped["User | None"] = relationship(foreign_keys=[user_id], lazy="selectin")
    approver: Mapped["User | None"] = relationship(foreign_keys=[approver_id], lazy="selectin")
