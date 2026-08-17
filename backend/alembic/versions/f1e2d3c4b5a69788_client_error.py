"""add client_error_reports (前端运行时错误上报)

Revision ID: f1e2d3c4b5a69788
Revises: e7f8a9b0c1d2e3f4
Create Date: 2026-08-16

"""
from alembic import op
import sqlalchemy as sa

revision = "f1e2d3c4b5a69788"
down_revision = "e7f8a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_error_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("message", sa.String(length=1000), nullable=True),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("client_error_reports")
