"""阶段 1 预测数据底座 (plan 2026-05-12-forecast-and-backtest.md §1.0.1 + §1.1).

仅实现 weekly_demand_series; §1.2-1.5 (base_demand_view / winsorize / stockout_adjust /
is_bulk_order) 留待 PR2 (SKU 分类) 之后再加。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import stockpile_db
from models import InventoryEvent


def _monday(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


def _parse_event_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def weekly_demand_series(
    barcode: str,
    end_date: date,
    weeks: int,
    session: Session | None = None,
) -> dict[date, int]:
    """周聚合销量, 按 document_no 净抵退货 (plan §1.0.1).

    Window: 末周 = 含 end_date 的 ISO 周; 向前回看 weeks 周.
    返回 dict[week_start_monday, qty_sum] 按时间升序, 空周补 0.

    退货归并:
    - 同 document_no 内全部 qty 求和 → 净量
    - 净量 > 0: 挂到 doc 内最早 event_at 所属的周
    - 净量 ≤ 0: 丢弃 (原单不在窗口或被完全冲销, 周需求 0 而非负)
    - document_no 为空: 按事件主键单独成 doc (无法合并)
    """
    if weeks < 1:
        raise ValueError("weeks must be >= 1")

    end_monday = _monday(end_date)
    week_starts = [
        end_monday - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)
    ]
    window_start = week_starts[0]
    window_end_exclusive = end_monday + timedelta(days=7)
    series: dict[date, int] = {w: 0 for w in week_starts}

    def _fetch(s: Session) -> list[tuple[str, int, str | None, int]]:
        return s.execute(
            select(
                InventoryEvent.event_at,
                InventoryEvent.qty,
                InventoryEvent.document_no,
                InventoryEvent.id,
            ).where(
                InventoryEvent.event_type == "sale",
                InventoryEvent.product_barcode == barcode,
                InventoryEvent.event_at >= window_start.isoformat(),
                InventoryEvent.event_at < window_end_exclusive.isoformat(),
            )
        ).all()

    if session is None:
        with stockpile_db._session() as s:
            rows = _fetch(s)
    else:
        rows = _fetch(session)

    buckets: dict[str, list[tuple[date, int]]] = defaultdict(list)
    for event_at, qty, doc_no, ev_id in rows:
        key = doc_no if doc_no else f"__null__{ev_id}"
        buckets[key].append((_parse_event_date(event_at), qty))

    for items in buckets.values():
        net = sum(q for _, q in items)
        if net <= 0:
            continue
        earliest_week = _monday(min(d for d, _ in items))
        if earliest_week in series:
            series[earliest_week] += net

    return series
