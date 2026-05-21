"""货号历史 service。

只读访问 stockpile / stockpile_changes / stockpile_locations 表。

阶段 1.5 PR2 起：
- 当前状态走子表 stockpile_locations（结构化、含 unknown 栏）
- 历史变更 diff 仍按字符串解析 stockpile_location（changes 表存的是当时字符串快照）
"""

from datetime import datetime

from sqlalchemy import or_, select

from app.repositories import stockpile_db
from app.parsers.location import parse_to_locations
from app.models import InventoryEvent, Stockpile, StockpileChange, StockpileLocation

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
    """归一为 naive datetime, 避免 stockpile_changes (PG tz-aware) 跟
    inventory_events (parquet naive YYYY-MM-DD) 混排时
    "can't compare offset-naive and offset-aware datetimes" 报错."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


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
                Stockpile.product_name_zh,
                Stockpile.product_name_local,
                Stockpile.erp_category_raw,
                Stockpile.erp_category_code,
                Stockpile.manual_grade,
                Stockpile.stock_price,
                Stockpile.sale_price,
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
        "product_name_zh": row[7],
        "product_name_local": row[8],
        "erp_category_raw": row[9],
        "erp_category_code": row[10],
        "manual_grade": row[11],
        "stock_price": row[12],
        "sale_price": row[13],
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


def _fetch_inventory_events(barcode: str) -> list[dict]:
    """读 inventory_events 中该条码的销售/采购记录，转成 timeline event 形态。

    与 stockpile_changes 不同：每条 inventory_event 单独一个 event（无 5s 窗口聚合），
    用 summary 字段承载"销售 5 件 × €12.50 给 C001"这类描述，前端不走 changes 模板。
    """
    with stockpile_db._session() as session:
        rows = session.execute(
            select(
                InventoryEvent.event_at,
                InventoryEvent.event_type,
                InventoryEvent.qty,
                InventoryEvent.unit_price,
                InventoryEvent.customer_id,
                InventoryEvent.supplier_id,
            )
            .where(InventoryEvent.product_barcode == barcode)
            .order_by(InventoryEvent.event_at.desc())
        ).all()
    out: list[dict] = []
    for r in rows:
        is_sale = r.event_type == "sale"
        actor = r.customer_id if is_sale else r.supplier_id
        verb = "销售" if is_sale else "采购"
        price_part = f" × €{r.unit_price}" if r.unit_price is not None else ""
        actor_part = f"（{actor}）" if actor else ""
        out.append(
            {
                "at": r.event_at,
                "change_type": r.event_type,  # 'sale' / 'purchase'
                "source": "inventory_events",
                "changes": [],
                "summary": f"{verb} {r.qty} 件{price_part}{actor_part}",
            }
        )
    return out


def aggregate_full_timeline(barcode: str) -> list[dict]:
    """合并 stockpile_changes 聚合事件 + inventory_events，按时间倒序。

    PR-FE-4b：原 aggregate_events 只覆盖 stockpile 主档变更（insert/update/
    deactivate/reactivate）。本函数额外把 sale / purchase 业务事件并入同一时间线，
    供货号历史页统一展示。
    """
    events = aggregate_events(barcode) + _fetch_inventory_events(barcode)
    events.sort(key=lambda e: _parse_dt(e["at"]), reverse=True)
    return events


_FUZZY_MIN_QUERY = 2
_FUZZY_LIMIT = 20


def find_fuzzy_matches(query: str, limit: int = _FUZZY_LIMIT) -> list[dict]:
    """LIKE %query% 子串模糊匹配 product_barcode 或 product_model。

    与 stockpile_db.search_stockpile 的差异：本函数 **不**过滤 is_active —— 货号
    历史页的目标是看历史，已下架记录就是用户想找的。排序为 active 优先 + barcode
    字典序。

    返回字段：barcode / model / location / is_active。
    """
    q = (query or "").strip()
    if len(q) < _FUZZY_MIN_QUERY:
        return []
    pattern = f"%{q}%"
    with stockpile_db._session() as session:
        rows = session.execute(
            select(
                Stockpile.product_barcode,
                Stockpile.product_model,
                Stockpile.stockpile_location,
                Stockpile.is_active,
            )
            .where(
                or_(Stockpile.product_barcode.like(pattern), Stockpile.product_model.like(pattern))
            )
            .order_by(Stockpile.is_active.desc(), Stockpile.product_barcode)
            .limit(limit)
        ).all()
    return [
        {"barcode": r[0], "model": r[1], "location": r[2], "is_active": bool(r[3])} for r in rows
    ]


def build_response(query: str) -> dict:
    """供 routes_history.py 直接 jsonify 的顶层结构。

    found=True  → { "found": True, "current": {...}, "events": [...] }
    found=False → { "found": False }                              # 完全无匹配
    found=False → { "found": False, "fuzzy_matches": [...] }      # 精确未中但子串有候选
    """
    record = find_record(query)
    if record is None:
        matches = find_fuzzy_matches(query)
        if matches:
            return {"found": False, "fuzzy_matches": matches}
        return {"found": False}

    # 当前状态：从子表 stockpile_locations 拉结构化数据
    current = current_locations(record["barcode"])
    record["store_locations"] = current["stores"]
    record["warehouse_locations"] = current["warehouses"]
    record["unknown_locations"] = current["unknown"]

    events = aggregate_full_timeline(record["barcode"])
    for e in events:
        # stockpile_changes 的 source 来自主表；
        # inventory_events 已在 _fetch 里写好 'inventory_events'
        if e.get("source") is None:
            e["source"] = record["source"]
        # 库位变更行：拆 old/new
        for ch in e.get("changes", []):
            if ch["field"] == "stockpile_location":
                ch["old_split"] = split_location(ch["old"])
                ch["new_split"] = split_location(ch["new"])
    return {"found": True, "current": record, "events": events}
