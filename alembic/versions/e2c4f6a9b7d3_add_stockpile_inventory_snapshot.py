"""add stockpile_inventory_snapshot table

Revision ID: e2c4f6a9b7d3
Revises: d8a3f5c2b1e4
Create Date: 2026-05-20 15:00:00.000000

库存快照表: 每次抓取 (周一 cron) 写一个 snapshot_date 全量, 保留历史快照.
UNIQUE (snapshot_date, product_model) 保证同日同 model 单行;
product_barcode 不在快照里 (ERP 库存页不导出条码), 服务器侧用 product_model
JOIN stockpile 反查 (规则 A: model==barcode, 规则 B: model==barcode[:-1][-5:]).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e2c4f6a9b7d3"
down_revision: Union[str, Sequence[str], None] = "d8a3f5c2b1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stockpile_inventory_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Text(), nullable=False),
        sa.Column("product_model", sa.Text(), nullable=False),
        sa.Column("product_name_zh", sa.Text(), nullable=True),
        sa.Column("erp_category_code", sa.Text(), nullable=True),
        sa.Column("erp_category_raw", sa.Text(), nullable=True),
        sa.Column("last_purchase_at", sa.Text(), nullable=True),
        sa.Column("last_arrival_at", sa.Text(), nullable=True),
        sa.Column("qty_store", sa.Integer(), nullable=True),
        sa.Column("qty_total", sa.Integer(), nullable=False),
        sa.Column("reorder_min", sa.Integer(), nullable=True),
        sa.Column("reorder_max", sa.Integer(), nullable=True),
        sa.Column(
            "is_discontinued_in_erp",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "imported_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "snapshot_date",
            "product_model",
            name="uq_inventory_snapshot_date_model",
        ),
    )
    op.create_index(
        "idx_inventory_snapshot_date",
        "stockpile_inventory_snapshot",
        ["snapshot_date"],
    )
    op.create_index(
        "idx_inventory_snapshot_model",
        "stockpile_inventory_snapshot",
        ["product_model"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_inventory_snapshot_model", table_name="stockpile_inventory_snapshot"
    )
    op.drop_index(
        "idx_inventory_snapshot_date", table_name="stockpile_inventory_snapshot"
    )
    op.drop_table("stockpile_inventory_snapshot")
