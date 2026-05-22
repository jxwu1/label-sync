"""add stockpile.master_stock_price_eur

Revision ID: a3c9b7e4d2f1
Revises: f8c6a4b2e1d9
Create Date: 2026-05-22 17:30:00.000000

ERP 产品总档 (product_master.stock_price) 折算成 EUR 后落库, 给毛利兜底:
- FOREIGN (GR/ES/IT/DE/TR...): stock_price 已是 EUR, 直接写
- CN/HZ: 一律 NULL (国内同事把海运费混在 stock_price 里, 不能用作纯进价)
- stock_price = 0: NULL
analytics.margin_pct 用 COALESCE(last_purchase_unit_price, master_stock_price_eur).
breakdown.margin_source 标 'purchase' / 'master' / null 让前端知道精度.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a3c9b7e4d2f1"
down_revision: Union[str, Sequence[str], None] = "f8c6a4b2e1d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stockpile",
        sa.Column("master_stock_price_eur", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stockpile", "master_stock_price_eur")
