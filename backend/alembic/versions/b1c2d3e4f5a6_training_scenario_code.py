"""add training_scenarios.code for stable seeding

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_scenarios", sa.Column("code", sa.String(length=50), nullable=True))
    op.create_unique_constraint("uq_training_scenarios_code", "training_scenarios", ["code"])


def downgrade() -> None:
    op.drop_constraint("uq_training_scenarios_code", "training_scenarios", type_="unique")
    op.drop_column("training_scenarios", "code")
