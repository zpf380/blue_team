"""add network_discoveries (网络发现任务)

Revision ID: a9b8c7d6e5f4a3b2
Revises: f1a2b3c4d5e6f7a8
Create Date: 2026-08-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a9b8c7d6e5f4a3b2"
down_revision = "f1a2b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "network_discoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subnet_id", sa.Integer(), sa.ForeignKey("ip_subnets.id"), nullable=True),
        sa.Column("network", postgresql.CIDR(), nullable=False),
        sa.Column("scan_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("online_ips", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("unregistered_ips", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("registered_ips", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("offline_ips", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_discovery_subnet_status", "network_discoveries", ["subnet_id", "scan_status"])


def downgrade() -> None:
    op.drop_index("idx_discovery_subnet_status", table_name="network_discoveries")
    op.drop_table("network_discoveries")
