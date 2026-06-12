"""阶段 1 预测数据底座 (plan 2026-05-12-forecast-and-backtest.md §1.0.1 + §1.1 + §1.3 + §1.5).

已实现:
- weekly_demand_series (§1.0.1 + §1.1)
- winsorize (§1.3)
- compute_doc_qty_stats / is_bulk_order (§1.5)

待 §1.2 base_demand_view 整合层 (PR4) 把以上组合起来.
§1.4 stockout_adjust 等 SKU 级日库存快照表建好再做.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryEvent
from app.repositories import stockpile_db

_BULK_K_DEFAULT = 3.0
_MIN_STATS_SAMPLES = 4


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
    week_starts = [end_monday - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)]
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


def weekly_demand_series_bulk(
    barcodes: list[str],
    end_date: date,
    weeks: int,
    session: Session | None = None,
) -> dict[str, dict[date, int]]:
    """weekly_demand_series 的批量版：一次窗口查询取齐全部 SKU。

    逐 SKU 结果与单个调用一致（test_forecast_bulk 等价测试守护）。
    退货归并语义同单 SKU 版：doc 桶按 (barcode, doc_key) 分组，空单号
    （None/''）按事件主键独立。
    """
    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    barcodes = list(dict.fromkeys(barcodes))
    if not barcodes:
        return {}
    if session is None:
        with stockpile_db._session() as s:
            return weekly_demand_series_bulk(barcodes, end_date, weeks, s)

    end_monday = _monday(end_date)
    week_starts = [end_monday - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)]
    window_start = week_starts[0]
    window_end_exclusive = end_monday + timedelta(days=7)

    rows = session.execute(
        select(
            InventoryEvent.product_barcode,
            InventoryEvent.event_at,
            InventoryEvent.qty,
            InventoryEvent.document_no,
            InventoryEvent.id,
        ).where(
            InventoryEvent.event_type == "sale",
            InventoryEvent.product_barcode.in_(barcodes),
            InventoryEvent.event_at >= window_start.isoformat(),
            InventoryEvent.event_at < window_end_exclusive.isoformat(),
        )
    ).all()

    buckets: dict[tuple[str, str], list[tuple[date, int]]] = defaultdict(list)
    for bc, event_at, qty, doc_no, ev_id in rows:
        key = (bc, doc_no if doc_no else f"__null__{ev_id}")
        buckets[key].append((_parse_event_date(event_at), qty))

    out: dict[str, dict[date, int]] = {bc: {w: 0 for w in week_starts} for bc in barcodes}
    for (bc, _doc), items in buckets.items():
        net = sum(q for _, q in items)
        if net <= 0:
            continue
        earliest_week = _monday(min(d for d, _ in items))
        if earliest_week in out[bc]:
            out[bc][earliest_week] += net
    return out


# ---- §1.3 winsorize ----------------------------------------------------------


def winsorize(values: list[float] | list[int], q: float = 0.95) -> list[float]:
    """把 > q 分位的值压到 q 分位本身. 空输入返回空, 不改输入.

    plan §1.3: 只用于 retail_dominant / mixed; 不动 wholesale_only.
    """
    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    cap = float(np.quantile(arr, q))
    return [float(min(v, cap)) for v in arr]


# ---- §1.5 IQR 基础的异常订单判定 --------------------------------------------


def compute_doc_qty_stats(net_qtys: list[int] | list[float]) -> dict | None:
    """对单 SKU 的 doc 净量列表算 median + IQR. < 4 样本返回 None.

    返回 {"median", "q1", "q3", "iqr"}.
    """
    if len(net_qtys) < _MIN_STATS_SAMPLES:
        return None
    arr = np.asarray(net_qtys, dtype=float)
    q1 = float(np.quantile(arr, 0.25))
    q3 = float(np.quantile(arr, 0.75))
    return {
        "median": float(np.median(arr)),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
    }


def is_bulk_order(qty: float, stats: dict | None, k: float = _BULK_K_DEFAULT) -> bool:
    """qty > median + k·IQR → True. None / 不合法 stats → False.

    plan §1.5: 弃用均值改 median + IQR, 避免 wholesale 大单污染阈值.
    """
    if stats is None:
        return False
    threshold = stats["median"] + k * stats["iqr"]
    return qty > threshold


# ---- §1.2 base_demand_view ---------------------------------------------------

_MIXED_KEEP_CUSTOMER_TYPES = ("foreign", "chinese")


def base_demand_view(
    barcode: str,
    end_date: date,
    weeks: int,
    session: Session | None = None,
) -> dict:
    """plan §1.2 基础需求视图: 按 SKU 类型分流剔异常单 + 客户过滤后周聚合.

    返回 {
        "sku_type": SKU_TYPES 之一,
        "series": dict[date, int] | None  (wholesale_only / unclassified 为 None),
        "exclusion_count": int  (剔除的 doc 数),
        "exclusion_qty": int    (剔除的总净 qty),
    }

    规则:
    - wholesale_only / unclassified: series=None, 直接返回
    - retail_dominant: 仅 is_bulk_order 剔大单
    - mixed: 同上 + 客户类型 ∉ {foreign, chinese} 也剔
    - IQR stats 用全历史 doc-net qty (窗口外也算, 阈值更稳)
    - 退货归并复用 §1.0.1: 同 doc 净抵, 净量 ≤ 0 丢弃 (不计入 exclusion)
    """
    from app.utils.categorizer import _fetch_sku_doc_net_qty, classify_sku_type

    sku_type = classify_sku_type(barcode, session, as_of=end_date)
    if sku_type in ("wholesale_only", "dying", "unclassified"):
        return {
            "sku_type": sku_type,
            "series": None,
            "exclusion_count": 0,
            "exclusion_qty": 0,
        }

    all_doc_qtys = _fetch_sku_doc_net_qty(barcode, session)
    stats = compute_doc_qty_stats(all_doc_qtys)

    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    end_monday = _monday(end_date)
    week_starts = [end_monday - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)]
    window_start = week_starts[0]
    window_end_exclusive = end_monday + timedelta(days=7)
    series: dict[date, int] = {w: 0 for w in week_starts}

    def _fetch_window(s: Session):
        return s.execute(
            select(
                InventoryEvent.event_at,
                InventoryEvent.qty,
                InventoryEvent.document_no,
                InventoryEvent.id,
                InventoryEvent.customer_id,
            ).where(
                InventoryEvent.event_type == "sale",
                InventoryEvent.product_barcode == barcode,
                InventoryEvent.event_at >= window_start.isoformat(),
                InventoryEvent.event_at < window_end_exclusive.isoformat(),
            )
        ).all()

    cust_types: dict[str, str] = {}
    if session is None:
        with stockpile_db._session() as s:
            rows = _fetch_window(s)
            if sku_type == "mixed":
                cust_types = _fetch_customer_types({r[4] for r in rows if r[4]}, s)
    else:
        rows = _fetch_window(session)
        if sku_type == "mixed":
            cust_types = _fetch_customer_types({r[4] for r in rows if r[4]}, session)

    buckets: dict[str, list[tuple[date, int, str | None]]] = defaultdict(list)
    for event_at, qty, doc_no, ev_id, cust_id in rows:
        key = doc_no if doc_no else f"__null__{ev_id}"
        buckets[key].append((_parse_event_date(event_at), qty, cust_id))

    excl_count = 0
    excl_qty = 0
    for items in buckets.values():
        net = sum(q for _, q, _ in items)
        if net <= 0:
            continue
        if is_bulk_order(net, stats):
            excl_count += 1
            excl_qty += net
            continue
        if sku_type == "mixed":
            cust_id = items[0][2]
            cust_type = cust_types.get(cust_id) if cust_id else None
            if cust_type not in _MIXED_KEEP_CUSTOMER_TYPES:
                excl_count += 1
                excl_qty += net
                continue
        earliest = min(d for d, _, _ in items)
        week = _monday(earliest)
        if week in series:
            series[week] += net

    return {
        "sku_type": sku_type,
        "series": series,
        "exclusion_count": excl_count,
        "exclusion_qty": excl_qty,
    }


def base_demand_views_bulk(
    barcodes: list[str],
    end_date: date,
    weeks: int,
    session: Session | None = None,
) -> dict[str, dict]:
    """base_demand_view 的批量版: 常数次查询 (≤4), 单 SKU 结果与逐个调用一致.

    给简报等一次算几千 SKU 的调用方用, 避免 N+1 (逐个调用每 SKU 3-5 次查询)。
    取数 3 次按 barcode 集合取齐: last_sale / 全历史 doc-net / 窗口事件,
    出现 mixed 再 +1 次客户类型; 分类复用 categorizer 纯函数
    (classify_sku_type_from_docs + dying 周数判定, as_of=end_date 同 base_demand_view)。
    """
    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    barcodes = list(dict.fromkeys(barcodes))
    if not barcodes:
        return {}
    if session is None:
        with stockpile_db._session() as s:
            return base_demand_views_bulk(barcodes, end_date, weeks, s)

    from sqlalchemy import String, case, cast, func, literal, or_

    from app.utils.categorizer import (
        _DYING_WEEKS,
        _DYING_WEEKS_WHOLESALE,
        _parse_date,
        classify_sku_type_from_docs,
    )

    # 1) 每 SKU 最后销售时间 (dying 判定)
    last_sale = dict(
        session.execute(
            select(InventoryEvent.product_barcode, func.max(InventoryEvent.event_at))
            .where(
                InventoryEvent.event_type == "sale",
                InventoryEvent.product_barcode.in_(barcodes),
            )
            .group_by(InventoryEvent.product_barcode)
        ).all()
    )

    # 2) 每 SKU 全历史 doc-net qty (语义同 _fetch_sku_doc_net_qty: 同 doc 求和,
    #    无单号按事件各自独立, 净量 <= 0 丢弃)。
    # 注意: 导入器把空单号写成 ''(非 NULL), Python 路径 `doc_no if doc_no else ...`
    # 对 '' 同样按独立事件处理 → SQL 分组必须 NULL 和 '' 都落到 per-id 键, 否则
    # 同 SKU 全部空单号历史被并成一个 doc, IQR/分类口径漂移 (review 阻断项)。
    doc_key = case(
        (
            or_(InventoryEvent.document_no.is_(None), InventoryEvent.document_no == ""),
            literal("__null__").op("||")(cast(InventoryEvent.id, String)),
        ),
        else_=InventoryEvent.document_no,
    )
    doc_nets: dict[str, list[int]] = defaultdict(list)
    for bc, net in session.execute(
        select(InventoryEvent.product_barcode, func.sum(InventoryEvent.qty))
        .where(
            InventoryEvent.event_type == "sale",
            InventoryEvent.product_barcode.in_(barcodes),
        )
        .group_by(InventoryEvent.product_barcode, doc_key)
        .having(func.sum(InventoryEvent.qty) > 0)
    ).all():
        doc_nets[bc].append(int(net))

    def _classify(bc: str) -> str:
        # 与 categorizer.classify_sku_type 同语义 (类型感知 dying, ADR-0002):
        # 一致性由 test_bulk_matches_per_sku_view 守护。
        last_at = last_sale.get(bc)
        if last_at is None:
            return "unclassified"
        weeks_since = (end_date - _parse_date(str(last_at))).days // 7
        if weeks_since >= _DYING_WEEKS_WHOLESALE:
            return "dying"
        base = classify_sku_type_from_docs(doc_nets.get(bc, []))
        if weeks_since >= _DYING_WEEKS and base != "wholesale_only":
            return "dying"
        return base

    sku_types = {bc: _classify(bc) for bc in barcodes}
    out: dict[str, dict] = {}
    active: list[str] = []
    for bc in barcodes:
        if sku_types[bc] in ("wholesale_only", "dying", "unclassified"):
            out[bc] = {
                "sku_type": sku_types[bc],
                "series": None,
                "exclusion_count": 0,
                "exclusion_qty": 0,
            }
        else:
            active.append(bc)
    if not active:
        return out

    end_monday = _monday(end_date)
    week_starts = [end_monday - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)]
    window_start = week_starts[0]
    window_end_exclusive = end_monday + timedelta(days=7)

    # 3) 窗口事件 (仅 retail_dominant / mixed 需要)
    win_rows = session.execute(
        select(
            InventoryEvent.product_barcode,
            InventoryEvent.event_at,
            InventoryEvent.qty,
            InventoryEvent.document_no,
            InventoryEvent.id,
            InventoryEvent.customer_id,
        ).where(
            InventoryEvent.event_type == "sale",
            InventoryEvent.product_barcode.in_(active),
            InventoryEvent.event_at >= window_start.isoformat(),
            InventoryEvent.event_at < window_end_exclusive.isoformat(),
        )
    ).all()

    # 4) mixed SKU 的客户类型
    mixed_cust_ids = {r[5] for r in win_rows if r[5] and sku_types[r[0]] == "mixed"}
    cust_types = _fetch_customer_types(mixed_cust_ids, session) if mixed_cust_ids else {}

    buckets: dict[str, dict[str, list[tuple[date, int, str | None]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for bc, event_at, qty, doc_no, ev_id, cust_id in win_rows:
        key = doc_no if doc_no else f"__null__{ev_id}"
        buckets[bc][key].append((_parse_event_date(event_at), qty, cust_id))

    for bc in active:
        stats = compute_doc_qty_stats(doc_nets.get(bc, []))
        series: dict[date, int] = {w: 0 for w in week_starts}
        excl_count = 0
        excl_qty = 0
        for items in buckets.get(bc, {}).values():
            net = sum(q for _, q, _ in items)
            if net <= 0:
                continue
            if is_bulk_order(net, stats):
                excl_count += 1
                excl_qty += net
                continue
            if sku_types[bc] == "mixed":
                cust_id = items[0][2]
                cust_type = cust_types.get(cust_id) if cust_id else None
                if cust_type not in _MIXED_KEEP_CUSTOMER_TYPES:
                    excl_count += 1
                    excl_qty += net
                    continue
            week = _monday(min(d for d, _, _ in items))
            if week in series:
                series[week] += net
        out[bc] = {
            "sku_type": sku_types[bc],
            "series": series,
            "exclusion_count": excl_count,
            "exclusion_qty": excl_qty,
        }
    return out


def _fetch_customer_types(cust_ids: set[str], session: Session) -> dict[str, str]:
    if not cust_ids:
        return {}
    from app.models import Customer

    rows = session.execute(
        select(Customer.customer_id, Customer.customer_type).where(
            Customer.customer_id.in_(cust_ids)
        )
    ).all()
    return {cid: ctype for cid, ctype in rows}
