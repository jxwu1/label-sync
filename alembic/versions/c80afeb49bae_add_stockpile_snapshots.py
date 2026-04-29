"""add stockpile_snapshots

Revision ID: c80afeb49bae
Revises: 2385c879eb58
Create Date: 2026-04-29 10:49:48.032286

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c80afeb49bae'
down_revision: Union[str, Sequence[str], None] = '2385c879eb58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加 stockpile_snapshots 表，每次 import / compare 留计数快照。

    PK NOT NULL 类的 cosmetic 差异（SQLite 反射）顺延到后续做表重建时一并解决。
    """
    op.create_table(
        "stockpile_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "taken_at",
            sa.Text(),
            server_default=sa.text("(datetime('now','localtime'))"),
            nullable=False,
        ),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("total_local", sa.Integer(), nullable=False),
        sa.Column("total_export", sa.Integer(), nullable=True),
        sa.Column("consistent", sa.Integer(), nullable=True),
        sa.Column("cosmetic_count", sa.Integer(), nullable=True),
        sa.Column("substantive_count", sa.Integer(), nullable=True),
        sa.Column("only_in_local_count", sa.Integer(), nullable=True),
        sa.Column("only_in_export_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_stockpile_snapshots_taken_at",
        "stockpile_snapshots",
        ["taken_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_stockpile_snapshots_taken_at", table_name="stockpile_snapshots")
    op.drop_table("stockpile_snapshots")
