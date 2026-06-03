"""add sku_summary table

Revision ID: a3d8f1b9c2e7
Revises: pda_scan_0001
Create Date: 2026-06-03 10:00:00.000000

物化 SKU 汇总快照表 (货号历史/dashboard 列表提速). 每 SKU 一行,
payload 存 _list_sku_summary_impl 算出的整个 item dict (JSON). refresh
时整表重写; 读路径查表 + 空表/as_of≠today 回退实时.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a3d8f1b9c2e7"
down_revision: Union[str, Sequence[str], None] = "pda_scan_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sku_summary",
        sa.Column("product_barcode", sa.Text(), primary_key=True),
        sa.Column("as_of", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "computed_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_sku_summary_as_of", "sku_summary", ["as_of"])


def downgrade() -> None:
    op.drop_index("idx_sku_summary_as_of", table_name="sku_summary")
    op.drop_table("sku_summary")
