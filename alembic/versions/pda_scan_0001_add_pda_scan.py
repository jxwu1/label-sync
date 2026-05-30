"""add pda scan: user.role, employee.is_scanner, scan_sessions, scan_items

Revision ID: pda_scan_0001
Revises: wecom_acct_0001
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "pda_scan_0001"
down_revision = "wecom_acct_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'admin'")))
    op.add_column("employees", sa.Column("is_scanner", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_table(
        "scan_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operator_employee_id", sa.Text(), sa.ForeignKey("employees.employee_id"), nullable=False),
        sa.Column("operator_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("batch_label", sa.Text(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.Text(), server_default=sa.func.current_timestamp()),
        sa.Column("finalized_at", sa.Text(), nullable=True),
    )
    op.create_table(
        "scan_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("scan_sessions.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("scanned_at", sa.Text(), server_default=sa.func.current_timestamp()),
    )
    op.create_index("idx_scan_items_session", "scan_items", ["session_id", "seq"])


def downgrade() -> None:
    op.drop_index("idx_scan_items_session", table_name="scan_items")
    op.drop_table("scan_items")
    op.drop_table("scan_sessions")
    with op.batch_alter_table("employees") as b:
        b.drop_column("is_scanner")
    with op.batch_alter_table("users") as b:
        b.drop_column("role")
