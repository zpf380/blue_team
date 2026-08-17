"""add training course publish fields (训练课程发布状态)

Revision ID: e7d8c9b0a1f2e3d4
Revises: a1d2e3f4b5c6d7e8
Create Date: 2026-08-16

"""
from alembic import op
import sqlalchemy as sa

revision = "e7d8c9b0a1f2e3d4"
down_revision = "a1d2e3f4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_agents", sa.Column("status", sa.String(20), nullable=False, server_default="draft"))
    op.add_column("training_agents", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("training_agents", sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True))
    op.add_column("training_agents", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    op.drop_column("training_agents", "created_at")
    op.drop_column("training_agents", "created_by")
    op.drop_column("training_agents", "published_at")
    op.drop_column("training_agents", "status")
