"""add chat fields: channel_members.last_read_at, messages.file_name

Revision ID: a1b2c3d4e5f6
Revises: 6eb2c58c33d6
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "6eb2c58c33d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_members", sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("file_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "file_name")
    op.drop_column("channel_members", "last_read_at")
