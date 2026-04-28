"""货号历史 service。

只读访问 stockpile / stockpile_changes 表。
"""
import sqlite3
from datetime import datetime
from typing import Optional

import stockpile_db

_AGGREGATE_WINDOW_SECONDS = 5


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(stockpile_db.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def find_record(query: str) -> Optional[dict]:
    """精确匹配 product_model 或 product_barcode（两列均 UNIQUE）。

    返回当前主表行的 dict，或 None。
    """
    q = (query or "").strip()
    if not q:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT product_barcode, product_model, stockpile_location, is_active, "
            "       source, created_at, updated_at "
            "FROM stockpile "
            "WHERE product_barcode = ? OR product_model = ? "
            "LIMIT 1",
            (q, q),
        ).fetchone()
    if row is None:
        return None
    return {
        "barcode": row["product_barcode"],
        "model": row["product_model"],
        "location": row["stockpile_location"],
        "is_active": bool(row["is_active"]),
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def aggregate_events(barcode: str) -> list[dict]:
    """按 barcode 拉所有 changes，按 created_at 倒序，
    相邻条目时间差 ≤ 5 秒则合并为同一事件。

    每个事件结构：
        {
            "at": "<created_at 字符串，取组内最新一条>",
            "source": None,  # changes 表不存 source（来自 stockpile.source），后期填充
            "change_type": "<组内最新一条的 change_type>",
            "changes": [{ "field": ..., "old": ..., "new": ... }, ...]
        }
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT field_name, old_value, new_value, change_type, created_at "
            "FROM stockpile_changes "
            "WHERE product_barcode = ? "
            "ORDER BY created_at DESC",
            (barcode,),
        ).fetchall()

    events: list[dict] = []
    current: Optional[dict] = None

    for row in rows:
        change = {
            "field": row["field_name"],
            "old": row["old_value"],
            "new": row["new_value"],
        }
        if current is None:
            current = {
                "at": row["created_at"],
                "change_type": row["change_type"],
                "changes": [change],
            }
            continue
        prev_dt = _parse_dt(current["at"])
        cur_dt = _parse_dt(row["created_at"])
        delta = (prev_dt - cur_dt).total_seconds()
        if 0 <= delta <= _AGGREGATE_WINDOW_SECONDS:
            current["changes"].append(change)
        else:
            events.append(current)
            current = {
                "at": row["created_at"],
                "change_type": row["change_type"],
                "changes": [change],
            }
    if current is not None:
        events.append(current)
    return events


def build_response(query: str) -> dict:
    """供 routes_history.py 直接 jsonify 的顶层结构。

    found=False  →  { "found": False }
    found=True   →  { "found": True, "current": {...}, "events": [...] }
    """
    record = find_record(query)
    if record is None:
        return {"found": False}
    events = aggregate_events(record["barcode"])
    # source 来自主表，注入到每个事件方便前端显示
    for e in events:
        e["source"] = record["source"]
    return {"found": True, "current": record, "events": events}
