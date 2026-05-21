"""add stockpile.last_purchase_unit_price

Revision ID: f8c6a4b2e1d9
Revises: f7b5e9d2c8a1
Create Date: 2026-05-21 18:00:00.000000

把每个 SKU 最近一次有效采购的折后净价 (unit_price * (1-discount/100)) 落 stockpile,
给毛利计算用. 用户决策 (2026-05-21): 取消之前 sanitize.py NULL out
events.purchase.unit_price 的脱敏, 接受 Hetzner 内网态势下进价上 PG 明文.

nullable=True 因为存量 26k 行旧 SKU 还没新 purchase event 进来回填.
analytics 端算毛利时要兜底处理 NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f8c6a4b2e1d9"
down_revision: Union[str, Sequence[str], None] = "f7b5e9d2c8a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stockpile",
        sa.Column("last_purchase_unit_price", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stockpile", "last_purchase_unit_price")
