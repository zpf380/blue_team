"""add network_discoveries.hosts (在线终端元数据 IP/MAC/vendor)

Revision ID: b2c3d4e5f6a7b8c9
Revises: a9b8c7d6e5f4a3b2
Create Date: 2026-08-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c3d4e5f6a7b8c9"
down_revision = "a9b8c7d6e5f4a3b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "network_discoveries",
        sa.Column("hosts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("network_discoveries", "hosts")
