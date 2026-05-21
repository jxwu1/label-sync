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
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.repositories import stockpile_db
from app.utils.categorizer import classify_from_sales
from app.models import Customer, InventoryEvent, Stockpile, StockpileInventorySnapshot
from app.services.sku_origin import classify_origin

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


def compute_qty_percentile(barcode: str, session: Session | None = None) -> float | None:
    """该 SKU 总销量在所有有销售的 SKU 中的百分位（0-100）。

    用途：dashboard "等级 vs 销量" 对照（高等级低销量 = 等级失真，反之亦然）。
    无销售 → None。
    """
    from sqlalchemy import text

    stmt = text(
        """
        WITH totals AS (
            SELECT product_barcode, SUM(qty) AS total
            FROM inventory_events
            WHERE event_type = 'sale'
            GROUP BY product_barcode
        ),
        me AS (SELECT total FROM totals WHERE product_barcode = :bc)
        SELECT
            CASE WHEN (SELECT COUNT(*) FROM totals) = 0 THEN NULL
                 ELSE
                    (SELECT COUNT(*) FROM totals WHERE total < (SELECT total FROM me)) * 100.0
                    / (SELECT COUNT(*) FROM totals)
            END
        """
    )
    if session is not None:
        return _run_pct(session, stmt, barcode)
    with stockpile_db._session() as s:
        return _run_pct(s, stmt, barcode)


def _run_pct(session, stmt, barcode: str) -> float | None:
    row = session.execute(stmt, {"bc": barcode}).first()
    if row is None or row[0] is None:
        return None
    return round(float(row[0]), 1)


def compute_weekly_timeline(
    barcode: str,
    weeks: int = 52,
    as_of: date | None = None,
    session: Session | None = None,
) -> list[dict[str, Any]]:
    """每周销量 + 每周采购均价（折后）。Canvas 时间线图用。

    最近 `weeks` 周（含 as_of 当周）。每周返回：
        {week_start: 'YYYY-MM-DD', sale_qty: int, purchase_unit_price: float|None}

    purchase_unit_price 是该周内的折后均价（unit_price × (1-discount/100)）。
    无销售/采购时对应字段为 0 / None。
    """
    from datetime import timedelta

    as_of = as_of or _today()
    rows = _fetch_all_rows(barcode, session)

    # 周右端：as_of 那周。第 i 周（i=0..weeks-1）右端 = as_of - i*7 天
    sale_buckets = [0] * weeks
    purchase_prices: list[list[float]] = [[] for _ in range(weeks)]

    for r in rows:
        d = _parse_date(r.event_at)
        delta = (as_of - d).days
        if delta < 0 or delta >= weeks * 7:
            continue
        idx = weeks - 1 - delta // 7
        if r.event_type == "sale":
            sale_buckets[idx] += r.qty
        elif r.event_type == "purchase" and r.unit_price:
            net = _net_unit(r.unit_price, r.discount_pct)
            if net > 0:
                purchase_prices[idx].append(net)

    timeline: list[dict[str, Any]] = []
    for i in range(weeks):
        week_end = as_of - timedelta(days=(weeks - 1 - i) * 7)
        week_start = week_end - timedelta(days=6)
        prices = purchase_prices[i]
        avg_price = round(sum(prices) / len(prices), 2) if prices else None
        timeline.append(
            {
                "week_start": week_start.isoformat(),
                "sale_qty": int(sale_buckets[i]),
                "purchase_unit_price": avg_price,
            }
        )
    return timeline


def _attach_urgency_scores(items: list[dict[str, Any]]) -> None:
    """按 origin 子集算销速分位 → 灌 urgency_score / urgency_breakdown 字段。

    velocity_pctile = 子集内 < self.weekly_velocity 的 SKU 数 / 子集总数。
    新品 / 真停用单独标 None。停用 SKU 不参与分位计算（否则会拉低活跃 SKU）。
    """
    import bisect

    by_origin: dict[str, list[float]] = {}
    for it in items:
        if it["is_truly_discontinued"] or it["is_new_item"]:
            continue
        if it["weekly_velocity"] > 0:
            by_origin.setdefault(it["origin"], []).append(it["weekly_velocity"])
    for vs in by_origin.values():
        vs.sort()

    for it in items:
        if it["is_truly_discontinued"]:
            it["urgency_score"] = None
            it["urgency_breakdown"] = None
            continue
        bucket = by_origin.get(it["origin"], [])
        if not bucket or it["weekly_velocity"] == 0:
            pctile = 0.0
        else:
            idx = bisect.bisect_left(bucket, it["weekly_velocity"])
            pctile = idx / len(bucket)
        breakdown = _compute_urgency_score(
            velocity_pctile=pctile,
            weeks_of_cover=it["weeks_of_cover"],
            last_purchase_days=it["last_purchase_days_ago"],
            is_new_item=it["is_new_item"],
        )
        it["urgency_score"] = breakdown["total"]
        it["urgency_breakdown"] = (
            None if breakdown["total"] is None
            else {
                "velocity": breakdown["velocity"],
                "cover": breakdown["cover"],
                "recency": breakdown["recency"],
                "velocity_pctile": round(pctile, 3),
            }
        )


