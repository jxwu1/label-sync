"""add restock_decisions table

Revision ID: b4d8c1e5f3a2
Revises: a3c9b7e4d2f1
Create Date: 2026-05-22 18:30:00.000000

补货决策反馈闭环 (P3 数据收集):
  4 类信号 (decision 列):
    - ordered:          推荐对了, 你按推荐进了货
    - overridden:       低分但你硬要进 (推算: 标已下单时 urgency<50)
    - skipped:          出现在 top 但你不进 (含原因)
    - stale_high_score: 高分 14 天未处理 (按需扫出)

  每行存"决策那一刻"的快照, 避免事后 SKU 销售/库存变了无法复盘.

  分析用 (一周后回头看):
    - 哪类 SKU 总被跳过 → 那个维度可能权重偏高
    - 哪类被 overridden → 算法没看到的隐式信号
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b4d8c1e5f3a2"
down_revision: Union[str, Sequence[str], None] = "a3c9b7e4d2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "restock_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("barcode", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.Text(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("urgency_score", sa.Float()),
        sa.Column("velocity_pctile", sa.Float()),
        sa.Column("margin_pctile", sa.Float()),
        sa.Column("breakdown_velocity", sa.Float()),
        sa.Column("breakdown_cover", sa.Float()),
        sa.Column("breakdown_recency", sa.Float()),
        sa.Column("breakdown_margin", sa.Float()),
        sa.Column("margin_source", sa.Text()),
        sa.Column("weekly_revenue", sa.Float()),
        sa.Column("weekly_velocity", sa.Float()),
        sa.Column("margin_pct", sa.Float()),
        sa.Column("weeks_of_cover", sa.Float()),
        sa.Column("origin", sa.Text()),
        sa.Column("supplier_id", sa.Text()),
        sa.Column("reason", sa.Text()),
    )
    op.create_index("idx_restock_decisions_barcode", "restock_decisions", ["barcode"])
    op.create_index("idx_restock_decisions_decided_at", "restock_decisions", ["decided_at"])
    op.create_index("idx_restock_decisions_decision", "restock_decisions", ["decision"])


def downgrade() -> None:
    op.drop_index("idx_restock_decisions_decision", table_name="restock_decisions")
    op.drop_index("idx_restock_decisions_decided_at", table_name="restock_decisions")
    op.drop_index("idx_restock_decisions_barcode", table_name="restock_decisions")
    op.drop_table("restock_decisions")
