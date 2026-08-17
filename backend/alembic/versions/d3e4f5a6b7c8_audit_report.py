"""add audit_reports table for compliance reports

Revision ID: d3e4f5a6b7c8
Revises: b1c2d3e4f5a6
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("report_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("report_data", JSONB(), nullable=True),
        sa.Column("generated_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("generated_by_name", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_reports")
