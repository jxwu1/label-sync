"""add stockpile_locations subtable

Revision ID: 2385c879eb58
Revises: cf04ed0496f7
Create Date: 2026-04-29 10:15:50.214740

阶段 1.5 PR1：加多库位子表 + 数据迁移。
- 主表 stockpile.stockpile_location 字符串永久保留（月度比对源）
- 子表是派生视图，由 stockpile_db._upsert dual-write 维护

PK NOT NULL 类的 cosmetic 差异（SQLite 老 schema 反射）顺延到后续做表
重建时一并解决，本迁移不动。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2385c879eb58"
down_revision: Union[str, Sequence[str], None] = "cf04ed0496f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 子表分类用前缀映射（与 location_parser._KIND_BY_PREFIX 同步）
_KIND_BY_PREFIX = {
    "A": "store", "B": "store", "C": "store",
    "X": "warehouse", "Z": "warehouse",
}


def _classify_kind(loc: str) -> str:
    if not loc:
        return "unknown"
    return _KIND_BY_PREFIX.get(loc[:1].upper(), "unknown")


def _parse_to_locations(raw: str) -> list[tuple[str, str, int]]:
    """与 location_parser.parse_to_locations 等价的内联实现，
    保证迁移自包含、不依赖项目代码后续演进。"""
    if not raw:
        return []
    result = []
    position = 0
    for part in str(raw).split("/"):
        loc = part.strip()
        if not loc:
            continue
        result.append((loc, _classify_kind(loc), position))
        position += 1
    return result


def upgrade() -> None:
    op.create_table(
        "stockpile_locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stockpile_id", sa.Integer(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.Text(),
            server_default=sa.text("(datetime('now','localtime'))"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["stockpile_id"], ["stockpile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stockpile_id", "location", name="uq_stockpile_locations"),
    )
    op.create_index(
        "idx_stockpile_locations_location", "stockpile_locations", ["location"], unique=False
    )
    op.create_index(
        "idx_stockpile_locations_stockpile",
        "stockpile_locations",
        ["stockpile_id"],
        unique=False,
    )

    # === 数据迁移：把现有 43k 行 stockpile_location 字符串拆到子表 ===
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, stockpile_location FROM stockpile")
    ).fetchall()

    inserts: list[dict] = []
    seen_pairs: set[tuple[int, str]] = set()  # 防 UNIQUE(stockpile_id, location) 冲突
    for row_id, raw in rows:
        for loc, kind, pos in _parse_to_locations(raw):
            key = (row_id, loc)
            if key in seen_pairs:
                continue  # 同 raw 字符串里同 location 重复出现（罕见但要防）
            seen_pairs.add(key)
            inserts.append({
                "stockpile_id": row_id,
                "location": loc,
                "kind": kind,
                "position": pos,
            })

    if inserts:
        bind.execute(
            sa.text(
                "INSERT INTO stockpile_locations (stockpile_id, location, kind, position) "
                "VALUES (:stockpile_id, :location, :kind, :position)"
            ),
            inserts,
        )


def downgrade() -> None:
    op.drop_index("idx_stockpile_locations_stockpile", table_name="stockpile_locations")
    op.drop_index("idx_stockpile_locations_location", table_name="stockpile_locations")
    op.drop_table("stockpile_locations")
