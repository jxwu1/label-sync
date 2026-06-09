"""forecast_output 加 stockout_zero_weeks_last8 列

Revision ID: a53886f73e90
Revises: b2c4e6f8a1d3
Create Date: 2026-06-09 12:20:56.563459

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a53886f73e90"
down_revision: Union[str, Sequence[str], None] = "b2c4e6f8a1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "forecast_output",
        sa.Column("stockout_zero_weeks_last8", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("forecast_output", "stockout_zero_weeks_last8")
