"""add inventory_imports audit table

Revision ID: 68b4bbea9edd
Revises: 848720a778ad
Create Date: 2026-05-07 11:15:08.905900

PR-FE-5b：每次 inventory import 留 audit 行（时间/类型/文件/总行/OK/重复/错误/操作员），
供「进销存导入」页底部「最近导入」表格展示。
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "68b4bbea9edd"
down_revision: Union[str, Sequence[str], None] = "848720a778ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_imports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "imported_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("(datetime('now','localtime'))"),
        ),
        sa.Column("event_type", sa.Text(), nullable=False),  # 'purchase' / 'sale'
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("ok_count", sa.Integer(), nullable=False),
        sa.Column("dup_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=False, server_default="admin"),
    )
    op.create_index(
        "idx_inventory_imports_at", "inventory_imports", ["imported_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_inventory_imports_at", table_name="inventory_imports")
    op.drop_table("inventory_imports")