def _compute_urgency_score(
    velocity_pctile: float | None,
    weeks_of_cover: float | None,
    last_purchase_days: int | None,
    is_new_item: bool = False,
) -> dict[str, Any]:
    """补货紧迫分（0-100）+ 三项分解。

    score = velocity_pctile * 50 + cover_factor * 30 + recency_factor * 20

    分项含义（透明给前端展示用）：
        velocity:  origin 子集内周销速分位 → 卖得越好分越高
        cover:     max(0, 1 - weeks_of_cover / 8) → 8 周内会断货加权；
                   weeks_of_cover=None（无库存数据或销速=0）按 0 处理
        recency:   min(1, days_since_last_purchase / 180) → 越久没补越急；
                   None（从无采购记录）按 0 处理

    新品（lifespan < 28d）数据不足，整体分置 None，前端单独 tab 展示。
    """
    if is_new_item:
        return {"total": None, "velocity": None, "cover": None, "recency": None}

    v = (velocity_pctile or 0.0) * 50.0
    if weeks_of_cover is None:
        c = 0.0
    else:
        # weeks_of_cover 可能 < 0 (ERP 超卖待到货, qty_total 负) → 视为 0 库存,
        # cover 满分. clamp 在 [0, 1] 避免分数溢出.
        woc = max(0.0, weeks_of_cover)
        c = max(0.0, 1.0 - woc / _URGENCY_COVER_TARGET_WEEKS) * 30.0
    if last_purchase_days is None:
        r = 0.0
    else:
        r = min(1.0, last_purchase_days / _URGENCY_RECENCY_FULL_DAYS) * 20.0
    return {
        "total": round(v + c + r, 1),
        "velocity": round(v, 1),
        "cover": round(c, 1),
        "recency": round(r, 1),
    }


def _snapshot_qty_lookup(session: Session) -> tuple[str | None, dict[str, int]]:
    """返回最新 snapshot_date + {product_model: qty_total} 字典。无数据返回 (None, {})."""
    latest_date = session.execute(
        select(func.max(StockpileInventorySnapshot.snapshot_date))
    ).scalar()
    if not latest_date:
        return None, {}
    rows = session.execute(
        select(
            StockpileInventorySnapshot.product_model,
            StockpileInventorySnapshot.qty_total,
        ).where(StockpileInventorySnapshot.snapshot_date == latest_date)
    ).all()
    return latest_date, {r.product_model: int(r.qty_total) for r in rows}


def _lookup_qty(qty_by_model: dict[str, int], barcode: str, model: str | None) -> int | None:
    """rule A (model==model) + rule B (13 位 barcode 取倒数第 2-6 位) 找 qty_total."""
    if model and model in qty_by_model:
        return qty_by_model[model]
    if barcode and len(barcode) == 13:
        short = barcode[-6:-1]  # SUBSTRING(barcode, len-5, 5) 等价
        if short in qty_by_model:
            return qty_by_model[short]
    return None


