"""add scan_status & error columns to scan_reports

Revision ID: e5f6a7b8c9d0e1f2
Revises: c4d5e6f7a8b9
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0e1f2"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_reports",
        sa.Column("scan_status", sa.String(length=20), server_default="pending", nullable=False),
    )
    op.add_column("scan_reports", sa.Column("error", sa.Text(), nullable=True))
    # 历史报告（旧模拟引擎已生成 scan_data）直接视为扫描完成
    op.execute("UPDATE scan_reports SET scan_status = 'completed' WHERE scan_data IS NOT NULL")
    op.create_index("idx_report_scan_status", "scan_reports", ["scan_status"])


def downgrade() -> None:
    op.drop_index("idx_report_scan_status", table_name="scan_reports")
    op.drop_column("scan_reports", "error")
    op.drop_column("scan_reports", "scan_status")
