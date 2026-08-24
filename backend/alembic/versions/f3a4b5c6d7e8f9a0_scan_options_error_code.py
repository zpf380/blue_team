"""add scan_options & error_code columns to scan_reports

Revision ID: f3a4b5c6d7e8f9a0
Revises: e7d8c9b0a1f2e3d4
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f3a4b5c6d7e8f9a0"
down_revision = "e7d8c9b0a1f2e3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_reports", sa.Column("scan_options", JSONB(), nullable=True))
    op.add_column("scan_reports", sa.Column("error_code", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_reports", "error_code")
    op.drop_column("scan_reports", "scan_options")
