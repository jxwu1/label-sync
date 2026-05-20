"""add forecast_output table

Revision ID: c1f0a7e3d4b2
Revises: b9e1c4f8a3d2
Create Date: 2026-05-20 09:30:00.000000

plan 2026-05-12-forecast-and-backtest.md §3.7: per-SKU 最新预测快照
(dashboard 用). 每 SKU 一行, upsert 刷新.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c1f0a7e3d4b2"
down_revision: Union[str, Sequence[str], None] = "b9e1c4f8a3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "forecast_output",
        sa.Column("product_barcode", sa.Text(), primary_key=True),
        sa.Column("model_used", sa.Text(), nullable=False),
        sa.Column("sku_type", sa.Text(), nullable=False),
        sa.Column("n_weeks_history", sa.Integer(), nullable=False),
        sa.Column("mu", sa.Float(), nullable=False),
        sa.Column("sigma", sa.Float(), nullable=False),
        sa.Column("p50", sa.Float(), nullable=False),
        sa.Column("p98", sa.Float(), nullable=False),
        sa.Column(
            "computed_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "idx_forecast_output_computed_at", "forecast_output", ["computed_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_forecast_output_computed_at", table_name="forecast_output")
    op.drop_table("forecast_output")
