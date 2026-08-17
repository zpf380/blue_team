"""add alerts.notified_at (外部通知发送时间)

Revision ID: b0a1c2d3e4f50617
Revises: f1e2d3c4b5a69788
Create Date: 2026-08-16

"""
from alembic import op
import sqlalchemy as sa

revision = "b0a1c2d3e4f50617"
down_revision = "f1e2d3c4b5a69788"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alerts", "notified_at")