def list_sku_summary(as_of: date | None = None) -> list[dict[str, Any]]:
    """聚合所有 active SKU 的销售汇总（dashboard 列表页用）。

    单次拉所有 active stockpile 主档 + 所有销售事件（带客户类型），
    内存 group by barcode 算每个 SKU 的指标。199k events / 27k SKU 在
    1-2 秒内完成。

    返回字段：barcode / model / name_zh / auto_category / manual_category /
    manual_grade / total_qty / lifespan_days / trend_slope_pct_per_week /
    qty_percentile / cn_qty / fo_qty / is_grade_inconsistent。
    """
    import bisect

    as_of = as_of or _today()
    velocity_cutoff_days = _VELOCITY_WEEKS * 7
    with stockpile_db._session() as session:
        sp_rows = session.execute(
            select(
                Stockpile.product_barcode,
                Stockpile.product_model,
                Stockpile.product_name_zh,
                Stockpile.auto_category,
                Stockpile.manual_category,
                Stockpile.manual_grade,
                Stockpile.is_truly_discontinued,
            ).where(Stockpile.is_truly_discontinued == False)  # noqa: E712 — SQL eq
        ).all()
        sales_rows = session.execute(
            select(
                InventoryEvent.product_barcode,
                InventoryEvent.event_at,
                InventoryEvent.qty,
                Customer.customer_type,
            )
            .join(Customer, Customer.customer_id == InventoryEvent.customer_id, isouter=True)
            .where(InventoryEvent.event_type == "sale")
        ).all()
        purchase_rows = session.execute(
            select(
                InventoryEvent.product_barcode,
                InventoryEvent.event_at,
                InventoryEvent.supplier_id,
            ).where(InventoryEvent.event_type == "purchase")
        ).all()
        _, qty_by_model = _snapshot_qty_lookup(session)

    by_bc: dict[str, list] = {}
    for r in sales_rows:
        by_bc.setdefault(r.product_barcode, []).append(r)

    # 每条码取最近一笔 purchase 的日期 + supplier_id
    last_purchase: dict[str, tuple[str, str | None]] = {}
    for r in purchase_rows:
        cur = last_purchase.get(r.product_barcode)
        if cur is None or r.event_at > cur[0]:
            last_purchase[r.product_barcode] = (r.event_at, r.supplier_id)

    items: list[dict[str, Any]] = []
    for bc, model, name_zh, auto_cat, manual_cat, grade, is_disc in sp_rows:
        sales = by_bc.get(bc, [])
        total_qty = int(sum(r.qty for r in sales))
        if sales:
            dates = [_parse_date(r.event_at) for r in sales]
            lifespan = (max(dates) - min(dates)).days
            weekly = _weekly_qty_array(dates, [r.qty for r in sales], as_of, _TREND_WEEKS)
            trend = _trend_slope_pct(weekly)
            # 26 周窗口净销量 + 有销售周数
            recent_qty = 0
            recent_weeks: set[tuple[int, int]] = set()
            for r in sales:
                d = _parse_date(r.event_at)
                if 0 <= (as_of - d).days < velocity_cutoff_days:
                    recent_qty += r.qty
                    iso = d.isocalendar()
                    recent_weeks.add((iso[0], iso[1]))
            n_active_weeks = len(recent_weeks)
            weekly_velocity = (recent_qty / n_active_weeks) if n_active_weeks else 0.0
        else:
            lifespan = 0
            trend = None
            weekly_velocity = 0.0
            n_active_weeks = 0
        cn_qty = int(sum(r.qty for r in sales if r.customer_type == "chinese"))
        fo_qty = int(sum(r.qty for r in sales if r.customer_type == "foreign"))
        qty_total = _lookup_qty(qty_by_model, bc, model)
        weeks_of_cover: float | None
        if weekly_velocity > 0 and qty_total is not None:
            weeks_of_cover = round(qty_total / weekly_velocity, 1)
        elif qty_total == 0 and weekly_velocity > 0:
            weeks_of_cover = 0.0
        else:
            weeks_of_cover = None  # 销速 0 → 不缺货也不紧迫；无 snapshot → 未知
        lp = last_purchase.get(bc)
        last_purchase_at = lp[0] if lp else None
        last_purchase_days_ago = (
            (as_of - _parse_date(lp[0])).days if lp else None
        )
        supplier_id = lp[1] if lp else None
        origin = classify_origin(supplier_id, model)
        is_new_item = bool(sales) and lifespan < _NEW_ITEM_LIFESPAN_DAYS
        items.append(
            {
                "barcode": bc,
                "model": model,
                "name_zh": name_zh,
                "auto_category": auto_cat,
                "manual_category": manual_cat,
                "manual_grade": grade,
                "is_truly_discontinued": bool(is_disc),
                "origin": origin,
                "qty_total": qty_total,
                "total_qty": total_qty,
                "weekly_velocity": round(weekly_velocity, 2),
                "n_active_weeks_26w": n_active_weeks,
                "weeks_of_cover": weeks_of_cover,
                "last_purchase_at": last_purchase_at,
                "last_purchase_days_ago": last_purchase_days_ago,
                "lifespan_days": lifespan,
                "is_new_item": is_new_item,
                "trend_slope_pct_per_week": (round(trend, 2) if trend is not None else None),
                "cn_qty": cn_qty,
                "fo_qty": fo_qty,
            }
        )

    # 紧迫分需要先算 origin 子集的销速分位，再灌回 items
    _attach_urgency_scores(items)

    # 全表 percentile：基于有销量 SKU
    sorted_qty = sorted(it["total_qty"] for it in items if it["total_qty"] > 0)
    n_with_sales = len(sorted_qty)
    for it in items:
        if it["total_qty"] > 0 and n_with_sales > 0:
            cnt_below = bisect.bisect_left(sorted_qty, it["total_qty"])
            it["qty_percentile"] = round(cnt_below * 100.0 / n_with_sales, 1)
        else:
            it["qty_percentile"] = None
        # 不一致告警
        g = it["manual_grade"]
        p = it["qty_percentile"]
        warn = False
        if g is not None and p is not None:
            if (g >= 8 and p < 30) or (g <= 3 and p > 70):
                warn = True
        it["is_grade_inconsistent"] = warn

    return items


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
