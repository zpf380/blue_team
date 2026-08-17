"""add leave_requests (休假/外勤申请)

Revision ID: d0e1f2a3b4c5d6e7
Revises: b0a1c2d3e4f50617
Create Date: 2026-08-16

"""
from alembic import op
import sqlalchemy as sa

revision = "d0e1f2a3b4c5d6e7"
down_revision = "b0a1c2d3e4f50617"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("approver_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_note", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_leave_req_user_status", "leave_requests", ["user_id", "status"])
    op.create_index("ix_leave_req_status_start", "leave_requests", ["status", "start_at"])


def downgrade() -> None:
    op.drop_index("ix_leave_req_status_start", table_name="leave_requests")
    op.drop_index("ix_leave_req_user_status", table_name="leave_requests")
    op.drop_table("leave_requests")
