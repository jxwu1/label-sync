"""inventory_events.imported_at 加索引 (简报新鲜度 MAX 提速)

Revision ID: f3a9c1d2e4b5
Revises: c7e1f0a2b9d4
Create Date: 2026-06-16

简报 data_health 的 get_data_freshness 做 MAX(imported_at)，原全表扫 ~290 万行 (~1.3s)。
imported_at 加索引后 MAX 走索引，亚毫秒。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c1d2e4b5"
down_revision: Union[str, Sequence[str], None] = "c7e1f0a2b9d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_events_imported_at", "inventory_events", ["imported_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_events_imported_at", table_name="inventory_events")
