"""SKU 4 类自动分类（阶段 5 PR 5.1）。

按**总销售时间序列**判（v1 客户端拆分仅展示，不进算法）。

| 类别 | 规则 |
|---|---|
| new        | 首次销售距 as_of < 4 周 |
| seasonal   | 周销量序列长度 ≥ 52 周 + 滞后 52 周 ACF > 0.5 + 至少 2 完整年度重复峰季 |
| declining  | 最近 4 周斜率 < 0 + 上一季度销量比再上一季度跌 ≥ 30% |
| stable     | 寿命 ≥ 26 周 + 销售周占比 ≥ 50% + 最近 12 周斜率 ∈ [-10%, +10%] |
| unclassified | 都不满足 |

判定优先级：new > seasonal > declining > stable > unclassified（防冲突）。

`manual_category` 不为空 → 覆盖 auto_category（dashboard 显示由前端按
`effective_category(stockpile)` 决定，本模块只算 auto）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select

from app.repositories import stockpile_db
from app.models import InventoryEvent

# 阈值常量（spec 锁定）
_NEW_MIN_DAYS = 28  # < 4 周
_SEASONAL_MIN_WEEKS = 52  # ≥ 1 年周销量
_SEASONAL_LAG = 52
_SEASONAL_ACF_THRESHOLD = 0.5
_SEASONAL_MIN_ACTIVE_WEEKS = 10  # 全年至少 10 周有销量；防 3 笔散点偶然 ACF 高
_SEASONAL_PEAK_QUANTILE = 0.8  # 顶 20% 周算 "峰季"
_SEASONAL_PEAK_OVERLAP = 0.3  # 两年峰周重叠率阈值
_DECLINING_RECENT_WEEKS = 4
_DECLINING_QUARTER_DROP = 0.3
_STABLE_MIN_DAYS = 182  # ≥ 26 周
_STABLE_ACTIVE_WEEKS_RATIO = 0.5
_STABLE_TREND_BAND = 10.0  # ±10%
_STABLE_TREND_WEEKS = 12

CATEGORIES = ("new", "seasonal", "declining", "stable", "unclassified")

# SKU 销售形态分类 (plan 2026-05-12-forecast-and-backtest.md §1.0.2, 与生命周期正交)
SKU_TYPES = ("retail_dominant", "mixed", "wholesale_only", "dying", "unclassified")

# 阈值 (spike _scratch/spike_sku_type_thresholds.py 验证, 5 个退场标准 barcode 全过)
_RETAIL_QTY_THRESHOLD = 24
_WHOLESALE_MIN_RETAIL_ROWS = 5
_WHOLESALE_MIN_RETAIL_RATIO = 0.05
_RETAIL_DOMINANT_RATIO = 0.80

# dying 阈值: 最后销售距 as_of >= 13 周 (无 sale event) → dying
# 阻止 CrostonSBA / NaiveSeasonal 在 dying SKU 上过预测 (4 baseline 回测发现 +0.89 系统性 bias)
_DYING_WEEKS = 13


def _today() -> date:
    return datetime.now().date()


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def classify_sku(
    barcode: str,
    as_of: date | None = None,
    session=None,
) -> str:
    """单 SKU 入口（自带一次 SQL）。返回 CATEGORIES 中之一。"""
    as_of = as_of or _today()
    rows = _fetch_sale_rows(barcode, session)
    return classify_from_sales([(r.event_at, r.qty) for r in rows], as_of)


def classify_from_sales(rows: list[tuple[str, int]], as_of: date) -> str:
    """rows: list of (event_at_str, qty) — 让批量路径预拉一次性事件后免 N+1。"""
    if not rows:
        return "unclassified"

    qtys_by_date: dict[date, int] = {}
    for at, qty in rows:
        d = _parse_date(at)
        qtys_by_date[d] = qtys_by_date.get(d, 0) + qty

    first_sale = min(qtys_by_date)
    days_since_first = (as_of - first_sale).days

    if days_since_first < _NEW_MIN_DAYS:
        return "new"

    weekly = _weekly_series(qtys_by_date, first_sale, as_of)

    if _is_seasonal(weekly):
        return "seasonal"
    if _is_declining(weekly, qtys_by_date, as_of):
        return "declining"
    if _is_stable(weekly, days_since_first):
        return "stable"
    return "unclassified"


# ---- 4 类内部判定 ---------------------------------------------------------


def _is_seasonal(weekly: list[int]) -> bool:
    """周销量长度 ≥ 52 + ACF(52) > 0.5 + 两年峰周对得上。"""
    n = len(weekly)
    if n < _SEASONAL_MIN_WEEKS:
        return False
    active_weeks = sum(1 for w in weekly if w > 0)
    if active_weeks < _SEASONAL_MIN_ACTIVE_WEEKS:
        return False
    acf52 = _acf_at_lag(weekly, _SEASONAL_LAG)
    if acf52 is None or acf52 <= _SEASONAL_ACF_THRESHOLD:
        return False
    # 至少两个完整年度峰周重叠
    if n < _SEASONAL_LAG * 2:
        # 不够 2 年完整数据，ACF 通过但峰周对照样本不够 → 算 seasonal（保守通过）
        return True
    return _peaks_overlap(weekly)


def _is_declining(weekly: list[int], qtys_by_date: dict[date, int], as_of: date) -> bool:
    """最近 4 周线性回归 < 0 + 上一季度比再上一季度跌 ≥ 30%。"""
    if len(weekly) < _DECLINING_RECENT_WEEKS:
        return False
    recent = weekly[-_DECLINING_RECENT_WEEKS:]
    if sum(recent) == 0:
        return False
    x = np.arange(len(recent), dtype=float)
    y = np.asarray(recent, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    if slope >= 0:
        return False

    # 上一季度 vs 再上一季度
    q_now_end = as_of
    q_now_start = as_of - timedelta(days=90)
    q_prev_start = as_of - timedelta(days=180)
    q_now = sum(q for d, q in qtys_by_date.items() if q_now_start <= d < q_now_end)
    q_prev = sum(q for d, q in qtys_by_date.items() if q_prev_start <= d < q_now_start)
    if q_prev <= 0:
        return False
    drop = (q_prev - q_now) / q_prev
    return drop >= _DECLINING_QUARTER_DROP


def _is_stable(weekly: list[int], days_since_first: int) -> bool:
    if days_since_first < _STABLE_MIN_DAYS:
        return False
    if len(weekly) == 0:
        return False
    active_weeks = sum(1 for w in weekly if w > 0)
    if active_weeks / len(weekly) < _STABLE_ACTIVE_WEEKS_RATIO:
        return False
    if len(weekly) < _STABLE_TREND_WEEKS:
        return False
    recent = weekly[-_STABLE_TREND_WEEKS:]
    if sum(recent) == 0:
        return False
    y = np.asarray(recent, dtype=float)
    mean = float(y.mean())
    if mean <= 0:
        return False
    x = np.arange(len(recent), dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    pct = slope / mean * 100.0
    return -_STABLE_TREND_BAND <= pct <= _STABLE_TREND_BAND


# ---- 核心算法 -------------------------------------------------------------


def _weekly_series(qtys_by_date: dict[date, int], first: date, as_of: date) -> list[int]:
    """从 first 那周开始（周日为周末），到 as_of 那周为止，每 7 天聚合一格。

    长度 = ceil((as_of - first).days / 7) + 1。空周补 0。
    """
    span_days = (as_of - first).days
    if span_days < 0:
        return []
    n_weeks = span_days // 7 + 1
    weekly = [0] * n_weeks
    for d, q in qtys_by_date.items():
        delta = (d - first).days
        if 0 <= delta < n_weeks * 7:
            weekly[delta // 7] += q
    return weekly


def _acf_at_lag(series: list[int], lag: int) -> float | None:
    """自相关函数（unbiased）：lag 重叠对的均值积 / 全长方差均值。

    用 unbiased 估计是因为我们要在 lag 接近 N/2 处检测年度周期，
    biased 版本会被大 N 平均稀释（如 N=70 lag=52，理论纯正弦只能得 ~0.26）。
    unbiased 在小样本下方差变大但偏差更小，配合 spec 阈值 0.5 才有意义。

    lag ≤ 0 或 ≥ N，或方差 = 0 → 返回 None。
    """
    n = len(series)
    if lag <= 0 or lag >= n:
        return None
    y = np.asarray(series, dtype=float)
    mean = y.mean()
    centered = y - mean
    var_mean = float((centered * centered).sum() / n)
    if var_mean <= 0:
        return None
    overlap = n - lag
    cov_mean = float((centered[lag:] * centered[:-lag]).sum() / overlap)
    return cov_mean / var_mean


def _peaks_overlap(weekly: list[int]) -> bool:
    """周序列里取 80% 分位以上为"峰周"，看两个 52 周窗口（前后各一年）的
    峰周重叠率 ≥ _SEASONAL_PEAK_OVERLAP 即 True。"""
    n = len(weekly)
    if n < _SEASONAL_LAG * 2:
        return False
    y = np.asarray(weekly, dtype=float)
    threshold = float(np.quantile(y, _SEASONAL_PEAK_QUANTILE))
    if threshold <= 0:
        return False
    year_a = y[-_SEASONAL_LAG * 2 : -_SEASONAL_LAG]
    year_b = y[-_SEASONAL_LAG:]
    peaks_a = {i for i, v in enumerate(year_a) if v >= threshold}
    peaks_b = {i for i, v in enumerate(year_b) if v >= threshold}
    if not peaks_a or not peaks_b:
        return False
    overlap = len(peaks_a & peaks_b) / max(len(peaks_a | peaks_b), 1)
    return overlap >= _SEASONAL_PEAK_OVERLAP


# ---- 数据访问 -------------------------------------------------------------


def _fetch_sale_rows(barcode: str, session) -> list[Any]:
    stmt = select(
        InventoryEvent.event_at,
        InventoryEvent.qty,
    ).where(
        InventoryEvent.product_barcode == barcode,
        InventoryEvent.event_type == "sale",
    )
    if session is not None:
        return list(session.execute(stmt).all())
    with stockpile_db._session() as s:
        return list(s.execute(stmt).all())


# ---- SKU 销售形态分类 (plan §1.0.2) -------------------------------------------


def classify_sku_type(barcode: str, session=None, as_of: date | None = None) -> str:
    """单 SKU 销售形态: retail_dominant / mixed / wholesale_only / dying / unclassified.

    判定顺序 (优先级从高到低):
    1. 无任何销售 → unclassified
    2. 最后销售距 as_of >= _DYING_WEEKS 周 → dying (优先于 wholesale, 因为停售更紧急)
    3. doc-net qty 算 retail_dominant / mixed / wholesale_only

    as_of 默认 today; 跟回测窗口配套时应传 backtest 的 end_date.
    """
    as_of = as_of or _today()
    last_at = _fetch_last_sale_at(barcode, session)
    if last_at is None:
        return "unclassified"
    weeks_since = (as_of - _parse_date(last_at)).days // 7
    if weeks_since >= _DYING_WEEKS:
        return "dying"
    net_qtys = _fetch_sku_doc_net_qty(barcode, session)
    return classify_sku_type_from_docs(net_qtys)


def _fetch_last_sale_at(barcode: str, session) -> str | None:
    """返回该 SKU 最后一笔 sale 的 event_at (str), 无销售返回 None."""
    from sqlalchemy import func as sa_func

    stmt = select(sa_func.max(InventoryEvent.event_at)).where(
        InventoryEvent.event_type == "sale",
        InventoryEvent.product_barcode == barcode,
    )
    if session is not None:
        return session.execute(stmt).scalar()
    with stockpile_db._session() as s:
        return s.execute(stmt).scalar()


def classify_sku_type_from_docs(net_qtys: list[int]) -> str:
    """纯函数: 输入每 doc 销售净量 (> 0) 列表, 返回 SKU_TYPES 之一.

    判定 (plan §1.0.2):
    - 零售样本 = 净量 <= _RETAIL_QTY_THRESHOLD
    - wholesale_only: 零售样本 < _WHOLESALE_MIN_RETAIL_ROWS
                      OR 零售占比 < _WHOLESALE_MIN_RETAIL_RATIO
    - retail_dominant: 零售占比 >= _RETAIL_DOMINANT_RATIO
    - 其余 mixed; 空输入 unclassified
    """
    total = len(net_qtys)
    if total == 0:
        return "unclassified"
    retail = sum(1 for q in net_qtys if q <= _RETAIL_QTY_THRESHOLD)
    ratio = retail / total
    if retail < _WHOLESALE_MIN_RETAIL_ROWS or ratio < _WHOLESALE_MIN_RETAIL_RATIO:
        return "wholesale_only"
    if ratio >= _RETAIL_DOMINANT_RATIO:
        return "retail_dominant"
    return "mixed"


def _fetch_sku_doc_net_qty(barcode: str, session) -> list[int]:
    """单 SKU 全历史 sale doc-net qty 列表 (> 0).

    同 document_no 内所有事件 qty 求和; None doc_no 按事件主键各自独立.
    净量 <= 0 (孤儿退货 / 完全冲销) 丢弃, 不参与分母.
    """
    stmt = select(
        InventoryEvent.document_no,
        InventoryEvent.qty,
        InventoryEvent.id,
    ).where(
        InventoryEvent.event_type == "sale",
        InventoryEvent.product_barcode == barcode,
    )
    if session is not None:
        rows = list(session.execute(stmt).all())
    else:
        with stockpile_db._session() as s:
            rows = list(s.execute(stmt).all())

    buckets: dict[str, int] = {}
    for doc_no, qty, ev_id in rows:
        key = doc_no if doc_no else f"__null__{ev_id}"
        buckets[key] = buckets.get(key, 0) + qty
    return [q for q in buckets.values() if q > 0]
