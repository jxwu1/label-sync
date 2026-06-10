"""analytics 共享底座: 常量 + 取数 helper + 通用纯函数 (split-only 拆分自 analytics)。

叶子模块, 不依赖其他 analytics 子模块。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, InventoryEvent
from app.repositories import stockpile_db

_TREND_WEEKS = 12  # 趋势斜率窗口（plan 锁定 12 周）
_VELOCITY_WEEKS = 26  # 周销速窗口（补货决策面板用，固定 26 周）
_NEW_ITEM_LIFESPAN_DAYS = 28  # < 4 周算新品，紧迫分不可信
_URGENCY_COVER_TARGET_WEEKS = 8  # 期望库存可撑 8 周
_URGENCY_RECENCY_FULL_DAYS = 180  # 距上次进货 180 天达到满分
_FREQ_WINDOW_DAYS = 365  # 采购频率回看窗口
_DAYS_PER_MONTH = 30.44  # 老外端月均频率分母


def _today() -> date:
    return datetime.now().date()


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _net_unit(unit_price: float | None, discount_pct: float | None) -> float:
    """折后单价 = unit_price × (1 − discount/100)。任一为 None 当 0 处理。"""
    return (unit_price or 0.0) * (1.0 - (discount_pct or 0.0) / 100.0)


def _is_retail_customer(customer_id: str | None, customer_name: str | None) -> bool:
    """ERP 零售识别 (2026-05-23 改用客户口径, 弃 document_no 规则).

    用户决策: "只要客户id不是0, 名字不含零售的, 基本上都是批发".
    MB 前缀分布查实际有 MB6/7/8/9/2/1 多种, 无法用前缀切分零售 vs 批发.
    改用客户:
      零售 = customer_id == "0", 或 customer_name 含 "零售"
      批发 = 其他 (含 customer_id 为空的, 当批发处理 - 罕见, 内部入库等)
    """
    if customer_id == "0":
        return True
    if customer_name and "零售" in customer_name:
        return True
    return False


def _run_pct(session, stmt, barcode: str) -> float | None:
    row = session.execute(stmt, {"bc": barcode}).first()
    if row is None or row[0] is None:
        return None
    return round(float(row[0]), 1)


def _fetch_all_rows_with_doc_no(barcode: str, session: Session | None):
    """全 events with customer info (零售判定用 customer_id + customer_name)."""
    stmt = (
        select(
            InventoryEvent.event_at,
            InventoryEvent.event_type,
            InventoryEvent.qty,
            InventoryEvent.unit_price,
            InventoryEvent.discount_pct,
            InventoryEvent.document_no,
            InventoryEvent.customer_id,
            Customer.customer_name,
        )
        .join(Customer, Customer.customer_id == InventoryEvent.customer_id, isouter=True)
        .where(InventoryEvent.product_barcode == barcode)
    )
    if session is not None:
        return session.execute(stmt).all()
    with stockpile_db._session() as s:
        return s.execute(stmt).all()


def fetch_event_rows(barcode: str, session: Session | None = None):
    """全事件行的公开入口: 路由层一次取数, 传给 extras/holding/heatmap 复用去重。

    返回与各 compute_* 内部取数一致的 Row 序列 (event_at/event_type/qty/
    unit_price/discount_pct/document_no/customer_id/customer_name)。
    """
    # 经包命名空间解析, 保留 tests/routes 对 analytics._fetch_all_rows_with_doc_no
    # 的 monkeypatch seam (拆包前是同模块 global lookup, 行为不变)。
    import app.services.analytics as _pkg

    return _pkg._fetch_all_rows_with_doc_no(barcode, session)


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
