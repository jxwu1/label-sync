"""货号销售/采购指标 + 客户端拆分 (split-only 拆分自 analytics)。

每个 SKU 算 dashboard 展示用的指标，**不落表**，每次查询即时算。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import CONFIG
from app.models import Customer, InventoryEvent, Stockpile
from app.repositories import stockpile_db
from app.services.analytics._shared import (
    _FREQ_WINDOW_DAYS,
    _TREND_WEEKS,
    _customer_end_metrics,
    _fetch_all_rows,
    _fetch_all_rows_with_doc_no,
    _fetch_sale_rows,
    _fetch_sale_rows_with_customer_type,
    _is_retail_customer,
    _net_unit,
    _parse_date,
    _run_pct,
    _today,
    _trend_slope_pct,
    _weekly_qty_array,
)
from app.services.sku_origin import classify_origin


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

    # 毛利率: 走 origin-aware 主档优先, 跟 list_sku_summary 对齐 (2026-05-23).
    # 旧的 _avg_margin_pct 直接平均事件 unit_price, 对 CN 货 RMB vs EUR 错配 → -115% 假亏损.
    avg_margin_pct = _origin_aware_margin_pct(barcode, session)

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


def _origin_aware_margin_pct(barcode: str, session: Session | None) -> float | None:
    """Origin-aware margin (与 list_sku_summary 一致):
    sale: 优先 stockpile.sale_price (主档稳定), 退批发 events 净均价
    cost: FOREIGN 优先 last_purchase_unit_price (EUR), 退 master_stock_price_eur
          CN/HZ 仅 master_stock_price_eur (last_purchase 是 RMB, 不可用)
    """

    def _query(s: Session) -> float | None:
        sp = s.execute(
            select(
                Stockpile.product_model,
                Stockpile.supplier_id,
                Stockpile.sale_price,
                Stockpile.last_purchase_unit_price,
                Stockpile.master_stock_price_eur,
            ).where(Stockpile.product_barcode == barcode)
        ).first()
        if sp is None:
            return None
        model, sup_id, sale_p, last_pp, master_pp = sp
        origin = classify_origin(sup_id, model)
        cost: float | None = None
        if origin in ("CN", "HZ"):
            if master_pp is not None and master_pp > 0:
                cost = float(master_pp)
        else:
            if last_pp is not None and last_pp > 0:
                cost = float(last_pp)
            elif master_pp is not None and master_pp > 0:
                cost = float(master_pp)
        if cost is None:
            return None
        sale: float | None = float(sale_p) if sale_p and sale_p > 0 else None
        if sale is None:
            return None
        return round((sale - cost) / sale * 100.0, 2)

    if session is not None:
        return _query(session)
    with stockpile_db._session() as s:
        return _query(s)


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


def compute_weekly_timeline(
    barcode: str,
    weeks: int = 156,
    as_of: date | None = None,
    session: Session | None = None,
) -> list[dict[str, Any]]:
    """每周销量 + 每周采购均价 (折后, EUR 口径).

    最近 `weeks` 周 (含 as_of 当周). 每周返回:
      {week_start, sale_qty, purchase_unit_price (EUR), raw_unit_price_local, currency_local}

    口径 (2026-05-23): 进价 line 统一 EUR 落地成本.
      FOREIGN: event.unit_price 直接是 EUR, 沿用现状
      CN/HZ:   event.unit_price 是 RMB, 套公式
               (运费 × pack_volume / unit_quantity + RMB) / 汇率
               每周返回 EUR cost (chart 用) + 原始 RMB 单价 (tooltip 用)
    无销售/采购时对应字段为 0 / None.
    """
    import json
    from datetime import timedelta

    as_of = as_of or _today()
    rows = _fetch_all_rows(barcode, session)

    # 查 stockpile 主档拿 origin + 包装信息 (CN 公式参数)
    def _query_stockpile(s: Session) -> tuple[str | None, int | None, float | None]:
        sp = s.execute(
            select(Stockpile.supplier_id, Stockpile.product_model, Stockpile.extra).where(
                Stockpile.product_barcode == barcode
            )
        ).first()
        if sp is None:
            return None, None, None
        sup_id, model, extra = sp
        origin = classify_origin(sup_id, model)
        unit_qty: int | None = None
        pack_vol: float | None = None
        if extra:
            try:
                ex = json.loads(extra) if isinstance(extra, str) else extra
                uq = ex.get("unit_quantity")
                if uq is not None:
                    unit_qty = int(float(uq))
                pv = ex.get("pack_volume")
                if pv is not None:
                    pack_vol = float(pv)
            except (ValueError, TypeError):
                pass
        return origin, unit_qty, pack_vol

    if session is not None:
        origin, unit_qty, pack_vol = _query_stockpile(session)
    else:
        with stockpile_db._session() as s:
            origin, unit_qty, pack_vol = _query_stockpile(s)

    is_cn = origin in ("CN", "HZ")
    rate = CONFIG.cn_exchange_rate_rmb_per_eur if is_cn else None
    shipping_per_unit_rmb = 0.0
    if is_cn and pack_vol and pack_vol > 0 and unit_qty and unit_qty > 0:
        shipping_per_unit_rmb = CONFIG.cn_shipping_rate_rmb_per_m3 * pack_vol / unit_qty

    sale_buckets = [0] * weeks
    purchase_prices_eur: list[list[float]] = [[] for _ in range(weeks)]
    purchase_prices_raw: list[list[float]] = [[] for _ in range(weeks)]

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
            if net <= 0:
                continue
            if is_cn and rate and rate > 0:
                landed_eur = (net + shipping_per_unit_rmb) / rate
                purchase_prices_eur[idx].append(landed_eur)
                purchase_prices_raw[idx].append(net)
            else:
                purchase_prices_eur[idx].append(net)
                purchase_prices_raw[idx].append(net)

    currency_local = "RMB" if is_cn else "EUR"
    timeline: list[dict[str, Any]] = []
    for i in range(weeks):
        week_end = as_of - timedelta(days=(weeks - 1 - i) * 7)
        week_start = week_end - timedelta(days=6)
        eur_prices = purchase_prices_eur[i]
        raw_prices = purchase_prices_raw[i]
        avg_eur = round(sum(eur_prices) / len(eur_prices), 4) if eur_prices else None
        avg_raw = round(sum(raw_prices) / len(raw_prices), 2) if raw_prices else None
        timeline.append(
            {
                "week_start": week_start.isoformat(),
                "sale_qty": int(sale_buckets[i]),
                "purchase_unit_price": avg_eur,
                "raw_unit_price_local": avg_raw,
                "currency_local": currency_local,
            }
        )
    return timeline


def compute_monthly_sales(
    barcode: str,
    months: int = 36,
    as_of: date | None = None,
    session: Session | None = None,
) -> list[dict[str, Any]]:
    """月度销量聚合 (2026-05-23): timeline 扩 3 年后柱状图改月度避免过密.

    最近 `months` 月 (含 as_of 当月). 每月返回:
      {month_start: 'YYYY-MM-01', sale_qty: int (含退货负数), retail_qty: int}

    按 (year, month) 桶聚合, retail 单独算 (零售=document_no MB* 或 '0').
    """

    as_of = as_of or _today()
    rows = _fetch_all_rows_with_doc_no(barcode, session)

    def _shift_months(d: date, n: int) -> date:
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        return date(y, m, 1)

    # 计算窗口内每月起点 (months 个), 倒数第 i 月起点 = as_of 月 - i
    start_months: list[date] = []
    base = date(as_of.year, as_of.month, 1)
    for i in range(months - 1, -1, -1):
        start_months.append(_shift_months(base, -i))
    bucket: dict[date, dict[str, int]] = {m: {"sale_qty": 0, "retail_qty": 0} for m in start_months}
    cutoff = start_months[0]  # 最早桶

    for r in rows:
        if r.event_type != "sale":
            continue
        d = _parse_date(r.event_at)
        if d < cutoff:
            continue
        month_key = date(d.year, d.month, 1)
        if month_key not in bucket:
            continue
        if _is_retail_customer(r.customer_id, r.customer_name):
            bucket[month_key]["retail_qty"] += r.qty
        else:
            bucket[month_key]["sale_qty"] += r.qty

    return [
        {
            "month_start": m.isoformat(),
            "sale_qty": int(bucket[m]["sale_qty"]),
            "retail_qty": int(bucket[m]["retail_qty"]),
        }
        for m in start_months
    ]


def compute_sku_extras(
    barcode: str,
    as_of: date | None = None,
    session: Session | None = None,
    rows: list | None = None,
) -> dict[str, Any]:
    """货号历史扩展数据 (2026-05-23): 退货率 / 价格波动 / 客户 TOP10 / 首尾日期.

    返回:
      return_qty / total_sale_qty_gross / return_rate_pct
        gross = 正 qty 销售总数, return_qty = |负 qty| 总数 (退货件数)
        return_rate_pct = return_qty / (gross + return_qty) × 100
      price_mean / price_std / price_min / price_max
        批发 sale 事件 (qty > 0, document_no 非零售) unit_price 统计
      top_customers: [{customer_id, customer_type, qty, last_at}] desc qty, 取 10
      first_event_at / last_event_at: 全事件 (含 sale + purchase) 时间范围
      is_history_truncated: first_event_at <= '2021-06-01' (ETL 边界)
    """
    as_of = as_of or _today()
    rows = rows if rows is not None else _fetch_all_rows_with_doc_no(barcode, session)

    # 1. 退货率 (qty 件数口径)
    pos_qty = sum(r.qty for r in rows if r.event_type == "sale" and r.qty > 0)
    neg_qty = sum(-r.qty for r in rows if r.event_type == "sale" and r.qty < 0)
    return_rate_pct: float | None
    if pos_qty + neg_qty > 0:
        return_rate_pct = round(neg_qty / (pos_qty + neg_qty) * 100.0, 2)
    else:
        return_rate_pct = None

    # 2. 价格波动统计 (仅批发正销售, 滤掉零售 + 退货)
    wholesale_prices = [
        _net_unit(r.unit_price, r.discount_pct)
        for r in rows
        if r.event_type == "sale"
        and r.qty > 0
        and r.unit_price
        and not _is_retail_customer(r.customer_id, r.customer_name)
        and _net_unit(r.unit_price, r.discount_pct) > 0
    ]
    if wholesale_prices:
        mean_p = sum(wholesale_prices) / len(wholesale_prices)
        # 总体标准差 (n 分母, 不是 n-1; 全样本统计描述用)
        if len(wholesale_prices) > 1:
            var_p = sum((p - mean_p) ** 2 for p in wholesale_prices) / len(wholesale_prices)
            std_p = var_p**0.5
        else:
            std_p = 0.0
        price_stats: dict[str, float | int | None] = {
            "mean": round(mean_p, 4),
            "std": round(std_p, 4),
            "min": round(min(wholesale_prices), 4),
            "max": round(max(wholesale_prices), 4),
            "n": len(wholesale_prices),
        }
    else:
        price_stats = {"mean": None, "std": None, "min": None, "max": None, "n": 0}

    # 3. 客户 TOP10 拆 CN + 老外两栏 (2026-05-23):
    #    名字带中文一律 CN (不依赖 customers.customer_type stored 值, 直接看 name)
    #    中国客户单笔大批量, 不拆栏会霸榜老外完全看不见
    top_cn, top_foreign = _compute_top_customers_split(barcode, session)

    # 4. 零售汇总 (单独显示, 不进 TOP10): MB700 单 + customer_id='0'.
    retail_events = [
        r
        for r in rows
        if r.event_type == "sale" and _is_retail_customer(r.customer_id, r.customer_name)
    ]
    retail_qty_lifetime = sum(r.qty for r in retail_events)
    retail_revenue_lifetime = sum(
        r.qty * _net_unit(r.unit_price, r.discount_pct) for r in retail_events if r.unit_price
    )
    retail_n_transactions = len(retail_events)
    retail_last_at: str | None = None
    if retail_events:
        retail_last_at = max(r.event_at for r in retail_events)[:10]
    retail_summary = {
        "qty": int(retail_qty_lifetime),
        "revenue": round(retail_revenue_lifetime, 2),
        "n_transactions": retail_n_transactions,
        "last_at": retail_last_at,
        "avg_ticket_qty": round(retail_qty_lifetime / retail_n_transactions, 1)
        if retail_n_transactions > 0
        else None,
    }

    # 5. 首尾日期 + 完整性
    all_dates = [_parse_date(r.event_at) for r in rows]
    first_event_at: str | None = min(all_dates).isoformat() if all_dates else None
    last_event_at: str | None = max(all_dates).isoformat() if all_dates else None
    is_history_truncated = first_event_at is not None and first_event_at <= "2021-06-01"

    return {
        "return_qty": int(neg_qty),
        "total_sale_qty_gross": int(pos_qty),
        "return_rate_pct": return_rate_pct,
        "price_stats": price_stats,
        "top_customers_cn": top_cn,
        "top_customers_foreign": top_foreign,
        "retail_summary": retail_summary,
        "first_event_at": first_event_at,
        "last_event_at": last_event_at,
        "is_history_truncated": is_history_truncated,
    }


def _compute_top_customers_split(
    barcode: str,
    session: Session | None,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """客户 TOP N 拆 CN + 老外两栏 (2026-05-23).

    返回 (top_cn, top_foreign), 每栏 limit 个.
    排除零售事件 (document_no MB700* 或 '0'), 仅算批发客户.
    客户类型判定: 名字含汉字 → CN.
    """
    from app.utils.customer_classifier import has_chinese_chars

    stmt = (
        select(
            InventoryEvent.customer_id,
            Customer.customer_type,
            Customer.customer_name,
            func.sum(InventoryEvent.qty).label("net_qty"),
            func.max(InventoryEvent.event_at).label("last_at"),
        )
        .join(Customer, Customer.customer_id == InventoryEvent.customer_id, isouter=True)
        .where(
            InventoryEvent.product_barcode == barcode,
            InventoryEvent.event_type == "sale",
            InventoryEvent.customer_id.is_not(None),
            InventoryEvent.customer_id != "0",  # 零售客户 ID=0
            # 排除名字含"零售"的客户 (即使有 ID, 用户决策)
            ~func.coalesce(Customer.customer_name, "").like("%零售%"),
        )
        .group_by(
            InventoryEvent.customer_id,
            Customer.customer_type,
            Customer.customer_name,
        )
        .order_by(func.sum(InventoryEvent.qty).desc())
    )

    def _q(s: Session) -> tuple[list, list]:
        cn: list[dict[str, Any]] = []
        fo: list[dict[str, Any]] = []
        for r in s.execute(stmt).all():
            is_cn = has_chinese_chars(r.customer_name)
            effective_type = "chinese" if is_cn else (r.customer_type or "foreign")
            entry = {
                "customer_id": r.customer_id,
                "customer_type": effective_type,
                "customer_name": r.customer_name,
                "qty": int(r.net_qty or 0),
                "last_at": (r.last_at or "")[:10] if r.last_at else None,
            }
            target = cn if is_cn else fo
            if len(target) < limit:
                target.append(entry)
            if len(cn) >= limit and len(fo) >= limit:
                break
        return cn, fo

    if session is not None:
        return _q(session)
    with stockpile_db._session() as s:
        return _q(s)


def compute_avg_holding_days(
    barcode: str,
    session: Session | None = None,
    rows: list | None = None,
) -> dict[str, Any]:
    """平均持仓周期 (FIFO 简化): 每件货从进货到卖出经历几天.

    算法 (FIFO 近似):
      把所有 purchase events 按时间排序 → 形成 FIFO 队列, 每件标进货日.
      把所有 sale events 按时间排序 → 按 qty 依次从队列取货, 算 (sale_date - purchase_date).
      退货 (qty<0) 退回最早可退队列 (简化: 退到最后被卖那批).
    返回 {avg_days, n_pairs, oldest_held_days}.
      avg_days: 已售件的平均持仓
      oldest_held_days: 当前仓库里最早进的那件已经放了多少天 (压货预警)
      None 表示无法算 (无 purchase 或无 sale).
    """
    rows = rows if rows is not None else _fetch_all_rows_with_doc_no(barcode, session)
    purchases = sorted(
        [r for r in rows if r.event_type == "purchase" and r.qty > 0],
        key=lambda r: r.event_at,
    )
    sales = sorted(
        [r for r in rows if r.event_type == "sale" and r.qty > 0],
        key=lambda r: r.event_at,
    )
    if not purchases or not sales:
        return {"avg_days": None, "n_pairs": 0, "oldest_held_days": None}

    # FIFO 队列: [(进货日, 剩余 qty), ...]
    queue: list[list[Any]] = [[_parse_date(r.event_at), r.qty] for r in purchases]
    holding_days_sum = 0.0
    holding_days_n = 0
    for r in sales:
        sale_d = _parse_date(r.event_at)
        remaining = r.qty
        while remaining > 0 and queue:
            head = queue[0]
            taken = min(remaining, head[1])
            diff = (sale_d - head[0]).days
            holding_days_sum += diff * taken
            holding_days_n += taken
            head[1] -= taken
            remaining -= taken
            if head[1] == 0:
                queue.pop(0)
        if remaining > 0:
            # 销售超出已知进货 (历史不全), 跳过余量
            break

    avg_days: float | None = None
    if holding_days_n > 0:
        avg_days = round(holding_days_sum / holding_days_n, 1)
    # 队列剩余最早的就是当前仓库里压最久的
    oldest_held_days: int | None = None
    if queue:
        oldest_in_stock = queue[0][0]
        oldest_held_days = (_today() - oldest_in_stock).days
    return {
        "avg_days": avg_days,
        "n_pairs": holding_days_n,
        "oldest_held_days": oldest_held_days,
    }


def compute_monthly_heatmap(
    barcode: str,
    years: int = 4,
    as_of: date | None = None,
    session: Session | None = None,
    rows: list | None = None,
) -> dict[str, Any]:
    """月度销量热力图: years 年 × 12 月 矩阵.

    返回 {
      years: ['2023', '2024', '2025', '2026'],  # 最近 years 年 desc 到当年
      matrix: { '2026': [Jan, Feb, ..., Dec], '2025': [...], ... }  # 每月批发净 qty
      max_qty: 最大值 (前端归一化用)
    }
    用于看季节性 (哪个月卖得多) 和年增长 (跨年对比同月).
    """
    as_of = as_of or _today()
    rows = rows if rows is not None else _fetch_all_rows_with_doc_no(barcode, session)
    current_year = as_of.year
    year_list = [str(y) for y in range(current_year - years + 1, current_year + 1)]
    matrix: dict[str, list[int]] = {y: [0] * 12 for y in year_list}
    for r in rows:
        if r.event_type != "sale" or _is_retail_customer(r.customer_id, r.customer_name):
            continue
        d = _parse_date(r.event_at)
        ykey = str(d.year)
        if ykey not in matrix:
            continue
        matrix[ykey][d.month - 1] += r.qty
    max_qty = 0
    for v in matrix.values():
        for q in v:
            if q > max_qty:
                max_qty = q
    return {"years": year_list, "matrix": matrix, "max_qty": int(max_qty)}
