"""SKU 汇总物化表 + 整表计算 (split-only 拆分自 analytics)。"""

from __future__ import annotations

import threading as _threading
from datetime import date
from typing import Any

from sqlalchemy import select

from app.config import CONFIG
from app.models import Customer, InventoryEvent, Stockpile
from app.repositories import stockpile_db
from app.services.analytics._shared import (
    _NEW_ITEM_LIFESPAN_DAYS,
    _TREND_WEEKS,
    _VELOCITY_WEEKS,
    _is_retail_customer,
    _net_unit,
    _parse_date,
    _today,
    _trend_slope_pct,
    _weekly_qty_array,
)
from app.services.analytics.restock_calc import (
    _attach_urgency_scores,
    _lookup_qty,
    _restock_recommendation,
    _snapshot_qty_lookup,
)
from app.services.sku_origin import classify_origin

# list_sku_summary 60s 内存缓存 (2026-05-23): 整表计算 ~2-3s, 货号历史 / 补货决策
# 每次开页都触发. 60s TTL 平衡新鲜度和延迟. tests setUp 显式 clear_cache 防泄漏.
# Lock 防 thundering herd: 冷启动多个 panel 并发命中, 不加锁会重复计算 N 次.

_LIST_CACHE: dict = {"key": None, "value": None, "ts": 0.0}
_LIST_TTL_SECONDS = 60.0
_LIST_LOCK = _threading.Lock()


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

    import app.services.analytics as _pkg
    from app.models import SkuSummary

    as_of = as_of or _today()
    items = _pkg._list_sku_summary_impl(as_of)
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
    if (
        _LIST_CACHE["key"] == cache_key
        and _LIST_CACHE["value"] is not None
        and now - _LIST_CACHE["ts"] < _LIST_TTL_SECONDS
    ):
        return _LIST_CACHE["value"]
    # 慢路径: 拿锁. 拿到后再 check 一次 (double-checked locking),
    # 因为可能在等锁期间另一线程已经填好缓存.
    with _LIST_LOCK:
        now = time.time()
        if (
            _LIST_CACHE["key"] == cache_key
            and _LIST_CACHE["value"] is not None
            and now - _LIST_CACHE["ts"] < _LIST_TTL_SECONDS
        ):
            return _LIST_CACHE["value"]
        # 表优先: 物化表有当日 as_of 的行就直接用 (避免整表重算 2.9M 事件);
        # 空表 / as_of≠物化日 → 回退实时计算.
        import app.services.analytics as _pkg

        result = _read_sku_summary_table(as_of or _today())
        if result is None:
            result = _pkg._list_sku_summary_impl(as_of)
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
                ForecastOutput.stockout_zero_weeks_last8,
            )
        ).all()
        _, qty_by_model = _snapshot_qty_lookup(session)

    by_bc: dict[str, list] = {}
    for r in sales_rows:
        by_bc.setdefault(r.product_barcode, []).append(r)

    forecast_by_bc: dict[str, tuple[float, float, str, int]] = {}
    for r in forecast_rows:
        forecast_by_bc[r.product_barcode] = (
            r.p50,
            r.p98,
            r.model_used,
            r.stockout_zero_weeks_last8,
        )

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
    for (
        bc,
        model,
        name_zh,
        auto_cat,
        manual_cat,
        grade,
        is_disc,
        sp_supplier_id,
        last_pp,
        master_pp,
        master_sp,
        _extra,
    ) in sp_rows:
        sales = by_bc.get(bc, [])
        # 批发/零售分流: document_no 以 'MB' 开头或 = '0' 算零售, 不进批发聚合.
        # 零售只做透明展示 (retail_qty_26w / retail_revenue_26w),
        # 不污染 weekly_velocity/sale_net_avg.
        # 5206753040071 case: 单笔零售 €8.4677 拉爆批发均价 → 这里干掉.
        wholesale_sales = [
            r for r in sales if not _is_retail_customer(r.customer_id, r.customer_name)
        ]
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
        last_purchase_days_ago = (as_of - _parse_date(lp[0])).days if lp else None
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
        # 优先用历史观测: 26 周内零售实际笔数 >= retail_observed_min_qty 时,
        # 用 retail_revenue/retail_qty.
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
        lifetime_sale_revenue = sum(r.qty * _net_unit(r.unit_price, r.discount_pct) for r in sales)
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
        is_history_truncated = first_event_at is not None and first_event_at <= "2021-06-01"
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
                    bc,
                    qty_total,
                    weekly_velocity,
                    forecast_by_bc,
                    last_purchase_qty_by_bc,
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
