# recent_changes_service.py
"""货号历史 - 最近改动 service。

按 stockpile_snapshots(trigger='import') 切批次，关联到落在
窗口 (prev_taken_at, current_taken_at] 内的 stockpile_changes。
"""
from typing import Literal, Optional

from sqlalchemy import and_, func, select

import stockpile_db
from models import Stockpile, StockpileChange, StockpileSnapshot

_RECENT_IMPORTS_LIMIT = 10
_EPOCH = "1970-01-01 00:00:00"


def _batch_window(session, batch_id: int) -> tuple[str, str]:
    """返回 (window_start, window_end) 字符串。

    window_end = snapshot[batch_id].taken_at
    window_start = 上一个 trigger='import' snapshot 的 taken_at；不存在时取 _EPOCH
    """
    current = session.execute(
        select(StockpileSnapshot.taken_at)
        .where(StockpileSnapshot.id == batch_id)
    ).scalar_one()

    prev = session.execute(
        select(StockpileSnapshot.taken_at)
        .where(and_(
            StockpileSnapshot.trigger == "import",
            StockpileSnapshot.id < batch_id,
        ))
        .order_by(StockpileSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    return (prev or _EPOCH, current)


def list_recent_imports(limit: int = _RECENT_IMPORTS_LIMIT) -> list[dict]:
    """返回最近 N 次 import snapshot 概览。

    每条 dict 字段：batch_id / taken_at / total_local / change_count / affected_barcodes
    """
    with stockpile_db._session() as session:
        snapshots = session.execute(
            select(StockpileSnapshot)
            .where(StockpileSnapshot.trigger == "import")
            .order_by(StockpileSnapshot.id.desc())
            .limit(limit)
        ).scalars().all()

        result = []
        for snap in snapshots:
            start, end = _batch_window(session, snap.id)
            stats = session.execute(
                select(
                    func.count().label("n"),
                    func.count(func.distinct(StockpileChange.product_barcode)).label("bc"),
                ).where(and_(
                    StockpileChange.created_at > start,
                    StockpileChange.created_at <= end,
                ))
            ).one()
            result.append({
                "batch_id": snap.id,
                "taken_at": snap.taken_at,
                "total_local": snap.total_local,
                "change_count": stats.n,
                "affected_barcodes": stats.bc,
            })
        return result
