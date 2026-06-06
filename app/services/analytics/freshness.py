"""数据新鲜度判定 (split-only 拆分自 analytics)。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.models import InventoryEvent
from app.repositories import stockpile_db
from app.services.analytics._shared import _parse_date, _today

# 数据新鲜度: scraper 每周抓一次, 距上次灌数 > 9 天 → 至少漏了一轮, 判定 stale
_DATA_STALE_DAYS = 9


def get_data_freshness(as_of: date | None = None) -> dict[str, Any]:
    """返回数据新鲜度: 基于 max(inventory_events.imported_at)。

    {last_import_at, last_import_date, days_since, stale}
    空库 → 全 None + stale=False (无数据不报红, 避免本地/新系统误报)。
    """
    as_of = as_of or _today()
    with stockpile_db._session() as session:
        last = session.execute(select(func.max(InventoryEvent.imported_at))).scalar()
    if not last:
        return {
            "last_import_at": None,
            "last_import_date": None,
            "days_since": None,
            "stale": False,
        }
    last_date = _parse_date(str(last))
    days = (as_of - last_date).days
    return {
        "last_import_at": str(last),
        "last_import_date": last_date.isoformat(),
        "days_since": days,
        "stale": days > _DATA_STALE_DAYS,
    }
