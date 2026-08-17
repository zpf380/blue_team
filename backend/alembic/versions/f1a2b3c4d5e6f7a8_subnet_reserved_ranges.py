"""add ip_subnets.reserved_ranges (保留地址段)

Revision ID: f1a2b3c4d5e6f7a8
Revises: e5f6a7b8c9d0e1f2
Create Date: 2026-08-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6f7a8"
down_revision = "e5f6a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ip_subnets",
        sa.Column("reserved_ranges", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ip_subnets", "reserved_ranges")
