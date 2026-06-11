"""forecast_output 加 horizon 分位数列 (ADR-0001 / RL-1, RL-3)

Revision ID: c7e1f0a2b9d4
Revises: a53886f73e90
Create Date: 2026-06-11

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7e1f0a2b9d4"
down_revision: Union[str, Sequence[str], None] = "a53886f73e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("forecast_output", sa.Column("horizon_weeks", sa.Integer(), nullable=True))
    op.add_column("forecast_output", sa.Column("p50_h", sa.Float(), nullable=True))
    op.add_column("forecast_output", sa.Column("p98_h", sa.Float(), nullable=True))
    op.add_column("forecast_output", sa.Column("p98_13w", sa.Float(), nullable=True))
    op.add_column(
        "forecast_output",
        sa.Column("stockout_weeks_excluded", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("forecast_output", "stockout_weeks_excluded")
    op.drop_column("forecast_output", "p98_13w")
    op.drop_column("forecast_output", "p98_h")
    op.drop_column("forecast_output", "p50_h")
    op.drop_column("forecast_output", "horizon_weeks")
