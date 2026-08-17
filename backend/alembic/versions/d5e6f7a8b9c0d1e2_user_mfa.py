"""用户 MFA（TOTP）字段：totp_secret / totp_enabled / totp_confirmed_at

Revision ID: d5e6f7a8b9c0d1e2
Revises: b2c3d4e5f6a7b8c9
Create Date: 2026-08-16
"""
import sqlalchemy as sa

from alembic import op

revision = "d5e6f7a8b9c0d1e2"
down_revision = "b2c3d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("refresh_tokens", sa.Column("ip_address", sa.String(45), nullable=True))
    op.add_column("refresh_tokens", sa.Column("user_agent", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("refresh_tokens", "user_agent")
    op.drop_column("refresh_tokens", "ip_address")
    op.drop_column("users", "totp_confirmed_at")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
