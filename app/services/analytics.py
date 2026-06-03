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

from app.config import CONFIG
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


# 数据新鲜度: scraper 每周抓一次, 距上次灌数 > 9 天 → 至少漏了一轮, 判定 stale
_DATA_STALE_DAYS = 9


def get_data_freshness(as_of: date | None = None) -> dict[str, Any]:
    """返回数据新鲜度: 基于 max(inventory_events.imported_at)。

    {last_import_at, last_import_date, days_since, stale}
    空库 → 全 None + stale=False (无数据不报红, 避免本地/新系统误报)。
    """
    as_of = as_of or _today()
    with stockpile_db._session() as session:
        last = session.execute(select(func.max(InventoryEvent.imported_at))).scalar()
    if not last:
        return {"last_import_at": None, "last_import_date": None,
                "days_since": None, "stale": False}
    last_date = _parse_date(str(last))
    days = (as_of - last_date).days
    return {
        "last_import_at": str(last),
        "last_import_date": last_date.isoformat(),
        "days_since": days,
        "stale": days > _DATA_STALE_DAYS,
    }


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


def _run_pct(session, stmt, barcode: str) -> float | None:
    row = session.execute(stmt, {"bc": barcode}).first()
    if row is None or row[0] is None:
        return None
    return round(float(row[0]), 1)


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
    from datetime import timedelta
    import json

    as_of = as_of or _today()
    rows = _fetch_all_rows(barcode, session)

    # 查 stockpile 主档拿 origin + 包装信息 (CN 公式参数)
    def _query_stockpile(s: Session) -> tuple[str | None, int | None, float | None]:
        sp = s.execute(
            select(Stockpile.supplier_id, Stockpile.product_model, Stockpile.extra)
            .where(Stockpile.product_barcode == barcode)
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
    from datetime import timedelta
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
    rows = _fetch_all_rows_with_doc_no(barcode, session)

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
            std_p = var_p ** 0.5
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
    retail_events = [r for r in rows if r.event_type == "sale" and _is_retail_customer(r.customer_id, r.customer_name)]
    retail_qty_lifetime = sum(r.qty for r in retail_events)
    retail_revenue_lifetime = sum(
        r.qty * _net_unit(r.unit_price, r.discount_pct)
        for r in retail_events if r.unit_price
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
            if retail_n_transactions > 0 else None,
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
    rows = _fetch_all_rows_with_doc_no(barcode, session)
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
    rows = _fetch_all_rows_with_doc_no(barcode, session)
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


def compute_restock_snapshot(barcode: str) -> dict[str, Any] | None:
    """单 SKU 补货决策快照 (2026-05-23): 给货号历史复用补货 drawer 的指标.

    实现: 调 list_sku_summary 整表算一遍 (含 by-origin pctile), 再 filter 出
    目标 barcode. 是否在批量列表里(active + 非真停用) 都能拉到; 否则返 None.

    性能: 优先按 PK 读物化表单行 (~1ms); 表空/过期才回退 list_sku_summary
    (其本身再回退实时计算 + filter). 货号历史页高频开页不再触发整表重算.
    """
    row = _read_sku_summary_row(barcode, _today())
    if row is not None:
        return row
    # 单行未命中: 表空/过期, 或该货号本就不在汇总 (停用/无主档). 回退批量路径.
    items = list_sku_summary()
    for it in items:
        if it["barcode"] == barcode:
            return it
    return None


def compute_forecast_snapshot(
    barcode: str,
    session: Session | None = None,
) -> dict[str, Any] | None:
    """读 forecast_output 表的最新预测 (refresh_forecast_output 每周刷一次).

    返回 {model_used, n_weeks_history, mu, sigma, p50, p98, quarter_mu, quarter_p98}
    quarter_* = 周值 × 13 (3 个月口径). 无记录返 None.
    """
    from app.models import ForecastOutput
    def _q(s: Session):
        row = s.execute(
            select(ForecastOutput).where(ForecastOutput.product_barcode == barcode)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "model_used": row.model_used,
            "sku_type": row.sku_type,
            "n_weeks_history": row.n_weeks_history,
            "weekly_mu": round(float(row.mu), 2),
            "weekly_p50": round(float(row.p50), 2),
            "weekly_p98": round(float(row.p98), 2),
            "quarter_mu": round(float(row.mu) * 13, 0),
            "quarter_p98": round(float(row.p98) * 13, 0),
            "computed_at": row.computed_at,
        }
    if session is not None:
        return _q(session)
    with stockpile_db._session() as s:
        return _q(s)


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


def _attach_urgency_scores(items: list[dict[str, Any]]) -> None:
    """按 origin 子集算 revenue + margin 双分位 → 灌 urgency_score / urgency_breakdown。

    P2 (2026-05-22) 起公式:
        score = velocity_pctile*30 + cover*30 + recency*10 + margin_pctile*30
    velocity_pctile 仍按 weekly_revenue 排名 (P1 决策).
    margin_pctile 按 margin_pct 排名, 缺 margin (没有 last_purchase_unit_price)
    或负毛利的 SKU → margin_pctile=0 (不加分也不扣).

    新品 / 真停用单独标 None。停用 SKU 不参与分位计算（否则会拉低活跃 SKU）。
    """
    import bisect

    by_origin_rev: dict[str, list[float]] = {}
    by_origin_margin: dict[str, list[float]] = {}
    for it in items:
        if it["is_truly_discontinued"] or it["is_new_item"]:
            continue
        if it["weekly_revenue"] > 0:
            by_origin_rev.setdefault(it["origin"], []).append(it["weekly_revenue"])
        if it["margin_pct"] is not None and it["margin_pct"] > 0:
            by_origin_margin.setdefault(it["origin"], []).append(it["margin_pct"])
    for vs in by_origin_rev.values():
        vs.sort()
    for vs in by_origin_margin.values():
        vs.sort()

    for it in items:
        if it["is_truly_discontinued"]:
            it["urgency_score"] = None
            it["urgency_breakdown"] = None
            continue
        # revenue 分位
        rbucket = by_origin_rev.get(it["origin"], [])
        if not rbucket or it["weekly_revenue"] == 0:
            v_pctile = 0.0
        else:
            idx = bisect.bisect_left(rbucket, it["weekly_revenue"])
            v_pctile = idx / len(rbucket)
        # margin 分位 (缺 margin 或 <=0 → 0 分)
        mbucket = by_origin_margin.get(it["origin"], [])
        if not mbucket or it["margin_pct"] is None or it["margin_pct"] <= 0:
            m_pctile = 0.0
        else:
            idx = bisect.bisect_left(mbucket, it["margin_pct"])
            m_pctile = idx / len(mbucket)
        breakdown = _compute_urgency_score(
            velocity_pctile=v_pctile,
            weeks_of_cover=it["weeks_of_cover"],
            last_purchase_days=it["last_purchase_days_ago"],
            margin_pctile=m_pctile,
            is_new_item=it["is_new_item"],
            n_active_weeks=it.get("n_active_weeks_26w", 0),
        )
        it["urgency_score"] = breakdown["total"]
        it["urgency_breakdown"] = (
            None if breakdown["total"] is None
            else {
                "velocity": breakdown["velocity"],
                "cover": breakdown["cover"],
                "recency": breakdown["recency"],
                "margin": breakdown["margin"],
                "velocity_pctile": round(v_pctile, 3),
                "margin_pctile": round(m_pctile, 3),
                "margin_missing": it["margin_pct"] is None,
                "margin_source": it.get("margin_source"),
                "margin_price_source": it.get("margin_price_source"),
                "demand_validity": breakdown["demand_validity"],
            }
        )


_DEMAND_VALIDITY_FULL_WEEKS = 4  # n_active_weeks_26w >= 4 周才认 cover/recency 满分


def _compute_urgency_score(
    velocity_pctile: float | None,
    weeks_of_cover: float | None,
    last_purchase_days: int | None,
    margin_pctile: float | None = None,
    is_new_item: bool = False,
    n_active_weeks: int = 0,
) -> dict[str, Any]:
    """补货紧迫分（0-100）+ 四项分解。

    P2 (2026-05-22 起) 公式 E:
        score = velocity_pctile*30 + cover*30 + recency*10 + margin_pctile*30

    分项含义（透明给前端展示用）：
        velocity:  origin 子集内周销额 (€/周) 分位 → 销额越大分越高
        cover:     max(0, 1 - weeks_of_cover / 8) → 8 周内断货加权;
                   weeks_of_cover=None (无库存数据或销速=0) 按 0
        recency:   min(1, days_since_last_purchase / 180) → 越久没补越急;
                   None (从无采购) 按 0
        margin:    origin 子集内 margin_pct 分位 → 越赚钱分越高;
                   None (缺 last_purchase_unit_price) 或 <=0 按 0,
                   防止"卖得飞快但不赚钱"的伪好卖货霸占顶部

    新品（lifespan < 28d）数据不足, 整体分置 None, 前端单独 tab 展示。
    """
    if is_new_item:
        return {
            "total": None, "velocity": None, "cover": None,
            "recency": None, "margin": None, "demand_validity": None,
        }

    # demand_validity: 26 周内有销售周数 / 4. 长尾死货 (n_active_weeks=1) → 0.25,
    # cover/recency 卫星分被压到 1/4. 解决"3 年只卖 7 次的货拿满分 cover"问题.
    # velocity 和 margin 已经是分位制不需要再 dv 调整 (分位本身就反映了活跃度).
    dv = min(1.0, n_active_weeks / _DEMAND_VALIDITY_FULL_WEEKS)

    v = (velocity_pctile or 0.0) * 30.0
    if weeks_of_cover is None:
        c = 0.0
    else:
        # weeks_of_cover 可能 < 0 (ERP 超卖待到货, qty_total 负) → 视为 0 库存,
        # cover 满分. clamp 在 [0, 1] 避免分数溢出.
        woc = max(0.0, weeks_of_cover)
        c = max(0.0, 1.0 - woc / _URGENCY_COVER_TARGET_WEEKS) * 30.0 * dv
    if last_purchase_days is None:
        r = 0.0
    else:
        r = min(1.0, last_purchase_days / _URGENCY_RECENCY_FULL_DAYS) * 10.0 * dv
    m = (margin_pctile or 0.0) * 30.0
    return {
        "total": round(v + c + r + m, 1),
        "velocity": round(v, 1),
        "cover": round(c, 1),
        "recency": round(r, 1),
        "margin": round(m, 1),
        "demand_validity": round(dv, 3),
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


# list_sku_summary 60s 内存缓存 (2026-05-23): 整表计算 ~2-3s, 货号历史 / 补货决策
# 每次开页都触发. 60s TTL 平衡新鲜度和延迟. tests setUp 显式 clear_cache 防泄漏.
# Lock 防 thundering herd: 冷启动多个 panel 并发命中, 不加锁会重复计算 N 次.
import threading as _threading

_LIST_CACHE: dict = {"key": None, "value": None, "ts": 0.0}
_LIST_TTL_SECONDS = 60.0
_LIST_LOCK = _threading.Lock()


_RESTOCK_TARGET_WEEKS = _URGENCY_COVER_TARGET_WEEKS  # 默认 8 周


def _round_up_to_pack(qty: int | None, pack: int | None) -> int | None:
    """向上凑整到 pack 的倍数。qty=0 或 pack 无效时原样返回。"""
    if qty is None or qty <= 0 or not pack or pack <= 1:
        return qty
    import math
    return math.ceil(qty / pack) * pack


def _restock_recommendation(
    barcode: str,
    qty_total: int,
    weekly_velocity: float,
    forecast_by_bc: dict,
    last_purchase_qty_by_bc: dict,
    middle_qty: int | None = None,
) -> dict:
    """计算推荐补货量: 优先预测模型 p50/p98, 回退销速, 再回退上次进货量.
    结果向上凑整到中包倍数 (middle_qty)。"""
    import math
    target = _RESTOCK_TARGET_WEEKS
    last_pq = last_purchase_qty_by_bc.get(barcode)
    fc = forecast_by_bc.get(barcode)
    stock = qty_total or 0

    if fc:
        p50, p98, model = fc
        qty_p50 = max(0, math.ceil(p50 * target) - stock)
        qty_p98 = max(0, math.ceil(p98 * target) - stock)
        source = f"forecast:{model}"
    elif weekly_velocity > 0:
        qty_p50 = max(0, math.ceil(weekly_velocity * target) - stock)
        qty_p98 = max(0, math.ceil(weekly_velocity * target * 1.5) - stock)
        source = "velocity"
    elif last_pq:
        qty_p50 = last_pq
        qty_p98 = last_pq
        source = "last_purchase"
    else:
        qty_p50 = None
        qty_p98 = None
        source = None

    qty_p50 = _round_up_to_pack(qty_p50, middle_qty)
    qty_p98 = _round_up_to_pack(qty_p98, middle_qty)

    return {
        "restock_qty_p50": qty_p50,
        "restock_qty_p98": qty_p98,
        "restock_source": source,
        "last_purchase_qty": last_pq,
        "forecast_p50": round(fc[0], 2) if fc else None,
        "forecast_p98": round(fc[1], 2) if fc else None,
    }


def clear_list_sku_summary_cache() -> None:
    """测试 setUp 调用; 也可生产端点 (cron / 手动) 触发刷新."""
    with _LIST_LOCK:
        _LIST_CACHE["key"] = None
        _LIST_CACHE["value"] = None
        _LIST_CACHE["ts"] = 0.0


def refresh_sku_summary(as_of: date | None = None) -> int:
    """整表重算 list_sku_summary 并物化进 sku_summary 表 (每 SKU 一行 payload).

    复用 _list_sku_summary_impl, 物化值 == 实时值 (不重写指标数学). 整表重写
    (先清后批量插), 幂等. 仍拉全量事件进内存算 (几秒), 故只在导入 / cron /
    启动预热时调, 永不在用户开页跑. 返回写入行数.
    """
    from sqlalchemy import delete, insert

    from app.models import SkuSummary

    as_of = as_of or _today()
    items = _list_sku_summary_impl(as_of)
    as_of_iso = as_of.isoformat()
    with stockpile_db._session() as session:
        session.execute(delete(SkuSummary))
        if items:
            session.execute(
                insert(SkuSummary),
                [
                    {
                        "product_barcode": it["barcode"],
                        "as_of": as_of_iso,
                        "payload": it,
                    }
                    for it in items
                ],
            )
        session.commit()
    # 表已换新, 清掉读路径的 60s 内存缓存, 否则会继续吐旧列表.
    clear_list_sku_summary_cache()
    return len(items)


def prewarm_sku_summary() -> None:
    """启动预热: 物化表空 / 非当日 → 重建落表; 已是当日数据 → 只暖内存缓存.

    落表很关键: 否则单货号 PK 快路径会一直 miss 到下次 import/cron 才补上.
    """
    if _read_sku_summary_table(_today()) is None:
        refresh_sku_summary()
    else:
        list_sku_summary()


def list_sku_summary(as_of: date | None = None) -> list[dict[str, Any]]:
    """聚合所有 active SKU 的销售汇总（dashboard 列表页用）。

    60s 内存缓存 + 锁防 thundering herd. 冷启动场景: 多 panel 并发命中时
    只有一个线程算, 其他线程等结果, 避免重复算 N 次.
    """
    import time
    cache_key = (as_of,)
    # 快速路径: 缓存命中无锁返回 (race 也安全, dict 读单字段是原子的)
    now = time.time()
    if (_LIST_CACHE["key"] == cache_key
            and _LIST_CACHE["value"] is not None
            and now - _LIST_CACHE["ts"] < _LIST_TTL_SECONDS):
        return _LIST_CACHE["value"]
    # 慢路径: 拿锁. 拿到后再 check 一次 (double-checked locking),
    # 因为可能在等锁期间另一线程已经填好缓存.
    with _LIST_LOCK:
        now = time.time()
        if (_LIST_CACHE["key"] == cache_key
                and _LIST_CACHE["value"] is not None
                and now - _LIST_CACHE["ts"] < _LIST_TTL_SECONDS):
            return _LIST_CACHE["value"]
        # 表优先: 物化表有当日 as_of 的行就直接用 (避免整表重算 2.9M 事件);
        # 空表 / as_of≠物化日 → 回退实时计算.
        result = _read_sku_summary_table(as_of or _today())
        if result is None:
            result = _list_sku_summary_impl(as_of)
        _LIST_CACHE["key"] = cache_key
        _LIST_CACHE["value"] = result
        _LIST_CACHE["ts"] = now
        return result


def _read_sku_summary_table(as_of: date) -> list[dict[str, Any]] | None:
    """读物化表, 返回该 as_of 的 payload 列表; 无匹配行返回 None (调用方回退实时)."""
    from app.models import SkuSummary

    as_of_iso = as_of.isoformat()
    with stockpile_db._session() as session:
        rows = session.execute(
            select(SkuSummary.payload).where(SkuSummary.as_of == as_of_iso)
        ).all()
    if not rows:
        return None
    return [r[0] for r in rows]


def _read_sku_summary_row(barcode: str, as_of: date) -> dict[str, Any] | None:
    """按 PK 读物化表单行 payload (该 as_of); 无匹配返回 None.

    给单货号场景 (货号历史页) 用, 避免为一个 SKU 加载全表 27k 行 payload.
    """
    from app.models import SkuSummary

    with stockpile_db._session() as session:
        return session.execute(
            select(SkuSummary.payload).where(
                SkuSummary.product_barcode == barcode,
                SkuSummary.as_of == as_of.isoformat(),
            )
        ).scalar_one_or_none()


def _list_sku_summary_impl(as_of: date | None = None) -> list[dict[str, Any]]:
    """实际计算 list_sku_summary 的内部实现 (无缓存层).

    单次拉所有 active stockpile 主档 + 所有销售事件 (带客户类型),
    内存 group by barcode 算每个 SKU 的指标. 199k events / 27k SKU 在
    1-2 秒内完成.
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
                Stockpile.supplier_id,
                Stockpile.last_purchase_unit_price,
                Stockpile.master_stock_price_eur,
                Stockpile.sale_price,
                Stockpile.extra,
            ).where(Stockpile.is_truly_discontinued == False)  # noqa: E712 — SQL eq
        ).all()
        sales_rows = session.execute(
            select(
                InventoryEvent.product_barcode,
                InventoryEvent.event_at,
                InventoryEvent.qty,
                InventoryEvent.unit_price,
                InventoryEvent.discount_pct,
                InventoryEvent.document_no,
                InventoryEvent.customer_id,
                Customer.customer_type,
                Customer.customer_name,
            )
            .join(Customer, Customer.customer_id == InventoryEvent.customer_id, isouter=True)
            .where(InventoryEvent.event_type == "sale")
        ).all()
        purchase_rows = session.execute(
            select(
                InventoryEvent.product_barcode,
                InventoryEvent.event_at,
                InventoryEvent.supplier_id,
                InventoryEvent.qty,
            ).where(InventoryEvent.event_type == "purchase")
        ).all()
        from app.models import ForecastOutput
        forecast_rows = session.execute(
            select(
                ForecastOutput.product_barcode,
                ForecastOutput.p50,
                ForecastOutput.p98,
                ForecastOutput.model_used,
            )
        ).all()
        _, qty_by_model = _snapshot_qty_lookup(session)

    by_bc: dict[str, list] = {}
    for r in sales_rows:
        by_bc.setdefault(r.product_barcode, []).append(r)

    forecast_by_bc: dict[str, tuple[float, float, str]] = {}
    for r in forecast_rows:
        forecast_by_bc[r.product_barcode] = (r.p50, r.p98, r.model_used)

    last_purchase: dict[str, tuple[str, str | None]] = {}
    last_purchase_qty_by_bc: dict[str, int] = {}
    lifetime_purchase_qty_by_bc: dict[str, int] = {}
    for r in purchase_rows:
        cur = last_purchase.get(r.product_barcode)
        if cur is None or r.event_at > cur[0]:
            last_purchase[r.product_barcode] = (r.event_at, r.supplier_id)
            last_purchase_qty_by_bc[r.product_barcode] = int(r.qty)
        lifetime_purchase_qty_by_bc[r.product_barcode] = (
            lifetime_purchase_qty_by_bc.get(r.product_barcode, 0) + r.qty
        )

    import json as _json
    mid_qty_by_bc: dict[str, int] = {}
    for _r in sp_rows:
        if _r.extra:
            try:
                _ex = _json.loads(_r.extra) if isinstance(_r.extra, str) else _r.extra
                _mq = _ex.get("middle_quantity")
                if _mq is not None and str(_mq).strip() not in ("", "0"):
                    mid_qty_by_bc[_r.product_barcode] = int(float(_mq))
            except (ValueError, TypeError):
                pass

    items: list[dict[str, Any]] = []
    for bc, model, name_zh, auto_cat, manual_cat, grade, is_disc, sp_supplier_id, last_pp, master_pp, master_sp, _extra in sp_rows:
        sales = by_bc.get(bc, [])
        # 批发/零售分流: document_no 以 'MB' 开头或 = '0' 算零售, 不进批发聚合.
        # 零售只做透明展示 (retail_qty_26w / retail_revenue_26w), 不污染 weekly_velocity/sale_net_avg.
        # 5206753040071 case: 单笔零售 €8.4677 拉爆批发均价 → 这里干掉.
        wholesale_sales = [r for r in sales if not _is_retail_customer(r.customer_id, r.customer_name)]
        retail_sales = [r for r in sales if _is_retail_customer(r.customer_id, r.customer_name)]
        total_qty = int(sum(r.qty for r in wholesale_sales))
        if wholesale_sales:
            dates = [_parse_date(r.event_at) for r in wholesale_sales]
            lifespan = (max(dates) - min(dates)).days
            weekly = _weekly_qty_array(dates, [r.qty for r in wholesale_sales], as_of, _TREND_WEEKS)
            trend = _trend_slope_pct(weekly)
            # weekly 已经是 _TREND_WEEKS=12 周净销量数组 (最近一周在末尾), 直接复用做 sparkline
            weekly_qty_12w = [int(x) for x in weekly]
            # 26 周窗口净销量 + 净销售额 + 有销售周数 + 销售净加权均价 (仅批发)
            recent_qty = 0
            recent_revenue = 0.0
            recent_weeks: set[tuple[int, int]] = set()
            for r in wholesale_sales:
                d = _parse_date(r.event_at)
                if 0 <= (as_of - d).days < velocity_cutoff_days:
                    recent_qty += r.qty
                    recent_revenue += r.qty * _net_unit(r.unit_price, r.discount_pct)
                    iso = d.isocalendar()
                    recent_weeks.add((iso[0], iso[1]))
            n_active_weeks = len(recent_weeks)
            weekly_velocity = (recent_qty / n_active_weeks) if n_active_weeks else 0.0
            weekly_revenue = (recent_revenue / n_active_weeks) if n_active_weeks else 0.0
            # 销售净加权均价: 26 周窗口内 recent_revenue / recent_qty (仅批发).
            sale_net_avg = (recent_revenue / recent_qty) if recent_qty > 0 else None
        else:
            lifespan = 0
            trend = None
            weekly_velocity = 0.0
            weekly_revenue = 0.0
            n_active_weeks = 0
            weekly_qty_12w = [0] * _TREND_WEEKS
            sale_net_avg = None
            recent_qty = 0
            recent_revenue = 0.0
        # 零售透明字段: 26 周窗口内的零售销量/销售额, 不参与算法, 仅前端展示用.
        retail_qty_26w = 0
        retail_revenue_26w = 0.0
        for r in retail_sales:
            d = _parse_date(r.event_at)
            if 0 <= (as_of - d).days < velocity_cutoff_days:
                retail_qty_26w += r.qty
                retail_revenue_26w += r.qty * _net_unit(r.unit_price, r.discount_pct)
        cn_qty = int(sum(r.qty for r in wholesale_sales if r.customer_type == "chinese"))
        fo_qty = int(sum(r.qty for r in wholesale_sales if r.customer_type == "foreign"))
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
        last_purchase_supplier = lp[1] if lp else None
        # ERP 主档优先 (覆盖"标了供应商但还没产生 purchase event"的 SKU),
        # fallback 到最近 purchase event 的 supplier_id (兼容旧数据)
        supplier_id = sp_supplier_id or last_purchase_supplier
        origin = classify_origin(supplier_id, model)
        is_new_item = bool(sales) and lifespan < _NEW_ITEM_LIFESPAN_DAYS
        # 毛利率: (sale - cost) / sale * 100
        # cost = COALESCE(last_purchase_unit_price, master_stock_price_eur)
        # sale = COALESCE(stockpile.sale_price, sale_net_avg)  ← A 方案 (2026-05-23)
        # 原因: sale_net_avg 来自批发事件均价, 单笔异常单 (如 5206753040071 €8.4677)
        # 会拉爆均价; 主档 sale_price 是 ERP 档案价, 稳定且不受异常单影响.
        # margin_source 标 cost 来源; margin_price_source 标 sale 来源.
        margin_pct: float | None
        margin_source: str | None
        margin_price_source: str | None
        cost: float | None = None
        # cost 优先级取决于 origin (2026-05-23):
        #   FOREIGN: purchase event 是 EUR 原始价 (准) → 优先 last_pp, 退 master_pp
        #   CN/HZ:   purchase event 是 RMB 原始价 (不能当 EUR 用!) → 仅用 master_pp
        #            (落地公式算出的 EUR), 不用 last_pp 避免币种混淆造成 -270% 假亏损
        if origin in ("CN", "HZ"):
            if master_pp is not None and master_pp > 0:
                cost = float(master_pp)
                margin_source = "master"
            else:
                margin_source = None
        else:
            if last_pp is not None and last_pp > 0:
                cost = float(last_pp)
                margin_source = "purchase"
            elif master_pp is not None and master_pp > 0:
                cost = float(master_pp)
                margin_source = "master"
            else:
                margin_source = None
        sale: float | None = None
        if master_sp is not None and master_sp > 0:
            sale = float(master_sp)
            margin_price_source = "master"
        elif sale_net_avg is not None and sale_net_avg > 0:
            sale = float(sale_net_avg)
            margin_price_source = "events"
        else:
            margin_price_source = None
        if sale is not None and sale > 0 and cost is not None:
            margin_pct = round((sale - cost) / sale * 100.0, 2)
        else:
            margin_pct = None
            margin_source = None
            margin_price_source = None

        # 零售价派生 (2026-05-23): ERP 端点只导一个批发 sale_price tier.
        # 启发式: 大部分 SKU 零售=批发×2 (用户验证).
        # 优先用历史观测: 26 周内零售实际笔数 >= retail_observed_min_qty 时, 用 retail_revenue/retail_qty.
        # 单笔异常 (5206753040071 €8.4677) 因门槛 >=3 被剥离.
        retail_price_observed: float | None = None
        if retail_qty_26w >= CONFIG.retail_observed_min_qty and retail_revenue_26w > 0:
            retail_price_observed = round(retail_revenue_26w / retail_qty_26w, 4)
        retail_price_estimate: float | None = None
        if sale is not None and sale > 0:
            retail_price_estimate = round(sale * CONFIG.retail_to_wholesale_ratio, 4)
        if retail_price_observed is not None:
            retail_price_eur = retail_price_observed
            retail_price_source = "observed"
        elif retail_price_estimate is not None:
            retail_price_eur = retail_price_estimate
            retail_price_source = "estimate"
        else:
            retail_price_eur = None
            retail_price_source = None

        # 库存可销售金额 + 库存成本 (drawer 财务快照用).
        # 用历史 retail/wholesale 比例预测这堆库存会怎么卖出.
        # 公式: stock × retail_share × retail_price + stock × (1-retail_share) × wholesale_price
        # 无历史 → retail_share=0, 全按批发口径 (保守).
        inventory_sale_value: float | None = None
        inventory_cost_value: float | None = None
        retail_share_26w: float = 0.0
        total_26w_qty = recent_qty + retail_qty_26w
        if total_26w_qty > 0:
            retail_share_26w = retail_qty_26w / total_26w_qty
        if qty_total is not None and qty_total > 0 and sale is not None:
            ws_price = sale  # 批发口径 (主档 sale_price 或 sale_net_avg)
            rt_price = retail_price_eur if retail_price_eur is not None else ws_price
            inventory_sale_value = round(
                qty_total * retail_share_26w * rt_price
                + qty_total * (1.0 - retail_share_26w) * ws_price,
                2,
            )
        if qty_total is not None and qty_total > 0 and cost is not None:
            inventory_cost_value = round(qty_total * cost, 2)

        # 💵 累计盈亏 (drawer "已回本/压货中/亏损" 状态用):
        # cost 统一走 EUR (master_stock_price_eur 或 last_purchase_unit_price).
        # 不用 inventory_events.unit_price (CN 货是 RMB, 混币种会乱).
        # 已售成本 = 全历史累计销量(批发+零售) × cost
        # 实现利润 = 全历史累计销售额 - 已售成本
        # 假设: cost 用当前估算反推历史投入 (FIFO 简化, 不追多批次进价变化).
        lifetime_sale_qty = sum(r.qty for r in sales)
        lifetime_sale_revenue = sum(
            r.qty * _net_unit(r.unit_price, r.discount_pct) for r in sales
        )
        first_event_at = None
        if sales:
            first_event_at = min(_parse_date(r.event_at) for r in sales).isoformat()
        # 累计投入: lifetime_purchase_qty × cost (EUR 口径, 与 realized_profit 一致).
        # cost 用当前 master/last_purchase 估算; 多批次进价变化不追 (FIFO 简化).
        lifetime_purchase_qty = lifetime_purchase_qty_by_bc.get(bc, 0)
        lifetime_invested_eur: float | None = None
        if cost is not None and lifetime_purchase_qty > 0:
            lifetime_invested_eur = round(lifetime_purchase_qty * cost, 2)

        # 实现利润 (2026-05-23 双口径):
        #   qty_total > 0: FIFO. 销售 - 已售件数 × cost (剩余库存按 cost 算回资产).
        #   qty_total == 0 / None: 净现金流. 销售 - 总投入 (库存空 = 全部成本已花掉,
        #                                  进销差额是报损/盘亏/已花未收, 全部扣掉).
        # 5828079293643 例: qty_total=0, FIFO 给 5107 (假设 3581 件还在某处), 净现金
        # 流给 3852 (假设丢失), 净现金流更接近真实.
        realized_profit_eur: float | None = None
        if cost is not None and lifetime_sale_qty > 0:
            if qty_total is not None and qty_total > 0:
                sold_cost = lifetime_sale_qty * cost
                realized_profit_eur = round(lifetime_sale_revenue - sold_cost, 2)
            elif lifetime_invested_eur is not None:
                realized_profit_eur = round(lifetime_sale_revenue - lifetime_invested_eur, 2)
            else:
                sold_cost = lifetime_sale_qty * cost
                realized_profit_eur = round(lifetime_sale_revenue - sold_cost, 2)
        # 净现金流 (始终算, 给 drawer 双口径并列): revenue - 总投入
        # 与 realized_profit 对照: 大库存高差异时 FIFO 给乐观值, cashflow 给保守值
        net_cashflow_eur: float | None = None
        if lifetime_invested_eur is not None:
            net_cashflow_eur = round(lifetime_sale_revenue - lifetime_invested_eur, 2)
        # 进销库存不平百分比: 高于 30% 时 drawer 标 ⚠️ FIFO 可能高估
        inventory_imbalance_pct: float | None = None
        if lifetime_purchase_qty > 0:
            qt = qty_total if qty_total is not None else 0
            diff = lifetime_purchase_qty - lifetime_sale_qty - qt
            inventory_imbalance_pct = round(abs(diff) / lifetime_purchase_qty * 100.0, 1)
        # ETL 窗口起点保守取 2021-06-01: 早于此的 first_event 标"数据不全"
        # (运营人员判断"已回本"时心里有数, 窗口外的销售/采购可能没纳入)
        is_history_truncated = (
            first_event_at is not None and first_event_at <= "2021-06-01"
        )
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
                "supplier_id": supplier_id,
                "qty_total": qty_total,
                "total_qty": total_qty,
                "weekly_velocity": round(weekly_velocity, 2),
                "weekly_revenue": round(weekly_revenue, 2),
                "n_active_weeks_26w": n_active_weeks,
                "weeks_of_cover": weeks_of_cover,
                "last_purchase_at": last_purchase_at,
                "last_purchase_days_ago": last_purchase_days_ago,
                "last_purchase_unit_price": (float(last_pp) if last_pp is not None else None),
                "master_stock_price_eur": (float(master_pp) if master_pp is not None else None),
                "master_sale_price_eur": (float(master_sp) if master_sp is not None else None),
                "sale_net_avg": (round(sale_net_avg, 4) if sale_net_avg is not None else None),
                "margin_pct": margin_pct,
                "margin_source": margin_source,
                "margin_price_source": margin_price_source,
                "retail_qty_26w": retail_qty_26w,
                "retail_revenue_26w": round(retail_revenue_26w, 2),
                "retail_price_eur": retail_price_eur,
                "retail_price_source": retail_price_source,
                "retail_price_observed": retail_price_observed,
                "retail_price_estimate": retail_price_estimate,
                "retail_share_26w": round(retail_share_26w, 3),
                "inventory_sale_value_eur": inventory_sale_value,
                "inventory_cost_value_eur": inventory_cost_value,
                "lifetime_sale_qty": int(lifetime_sale_qty),
                "lifetime_sale_revenue_eur": round(lifetime_sale_revenue, 2),
                "lifetime_purchase_qty": int(lifetime_purchase_qty),
                "lifetime_invested_eur": lifetime_invested_eur,
                "realized_profit_eur": realized_profit_eur,
                "net_cashflow_eur": net_cashflow_eur,
                "inventory_imbalance_pct": inventory_imbalance_pct,
                "first_event_at": first_event_at,
                "is_history_truncated": is_history_truncated,
                "lifespan_days": lifespan,
                "is_new_item": is_new_item,
                "trend_slope_pct_per_week": (round(trend, 2) if trend is not None else None),
                "weekly_qty_12w": weekly_qty_12w,
                "cn_qty": cn_qty,
                "fo_qty": fo_qty,
                **_restock_recommendation(
                    bc, qty_total, weekly_velocity,
                    forecast_by_bc, last_purchase_qty_by_bc,
                    middle_qty=mid_qty_by_bc.get(bc),
                ),
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
