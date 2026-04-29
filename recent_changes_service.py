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


def get_batch_summary(batch_id: int) -> dict:
    """返回该批次 5 个统计 + roundtrip count。

    全部按 (barcode, field_name) 维度去重；同 barcode+field 多次变更
    若终态==起始态则计入 roundtrip_count，不进 5 个数字。
    """
    with stockpile_db._session() as session:
        start, end = _batch_window(session, batch_id)
        rows = session.execute(
            select(
                StockpileChange.product_barcode,
                StockpileChange.field_name,
                StockpileChange.old_value,
                StockpileChange.new_value,
                StockpileChange.change_type,
                StockpileChange.created_at,
            ).where(and_(
                StockpileChange.created_at > start,
                StockpileChange.created_at <= end,
            ))
            .order_by(StockpileChange.created_at)
        ).all()

    return _summarize(rows)


def _summarize(rows: list) -> dict:
    """把原始 changes 行折叠为 5 个统计 + roundtrip。"""
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r.product_barcode, r.field_name), []).append(r)

    counts = {
        "location_changes": 0,
        "model_changes": 0,
        "inserts": 0,
        "deactivates": 0,
        "reactivates": 0,
        "roundtrip_count": 0,
    }
    for (barcode, field), group in grouped.items():
        first_old = group[0].old_value
        last_new = group[-1].new_value
        last_type = group[-1].change_type
        # roundtrip：终态==起始态（仅 update 类型有意义）
        if first_old == last_new and last_type == "update":
            counts["roundtrip_count"] += 1
            continue
        if last_type == "insert":
            counts["inserts"] += 1
        elif last_type == "deactivate":
            counts["deactivates"] += 1
        elif last_type == "reactivate":
            counts["reactivates"] += 1
        elif field == "stockpile_location":
            counts["location_changes"] += 1
        elif field == "product_model":
            counts["model_changes"] += 1
    return counts
