"""forecast_output 加置信度分层输入列 nonzero_weeks / zero_weeks_last8

Revision ID: b2c4e6f8a1d3
Revises: a3d8f1b9c2e7
Create Date: 2026-06-05 11:00:00.000000

第1期任务③ 置信度分层: forecast_output 增两列, refresh_forecast_output 顺手算。
- nonzero_weeks: 历史里 >0 的周数 (与 backtest min_weeks 口径一致)
- zero_weeks_last8: 最近 8 周里 <=0 的周数 (近期零需求信号, 降级用)
两列 server_default 0, 既有行(若有)安全; forecast_output 本就每日 refresh 整行重建。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b2c4e6f8a1d3"
down_revision: Union[str, Sequence[str], None] = "a3d8f1b9c2e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "forecast_output",
        sa.Column("nonzero_weeks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "forecast_output",
        sa.Column("zero_weeks_last8", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("forecast_output", "zero_weeks_last8")
    op.drop_column("forecast_output", "nonzero_weeks")
