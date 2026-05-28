"""add employee.wecom_account

Revision ID: wecom_acct_0001
Revises: cb40fb302571
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "wecom_acct_0001"
down_revision = "cb40fb302571"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("wecom_account", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "wecom_account")
