"""add device offline_since / alert target_ip dedup / device_patrols (设备巡检)

Revision ID: a1d2e3f4b5c6d7e8
Revises: d0e1f2a3b4c5d6e7
Create Date: 2026-08-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CIDR, INET, JSONB

revision = "a1d2e3f4b5c6d7e8"
down_revision = "d0e1f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("offline_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alerts", sa.Column("target_ip", INET(), nullable=True))
    op.create_index("idx_alert_target_type", "alerts", ["target_ip", "alert_type"])
    op.create_table(
        "device_patrols",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subnet_id", sa.Integer, sa.ForeignKey("ip_subnets.id"), nullable=True),
        sa.Column("network", CIDR(), nullable=False),
        sa.Column("scan_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("online_ips", JSONB(), nullable=True),
        sa.Column("offline_ips", JSONB(), nullable=True),
        sa.Column("ghost_ips", JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_patrol_subnet_status", "device_patrols", ["subnet_id", "scan_status"])


def downgrade() -> None:
    op.drop_index("idx_patrol_subnet_status", table_name="device_patrols")
    op.drop_table("device_patrols")
    op.drop_index("idx_alert_target_type", table_name="alerts")
    op.drop_column("alerts", "target_ip")
    op.drop_column("devices", "offline_since")
