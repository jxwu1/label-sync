"""货号历史 service。

只读访问 stockpile / stockpile_changes / stockpile_locations 表。

阶段 1.5 PR2 起：
- 当前状态走子表 stockpile_locations（结构化、含 unknown 栏）
- 历史变更 diff 仍按字符串解析 stockpile_location（changes 表存的是当时字符串快照）
"""

from datetime import datetime

from sqlalchemy import or_, select

import stockpile_db
from location_parser import parse_to_locations
from models import Stockpile, StockpileChange, StockpileLocation

_AGGREGATE_WINDOW_SECONDS = 5


def split_location(loc_str: str | None) -> dict:
    """把 stockpile_location 字符串拆成 {stores, warehouses, unknown}。

    用于 stockpile_changes 历史变更 diff 显示（changes 表存字符串快照，
    没有当时的子表数据，只能字符串解析）。

    异常前缀（非 A/B/C/X/Z 开头）走 unknown 列，UI 单独展示而非静默丢弃。

    例：
        ""               → {"stores": [], "warehouses": [], "unknown": []}
        "A22-04-04"      → {"stores": ["A22-04-04"], "warehouses": [], "unknown": []}
        "A22/X11"        → {"stores": ["A22"], "warehouses": ["X11"], "unknown": []}
        "A22/Q99/X11"    → {"stores": ["A22"], "warehouses": ["X11"], "unknown": ["Q99"]}
    """
    stores: list[str] = []
    warehouses: list[str] = []
    unknown: list[str] = []
    for entry in parse_to_locations(loc_str):
        if entry["kind"] == "store":
            stores.append(entry["location"])
        elif entry["kind"] == "warehouse":
            warehouses.append(entry["location"])
        else:
            unknown.append(entry["location"])
    return {"stores": stores, "warehouses": warehouses, "unknown": unknown}


def current_locations(barcode: str) -> dict:
    """从 stockpile_locations 子表查 barcode 的当前库位，返回结构化分类。

    返回 {stores, warehouses, unknown}，每个是按 position 排序的字符串列表。
    """
    with stockpile_db._session() as session:
        rows = session.execute(
            select(StockpileLocation.location, StockpileLocation.kind)
            .join(Stockpile, Stockpile.id == StockpileLocation.stockpile_id)
            .where(Stockpile.product_barcode == barcode)
            .order_by(StockpileLocation.position)
        ).all()
    stores: list[str] = []
    warehouses: list[str] = []
    unknown: list[str] = []
    for location, kind in rows:
        if kind == "store":
            stores.append(location)
        elif kind == "warehouse":
            warehouses.append(location)
        else:
            unknown.append(location)
    return {"stores": stores, "warehouses": warehouses, "unknown": unknown}


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def find_record(query: str) -> dict | None:
    """精确匹配 product_model 或 product_barcode（两列均 UNIQUE）。

    返回当前主表行的 dict，或 None。
    """
    q = (query or "").strip()
    if not q:
        return None
    with stockpile_db._session() as session:
        row = session.execute(
            select(
                Stockpile.product_barcode,
                Stockpile.product_model,
                Stockpile.stockpile_location,
                Stockpile.is_active,
                Stockpile.source,
                Stockpile.created_at,
                Stockpile.updated_at,
            )
            .where(or_(Stockpile.product_barcode == q, Stockpile.product_model == q))
            .limit(1)
        ).first()
    if row is None:
        return None
    return {
        "barcode": row[0],
        "model": row[1],
        "location": row[2],
        "is_active": bool(row[3]),
        "source": row[4],
        "created_at": row[5],
        "updated_at": row[6],
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
    with stockpile_db._session() as session:
        rows = session.execute(
            select(
                StockpileChange.field_name,
                StockpileChange.old_value,
                StockpileChange.new_value,
                StockpileChange.change_type,
                StockpileChange.created_at,
            )
            .where(StockpileChange.product_barcode == barcode)
            .order_by(StockpileChange.created_at.desc())
        ).all()

    events: list[dict] = []
    current: dict | None = None

    for field_name, old_value, new_value, change_type, created_at in rows:
        change = {"field": field_name, "old": old_value, "new": new_value}
        if current is None:
            current = {
                "at": created_at,
                "change_type": change_type,
                "changes": [change],
            }
            continue
        prev_dt = _parse_dt(current["at"])
        cur_dt = _parse_dt(created_at)
        delta = (prev_dt - cur_dt).total_seconds()
        if 0 <= delta <= _AGGREGATE_WINDOW_SECONDS:
            current["changes"].append(change)
        else:
            events.append(current)
            current = {
                "at": created_at,
                "change_type": change_type,
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

    # 当前状态：从子表 stockpile_locations 拉结构化数据
    current = current_locations(record["barcode"])
    record["store_locations"] = current["stores"]
    record["warehouse_locations"] = current["warehouses"]
    record["unknown_locations"] = current["unknown"]

    events = aggregate_events(record["barcode"])
    for e in events:
        # source 来自主表，注入到每个事件方便前端显示
        e["source"] = record["source"]
        # 库位变更行：拆 old/new
        for ch in e["changes"]:
            if ch["field"] == "stockpile_location":
                ch["old_split"] = split_location(ch["old"])
                ch["new_split"] = split_location(ch["new"])
    return {"found": True, "current": record, "events": events}
