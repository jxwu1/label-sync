"""货号销售/采购指标 + 客户端拆分（阶段 5 PR 5.1）。

每个 SKU 算 dashboard 展示用的指标，**不落表**，每次查询即时算。

三组函数：
- compute_sales_metrics(barcode, as_of) → 销售面 5 数（含 12 周线性回归斜率）
- compute_purchase_metrics(barcode, as_of) → 采购面 4 数（含库存推算 / 毛利率 / 采购频率）
- compute_customer_split(barcode, as_of) → 中国端 / 老外端各 5 数

设计取舍：
- numpy 算斜率，**不引** sklearn / scipy / statsmodels（YAGNI，也是 plan 明确边界）
- as_of 可注入，方便测试和"按月度回溯"用例（默认 today）
- 缺数据返回 0 / None，不抛异常（dashboard 期望永远能渲染）
- 单 SKU 一次 SQL；5 万 SKU 批量算另写 batch 入口（PR 5.1f）
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import date, datetime
from typing import Any

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

import stockpile_db
from categorizer import classify_from_sales
from models import Customer, InventoryEvent, Stockpile

_TREND_WEEKS = 12  # 趋势斜率窗口（plan 锁定 12 周）
_FREQ_WINDOW_DAYS = 365  # 采购频率回看窗口
_DAYS_PER_MONTH = 30.44  # 老外端月均频率分母


def _today() -> date:
    return datetime.now().date()


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _net_unit(unit_price: float | None, discount_pct: float | None) -> float:
    """折后单价 = unit_price × (1 − discount/100)。任一为 None 当 0 处理。"""
    return (unit_price or 0.0) * (1.0 - (discount_pct or 0.0) / 100.0)


def compute_sales_metrics(
    barcode: str,
    as_of: date | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """单 SKU 销售面 5 指标。

    返回:
        total_qty / total_revenue / unique_customers / lifespan_days /
        trend_slope_pct_per_week (None 表示数据不足或全零)
    """
    as_of = as_of or _today()
    rows = _fetch_sale_rows(barcode, session)
    if not rows:
        return {
            "total_qty": 0,
            "total_revenue": 0.0,
            "unique_customers": 0,
            "lifespan_days": 0,
            "trend_slope_pct_per_week": None,
        }

    total_qty = sum(r.qty for r in rows)
    total_revenue = sum(r.qty * _net_unit(r.unit_price, r.discount_pct) for r in rows)
    unique_customers = len({r.customer_id for r in rows if r.customer_id})

    dates = [_parse_date(r.event_at) for r in rows]
    lifespan_days = (max(dates) - min(dates)).days

    weekly = _weekly_qty_array(dates, [r.qty for r in rows], as_of, _TREND_WEEKS)
    trend = _trend_slope_pct(weekly)

    return {
        "total_qty": int(total_qty),
        "total_revenue": round(total_revenue, 2),
        "unique_customers": unique_customers,
        "lifespan_days": lifespan_days,
        "trend_slope_pct_per_week": (round(trend, 2) if trend is not None else None),
    }


def compute_purchase_metrics(
    barcode: str,
    as_of: date | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """单 SKU 采购面 4 指标。

    返回:
        stock_balance        - sum(purchase qty) − sum(sale qty)；可负
        avg_margin_pct       - (售净均价 − 进均价) / 售净均价 × 100；任一面无数据 → None
        purchase_freq_365d   - 最近 365 天采购笔数
        last_purchase_days_ago - 距上次采购天数；从无采购 → None
    """
    as_of = as_of or _today()
    rows = _fetch_all_rows(barcode, session)

    purchase_qty = sum(r.qty for r in rows if r.event_type == "purchase")
    sale_qty = sum(r.qty for r in rows if r.event_type == "sale")
    stock_balance = int(purchase_qty - sale_qty)

    avg_margin_pct = _avg_margin_pct(rows)

    purchase_dates = [_parse_date(r.event_at) for r in rows if r.event_type == "purchase"]
    purchase_freq_365d = sum(
        1 for d in purchase_dates if 0 <= (as_of - d).days <= _FREQ_WINDOW_DAYS
    )
    last_purchase_days_ago = (as_of - max(purchase_dates)).days if purchase_dates else None

    return {
        "stock_balance": stock_balance,
        "avg_margin_pct": avg_margin_pct,
        "purchase_freq_365d": purchase_freq_365d,
        "last_purchase_days_ago": last_purchase_days_ago,
    }


def compute_customer_split(
    barcode: str,
    as_of: date | None = None,
    session: Session | None = None,
) -> dict[str, dict[str, Any]]:
    """中国端 / 老外端各 5 数。

    返回 {"cn": {...}, "fo": {...}}，每端结构：
        qty / unique_customers / max_single_qty / last_at / avg_freq_per_month

    customer_type='mixed' / 'unknown' 不计入任何一端（v1 决策：拆分仅展示）。
    """
    as_of = as_of or _today()
    rows = _fetch_sale_rows_with_customer_type(barcode, session)

    cn_rows = [r for r in rows if r.customer_type == "chinese"]
    fo_rows = [r for r in rows if r.customer_type == "foreign"]

    return {
        "cn": _customer_end_metrics(cn_rows, as_of),
        "fo": _customer_end_metrics(fo_rows, as_of),
    }


def recompute_categories(as_of: date | None = None) -> dict[str, Any]:
    """批量重算所有 active SKU 的 auto_category，写回 stockpile。

    单次 SQL 拉所有销售事件 → 内存 group by barcode → 跑 categorizer → 批量 UPDATE。
    5 万 SKU + 几十万事件应该在数秒内完成。

    返回 {'computed': N, 'by_category': {...}, 'duration_s': T}。
    """
    as_of = as_of or _today()
    started = time.time()
    computed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with stockpile_db._session() as session:
        active_barcodes = [
            r[0]
            for r in session.execute(
                select(Stockpile.product_barcode).where(Stockpile.is_active == 1)
            ).all()
        ]
        sales_rows = session.execute(
            select(
                InventoryEvent.product_barcode,
                InventoryEvent.event_at,
                InventoryEvent.qty,
            ).where(InventoryEvent.event_type == "sale")
        ).all()

        sales_by_bc: dict[str, list[tuple[str, int]]] = {}
        for bc, at, qty in sales_rows:
            sales_by_bc.setdefault(bc, []).append((at, qty))

        counts: Counter[str] = Counter()
        for bc in active_barcodes:
            cat = classify_from_sales(sales_by_bc.get(bc, []), as_of)
            counts[cat] += 1
            session.execute(
                update(Stockpile)
                .where(Stockpile.product_barcode == bc)
                .values(auto_category=cat, auto_category_computed_at=computed_at)
            )
        session.commit()

    return {
        "computed": len(active_barcodes),
        "by_category": dict(counts),
        "duration_s": round(time.time() - started, 2),
    }


# ---- 内部 helper -----------------------------------------------------------


def _fetch_sale_rows(barcode: str, session: Session | None):
    stmt = select(
        InventoryEvent.event_at,
        InventoryEvent.qty,
        InventoryEvent.unit_price,
        InventoryEvent.discount_pct,
        InventoryEvent.customer_id,
    ).where(
        InventoryEvent.product_barcode == barcode,
        InventoryEvent.event_type == "sale",
    )
    if session is not None:
        return session.execute(stmt).all()
    with stockpile_db._session() as s:
        return s.execute(stmt).all()


def _fetch_all_rows(barcode: str, session: Session | None):
    stmt = select(
        InventoryEvent.event_at,
        InventoryEvent.event_type,
        InventoryEvent.qty,
        InventoryEvent.unit_price,
        InventoryEvent.discount_pct,
    ).where(InventoryEvent.product_barcode == barcode)
    if session is not None:
        return session.execute(stmt).all()
    with stockpile_db._session() as s:
        return s.execute(stmt).all()


def _fetch_sale_rows_with_customer_type(barcode: str, session: Session | None):
    stmt = (
        select(
            InventoryEvent.event_at,
            InventoryEvent.qty,
            InventoryEvent.customer_id,
            Customer.customer_type,
        )
        .join(Customer, Customer.customer_id == InventoryEvent.customer_id, isouter=True)
        .where(
            InventoryEvent.product_barcode == barcode,
            InventoryEvent.event_type == "sale",
        )
    )
    if session is not None:
        return session.execute(stmt).all()
    with stockpile_db._session() as s:
        return s.execute(stmt).all()


def _weekly_qty_array(dates: list[date], qtys: list[int], as_of: date, n_weeks: int) -> list[int]:
    """以 as_of 为右端把销量按周（每 7 天一桶）放进长度 n_weeks 的数组，
    最早周在 [0]，最晚周在 [-1]。窗口外的销量丢掉。"""
    weekly = [0] * n_weeks
    for d, q in zip(dates, qtys, strict=True):
        delta = (as_of - d).days
        if 0 <= delta < n_weeks * 7:
            idx = n_weeks - 1 - delta // 7
            weekly[idx] += q
    return weekly


def _trend_slope_pct(weekly: list[int]) -> float | None:
    """对 weekly 做线性回归，返回斜率（每周 % 变化，归一化到均值）。

    None 触发条件：均值 ≤ 0 或长度 < 2。
    """
    if len(weekly) < 2:
        return None
    y = np.asarray(weekly, dtype=float)
    mean = float(y.mean())
    if mean <= 0:
        return None
    x = np.arange(len(weekly), dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return slope / mean * 100.0


def _avg_margin_pct(rows) -> float | None:
    purchase_unit = [r.unit_price for r in rows if r.event_type == "purchase" and r.unit_price]
    sale_net = [
        _net_unit(r.unit_price, r.discount_pct)
        for r in rows
        if r.event_type == "sale" and r.unit_price
    ]
    if not purchase_unit or not sale_net:
        return None
    avg_pp = sum(purchase_unit) / len(purchase_unit)
    avg_sp = sum(sale_net) / len(sale_net)
    if avg_sp <= 0:
        return None
    return round((avg_sp - avg_pp) / avg_sp * 100.0, 2)


def _customer_end_metrics(rows, as_of: date) -> dict[str, Any]:
    if not rows:
        return {
            "qty": 0,
            "unique_customers": 0,
            "max_single_qty": 0,
            "last_at": None,
            "avg_freq_per_month": 0.0,
        }
    qty = int(sum(r.qty for r in rows))
    customers = {r.customer_id for r in rows if r.customer_id}
    max_single = int(max(r.qty for r in rows))
    dates = [_parse_date(r.event_at) for r in rows]
    last_at = max(dates).isoformat()
    span_days = max((as_of - min(dates)).days, 1)
    months = max(span_days / _DAYS_PER_MONTH, 1.0)
    avg_freq_per_month = round(len(rows) / months, 2)

    return {
        "qty": qty,
        "unique_customers": len(customers),
        "max_single_qty": max_single,
        "last_at": last_at,
        "avg_freq_per_month": avg_freq_per_month,
    }
