"""add backtest_runs and backtest_results tables

Revision ID: b9e1c4f8a3d2
Revises: 68b4bbea9edd
Create Date: 2026-05-14 13:00:00.000000

plan 2026-05-12-forecast-and-backtest.md §2.5: 回测 run + per-SKU 分数表。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b9e1c4f8a3d2"
down_revision: Union[str, Sequence[str], None] = "68b4bbea9edd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.Text(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("view", sa.Text(), nullable=False),
        sa.Column("window_train", sa.Integer(), nullable=False),
        sa.Column("window_test", sa.Integer(), nullable=False),
        sa.Column("min_weeks", sa.Integer(), nullable=False),
        sa.Column(
            "n_skus_total",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "n_skus_scored",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("backtest_runs.id"),
            nullable=False,
        ),
        sa.Column("product_barcode", sa.Text(), nullable=False),
        sa.Column("sku_type", sa.Text(), nullable=False),
        sa.Column("n_weeks_train", sa.Integer(), nullable=False),
        sa.Column("n_weeks_test", sa.Integer(), nullable=False),
        sa.Column("mape", sa.Float(), nullable=True),
        sa.Column("mase", sa.Float(), nullable=True),
        sa.Column("bias", sa.Float(), nullable=False),
        sa.Column("coverage_p98", sa.Float(), nullable=False),
        sa.Column("mean_actual", sa.Float(), nullable=False),
        sa.Column("mean_predicted", sa.Float(), nullable=False),
    )
    op.create_index(
        "idx_backtest_results_run_id", "backtest_results", ["run_id"]
    )
    op.create_index(
        "idx_backtest_results_barcode", "backtest_results", ["product_barcode"]
    )


def downgrade() -> None:
    op.drop_index("idx_backtest_results_barcode", table_name="backtest_results")
    op.drop_index("idx_backtest_results_run_id", table_name="backtest_results")
    op.drop_table("backtest_results")
    op.drop_table("backtest_runs")
