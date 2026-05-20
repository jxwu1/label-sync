"""add stockpile.is_truly_discontinued

Revision ID: d8a3f5c2b1e4
Revises: c1f0a7e3d4b2
Create Date: 2026-05-20 14:00:00.000000

极高置信「真停用」标记: 库存=0 AND PG 完全无销售/采购事件 → True.
不影响业务逻辑, 给 dashboard 加 toggle 过滤用. 默认 False, 保守.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d8a3f5c2b1e4"
down_revision: Union[str, Sequence[str], None] = "c1f0a7e3d4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stockpile",
        sa.Column(
            "is_truly_discontinued",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("stockpile", "is_truly_discontinued")
