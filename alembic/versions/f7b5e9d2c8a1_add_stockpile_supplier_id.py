"""add stockpile.supplier_id

Revision ID: f7b5e9d2c8a1
Revises: e2c4f6a9b7d3
Create Date: 2026-05-21 16:00:00.000000

把 ERP 产品总档里"产品 → 供应商"的关系直接落 stockpile, 用于补货决策凑单时
跨"曾采购过 vs 仅 master 注册过"的统一视图. 之前 list_sku_summary 用
last_purchase event 的 supplier_id, 漏掉了"ERP 标了供应商但还没产生 purchase
event"的 SKU (典型: 刚上架 / 历史 ERP 迁移残留).

nullable=True 因为旧 26k 行未填; product_master importer 下次 import 时回填;
analytics 端 fallback 到 last_purchase 兜底.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f7b5e9d2c8a1"
down_revision: Union[str, Sequence[str], None] = "e2c4f6a9b7d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stockpile",
        sa.Column("supplier_id", sa.Text(), nullable=True),
    )
    op.create_index("idx_stockpile_supplier_id", "stockpile", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("idx_stockpile_supplier_id", table_name="stockpile")
    op.drop_column("stockpile", "supplier_id")
