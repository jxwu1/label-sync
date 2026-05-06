"""add stockpile stock_price and sale_price columns

Revision ID: 848720a778ad
Revises: 7f998b4f11ff
Create Date: 2026-05-06 13:41:17.993553

PR：product.csv 主档导入。stock_price/sale_price 是档案价格，与
inventory_events 里每行事件的实际成交价不同。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "848720a778ad"
down_revision: Union[str, Sequence[str], None] = "7f998b4f11ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stockpile") as batch:
        batch.add_column(sa.Column("stock_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("sale_price", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("stockpile") as batch:
        batch.drop_column("sale_price")
        batch.drop_column("stock_price")
