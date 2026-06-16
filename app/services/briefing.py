"""最新批次简报 (老板 backlog #3) 聚合编排。

只读聚合现有物化表/服务, 不建表不加 cron。每个 card/action 独立降级。
口径见 docs/superpowers/specs/2026-06-09-morning-briefing-design.md。
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from typing import Any

# 与补货页 KPI 同阈值 (restock.js renderKpi: 紧急>=70 / 关注40-69)。
# review round3: p50>0 全集在生产 ~1 万 SKU, 对老板是噪音 → 简报只看 关注+紧急。
URGENT_URGENCY_SCORE = 70
WATCH_URGENCY_SCORE = 40
SALES_MIN_COVER_SKUS = 5
ACTION_LIST_LIMIT = 5
# 压货判定的两套词表 (review #2): auto_category 域 = categorizer.CATEGORIES
# (new/seasonal/declining/stable/unclassified, 没有 'dying'); manual_category 域 =
# routes/analytics._VALID_MANUAL_CATEGORIES 的中文标签。两边分别匹配, 互不遮蔽。
OVERSTOCK_MANUAL_CATEGORIES = ("滞销",)
OVERSTOCK_AUTO_CATEGORIES = ("declining",)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_data_week(
    latest_event_date: date | None,
    as_of: date,
    prior_complete_event_date: date | None = None,
) -> tuple[date | None, bool]:
    """本批次数据周 = **有数据的**最新完整 ISO 周的周一。

    完整周定义 (review #3): 该周已整周过去 — week_monday + 7 天 <= as_of。
    旧判定 (week_monday + 6 <= latest_event_date) 要求周日当天有销售才算完整;
    希腊零售周日歇业, 最新事件常年落在周六 → 已完整的周被误判不完整, 简报永久晚一周。
    - 最新事件所在周已整周过去 → 用它 (该周确有 latest 事件)。
    - 最新事件在尚未过完的周 → 用 `prior_complete_event_date` (= 该周一之前的最近
      一条事件) 所在周。该周整周在 as_of 之前, 必然完整且必然有数据 (就是这条事件)。
      调用方需传入这条事件日期; 没有 (库里没有更早事件) → (None, False)。
    - 无事件 → (None, False)。

    不靠 earliest/latest 推断「上一周是否有数据」: 上一完整周可能恰好零销而更早有数据,
    直接定位「当前周之前最近一条事件」才能落到真正有数据的最新完整周。
    """
    if latest_event_date is None:
        return None, False
    candidate = _monday(latest_event_date)
    if candidate + timedelta(days=7) <= as_of:
        return candidate, True
    # 最新事件所在周尚未过完 → 落到「该周之前最近一条事件」所在周 (必有数据且完整)。
    if prior_complete_event_date is None:
        return None, False
    return _monday(prior_complete_event_date), True


def _forecast_covered_barcodes(session) -> list[str]:
    """有 forecast 且 sku_type ∈ retail_dominant/mixed 的 barcode 集合。"""
    from sqlalchemy import select

    from app.models import ForecastOutput

    rows = (
        session.execute(
            select(ForecastOutput.product_barcode).where(
                ForecastOutput.sku_type.in_(("retail_dominant", "mixed"))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _forecast_mu_sum(session) -> float:
    """下期系统预期总量 = Σmu(均值, 可加)。

    不用 Σp50: 多数零售 SKU 间歇销售, 周销中位数=0 → Σp50 几乎只剩稳定款, 严重
    低估总需求 (实测 Σp50≈2.6k vs Σmu≈17.5k≈实际周销量)。均值 mu = E[需求] 才可加。
    """
    from sqlalchemy import func, select

    from app.models import ForecastOutput

    total = session.execute(
        select(func.coalesce(func.sum(ForecastOutput.mu), 0.0)).where(
            ForecastOutput.sku_type.in_(("retail_dominant", "mixed"))
        )
    ).scalar()
    return float(total or 0.0)


def _latest_backtest_bias(session) -> float | None:
    """生产模型最新 backtest run 的平均 bias(=mean(pred-actual)); 无数据返回 None。

    复用 forecast_eval 的生产 run 选取 (EmpiricalQuantile / base_demand), 与
    预测效果看板同口径; 不取「全模型最大 run_id」, 避免误把某个 baseline 比较 run
    的 bias 当成生产模型校准。
    """
    from sqlalchemy import func, select

    from app.models import BacktestResult
    from app.services.forecast_eval import _PROD_MODEL, _PROD_VIEW, _latest_run

    prod = _latest_run(session, _PROD_MODEL, _PROD_VIEW)
    if prod is None:
        return None
    avg = session.execute(
        select(func.avg(BacktestResult.bias)).where(BacktestResult.run_id == prod.id)
    ).scalar()
    return float(avg) if avg is not None else None


def _base_demand_views_bulk(barcodes, end_date, weeks, session):
    """薄包装, 便于测试 monkeypatch。批量版避免逐 SKU N+1 (review #1)。"""
    from app.utils.forecast_data import base_demand_views_bulk

    return base_demand_views_bulk(barcodes, end_date, weeks, session)


def compute_sales_health(session, data_week, data_week_complete) -> dict[str, Any]:
    if data_week is None or not data_week_complete:
        return {
            "ok": True,
            "status": "week_incomplete",
            "delta_pct": None,
            "current_qty": None,
            "previous_qty": None,
            "forecast_next_total": None,
            "model_bias_units": None,
            "covered_skus": 0,
        }

    prev_week = data_week - timedelta(days=7)
    barcodes = _forecast_covered_barcodes(session)
    cur_sum = 0
    prev_sum = 0
    covered = 0
    views = _base_demand_views_bulk(barcodes, data_week, 2, session)
    for bd in views.values():
        series = bd.get("series") or {}
        if data_week in series:
            covered += 1
            cur_sum += int(series.get(data_week, 0))
            prev_sum += int(series.get(prev_week, 0))

    forecast_next = _forecast_mu_sum(session)
    bias = _latest_backtest_bias(session)
    # bias 是 mean(pred-actual) 的绝对件数/周 (review #4), 不是分数, 不能 x100 当百分比
    model_bias_units = round(bias, 1) if bias is not None else None

    if covered < SALES_MIN_COVER_SKUS:
        return {
            "ok": True,
            "status": "coverage_insufficient",
            "delta_pct": None,
            "current_qty": cur_sum,
            "previous_qty": None,
            "forecast_next_total": forecast_next,
            "model_bias_units": model_bias_units,
            "covered_skus": covered,
        }

    if prev_sum <= 0:
        return {
            "ok": True,
            "status": "no_previous_week",
            "delta_pct": None,
            "current_qty": cur_sum,
            "previous_qty": prev_sum,
            "forecast_next_total": forecast_next,
            "model_bias_units": model_bias_units,
            "covered_skus": covered,
        }

    delta_pct = round((cur_sum - prev_sum) / prev_sum * 100.0, 1)
    return {
        "ok": True,
        "status": "ok",
        "delta_pct": delta_pct,
        "current_qty": cur_sum,
        "previous_qty": prev_sum,
        "forecast_next_total": forecast_next,
        "model_bias_units": model_bias_units,
        "covered_skus": covered,
    }


def _suppressed_barcodes(session) -> set[str]:
    from app.services.restock_decisions import list_suppressed

    return set(list_suppressed(session).keys())


def _restock_candidates(session, rows) -> list[dict[str, Any]]:
    """与补货页 KPI 池同口径 (review #7, restock.js KPI pool):
    p50>0 且非真停用/非新品/未被 skip 抑制, 且 urgency_score >= 关注线(40)。
    否则简报数字和「查看全部→」落地页对不上, 且 p50>0 全集是上万 SKU 的噪音。
    (「已下单」标记是补货页 localStorage 客户端态, 服务端无从对齐, 不在此剔。)"""
    suppressed = _suppressed_barcodes(session)
    return [
        r
        for r in rows
        if (r.get("restock_qty_p50") or 0) > 0
        and (r.get("urgency_score") or 0) >= WATCH_URGENCY_SCORE
        and not r.get("is_truly_discontinued")
        and not r.get("is_new_item")
        and r["barcode"] not in suppressed
    ]


def compute_restock_risk(session, rows) -> dict[str, Any]:
    cands = _restock_candidates(session, rows)
    urgent = sum(1 for r in cands if (r.get("urgency_score") or 0) >= URGENT_URGENCY_SCORE)
    return {"ok": True, "total": len(cands), "urgent": urgent}


def _cover_sort_key(r) -> float:
    c = r.get("weeks_of_cover")
    return c if c is not None else float("inf")


def build_restock_actions(session, rows) -> dict[str, Any]:
    cands = _restock_candidates(session, rows)
    cands.sort(key=lambda r: (_cover_sort_key(r), -(r.get("restock_qty_p50") or 0)))
    items = [
        {
            "barcode": r["barcode"],
            "model": r.get("model"),
            "qty_total": r.get("qty_total"),
            "weekly_velocity": r.get("weekly_velocity"),
            "restock_qty_p50": r.get("restock_qty_p50"),
            "weeks_of_cover": r.get("weeks_of_cover"),
        }
        for r in cands[:ACTION_LIST_LIMIT]
    ]
    return {"ok": True, "items": items, "total": len(cands)}


def compute_stockout_impact(rows) -> dict[str, Any]:
    hits = [r for r in rows if (r.get("stockout_zero_weeks_last8") or 0) > 0]
    hits.sort(key=lambda r: r.get("stockout_zero_weeks_last8") or 0, reverse=True)
    samples = [
        {
            "barcode": r["barcode"],
            "model": r.get("model"),
            "zero_weeks": r.get("stockout_zero_weeks_last8"),
            "qty_total": r.get("qty_total"),
        }
        for r in hits[:ACTION_LIST_LIMIT]
    ]
    return {"ok": True, "total": len(hits), "samples": samples}


def _is_overstock(r) -> bool:
    return (
        r.get("manual_category") in OVERSTOCK_MANUAL_CATEGORIES
        or r.get("auto_category") in OVERSTOCK_AUTO_CATEGORIES
    )


def compute_overstock_risk(rows) -> dict[str, Any]:
    hits = [r for r in rows if _is_overstock(r) and (r.get("qty_total") or 0) > 0]
    stock_qty = sum(int(r.get("qty_total") or 0) for r in hits)
    costs = [
        r.get("inventory_cost_value_eur")
        for r in hits
        if r.get("inventory_cost_value_eur") is not None
    ]
    cost_available = len(costs) > 0
    # review #9: 成本覆盖稀疏时金额只是「有成本数据那部分」的和, 必须带 costed_skus
    # 口径给前端标注, 不能冒充全部压货的总值。
    overstock_value = round(sum(costs), 2) if cost_available else None
    hits.sort(key=lambda r: int(r.get("qty_total") or 0), reverse=True)
    samples = [
        {
            "barcode": r["barcode"],
            "model": r.get("model"),
            "qty_total": r.get("qty_total"),
            "cost_value_eur": r.get("inventory_cost_value_eur"),
        }
        for r in hits[:ACTION_LIST_LIMIT]
    ]
    return {
        "ok": True,
        "total": len(hits),
        "stock_qty": stock_qty,
        "cost_available": cost_available,
        "costed_skus": len(costs),
        "overstock_value_eur": overstock_value,
        "samples": samples,
    }


def _freshness() -> dict[str, Any]:
    from app.services.analytics.freshness import get_data_freshness

    return get_data_freshness()


def compute_data_health(rows) -> dict[str, Any]:
    f = _freshness()
    total = len(rows)
    with_cost = sum(1 for r in rows if r.get("inventory_cost_value_eur") is not None)
    coverage = round(with_cost * 100.0 / total, 1) if total else None
    return {
        "ok": True,
        "last_import_date": f.get("last_import_date"),
        "days_since": f.get("days_since"),
        "stale": f.get("stale"),
        "scrape_stale": f.get("scrape_stale"),
        "cost_coverage_pct": coverage,
    }


def _quality_report() -> dict[str, Any]:
    from app.services.data_quality import build_report

    return build_report()


def build_review_actions() -> dict[str, Any]:
    report = _quality_report()
    blocks = [
        {"kind": k, "count": v["count"], "samples": (v.get("samples") or [])[:2]}
        for k, v in report.items()
        if isinstance(v, dict) and "count" in v and (v.get("count") or 0) > 0
    ]
    blocks.sort(key=lambda b: b["count"], reverse=True)
    return {"ok": True, "items": blocks[:ACTION_LIST_LIMIT], "total": len(blocks)}


def _list_orders():
    from app.services.purchase import list_orders

    return list_orders(limit=500)


def _supplier_lead_days() -> dict[str, float]:
    from app.services.purchase import compute_supplier_lead_times

    return {r["supplier_id"]: r["median_days"] for r in compute_supplier_lead_times()}


def _latest_event_date() -> date | None:
    from sqlalchemy import func, select

    from app.models import InventoryEvent
    from app.repositories import stockpile_db
    from app.services.analytics._shared import _parse_date

    with stockpile_db._session() as session:
        val = session.execute(
            select(func.max(InventoryEvent.event_at)).where(InventoryEvent.event_type == "sale")
        ).scalar()
    return _parse_date(str(val)) if val else None


def _event_date_before(before: date) -> date | None:
    """`before` (周一) 之前最近一条销售事件的日期; 无则 None。

    用于定位「当前未完整周之前、有数据的最新完整周」。event_at 为 ISO 字符串,
    字符串比较对 ISO 日期/时间戳成立; `< before.isoformat()` 排除 before 当天及以后。
    """
    from sqlalchemy import func, select

    from app.models import InventoryEvent
    from app.repositories import stockpile_db
    from app.services.analytics._shared import _parse_date

    with stockpile_db._session() as session:
        val = session.execute(
            select(func.max(InventoryEvent.event_at)).where(
                InventoryEvent.event_type == "sale",
                InventoryEvent.event_at < before.isoformat(),
            )
        ).scalar()
    return _parse_date(str(val)) if val else None


def _load_rows() -> list[dict[str, Any]]:
    from app.services.analytics.summary import list_sku_summary

    return list_sku_summary()


def _safe(fn) -> dict[str, Any]:
    """运行一个 block 函数, 隔离**业务**信号错误为 {ok:false, error}。

    系统级错误 (DB 连接 / schema 缺列 / 表不存在 = SQLAlchemyError) **不**吞,
    上抛给路由层 → 真实 5xx, 不伪装成 200 (spec §6)。
    """
    from sqlalchemy.exc import SQLAlchemyError

    try:
        return fn()
    except SQLAlchemyError:
        raise  # 系统级 → 冒泡到路由返回 5xx
    except Exception as exc:  # noqa: BLE001 — 业务信号错误隔离
        return {"ok": False, "error": str(exc)}


def build_briefing(as_of: date, generated_at: str) -> dict[str, Any]:
    from app.repositories import stockpile_db

    rows = _load_rows()
    latest = _latest_event_date()
    # 仅当最新事件所在周尚未整周过去时, 才查「该周之前最近一条事件」定位有数据的完整周。
    prior = None
    if latest is not None:
        wk = _monday(latest)
        if wk + timedelta(days=7) > as_of:
            prior = _event_date_before(wk)
    data_week, complete = compute_data_week(latest, as_of, prior)

    with stockpile_db._session() as session:
        cards = {
            "sales_health": _safe(lambda: compute_sales_health(session, data_week, complete)),
            "restock_risk": _safe(lambda: compute_restock_risk(session, rows)),
            "stockout_impact": _safe(lambda: compute_stockout_impact(rows)),
            "overstock_risk": _safe(lambda: compute_overstock_risk(rows)),
            "data_health": _safe(lambda: compute_data_health(rows)),
        }
        actions = {
            "restock": _safe(lambda: build_restock_actions(session, rows)),
            "follow_up": _safe(lambda: build_follow_up_actions(as_of)),
            "review_anomalies": _safe(build_review_actions),
        }

    return {
        "ok": True,
        "generated_at": generated_at,
        "data_week": data_week.isoformat() if data_week else None,
        "data_week_complete": complete,
        "cards": cards,
        "actions": actions,
    }


# ── 缓存层 (拆分: 重核心按数据版本缓存 + 轻叠加日期敏感现算) ──────────────────
# build_briefing 每次重算 8 块 ~12s, 其中 sales_health 8s + load_rows 1.5s + review 1s
# 只随「新数据导入 / 数据周」变, 导入间不变 → 缓存为「重核心」, key=(data_week, MAX(event.id))。
# follow_up(逾期天数) 和 data_health(距今天数) 随 as_of 逐日变但便宜 → 每次现算保新鲜
# (imported_at 索引后 freshness 亚毫秒)。效果: 跨天首载只算轻叠加 ~0.2s, 重核心命中;
# 仅新导入(event.id 变)或数据周变才重算重核心(~10s, 约每周一次)。日期敏感字段零陈旧。
# 单操作员无并发 → 锁仅防偶发竞态。build_briefing 本体保持纯全量 (测试/直调用)。
_CORE_TTL = 6 * 3600  # 6h 兜底 (主失效 = 数据版本 + 数据周)
_cache_lock = threading.Lock()
_core_cache: dict[str, Any] = {"key": None, "core": None, "ts": 0.0}


def _now() -> float:
    return time.monotonic()


def _data_version() -> tuple[int | None, str | None]:
    """数据版本 = (MAX(InventoryEvent.id), MAX(ForecastOutput.computed_at))。

    重核心依赖 events(sales_health/review) + forecast(sales_health 的覆盖/预期)。
    两者各有索引(id PK / idx_forecast_output_computed_at), 微秒级。新导入→event.id 变;
    手动重算 forecast(无新 event)→computed_at 变 → 都正确失效缓存(否则 sales_health 陈旧)。
    """
    from sqlalchemy import func, select

    from app.models import ForecastOutput, InventoryEvent
    from app.repositories import stockpile_db

    with stockpile_db._session() as session:
        ev = session.execute(select(func.max(InventoryEvent.id))).scalar()
        fc = session.execute(select(func.max(ForecastOutput.computed_at))).scalar()
    return (ev, fc)


def _resolve_data_week(as_of: date) -> tuple[date | None, bool]:
    """便宜地定位数据周 (latest/prior 事件查询走索引)。缓存 key 与核心都用它。"""
    latest = _latest_event_date()
    prior = None
    if latest is not None:
        wk = _monday(latest)
        if wk + timedelta(days=7) > as_of:
            prior = _event_date_before(wk)
    return compute_data_week(latest, as_of, prior)


def _compute_core(data_week: date | None, complete: bool) -> dict[str, Any]:
    """重核心: 只随数据版本/数据周变的块 (sales_health / sku_summary 卡片 / review)。"""
    from app.repositories import stockpile_db

    rows = _load_rows()
    with stockpile_db._session() as session:
        return {
            "rows": rows,
            "cards": {
                "sales_health": _safe(lambda: compute_sales_health(session, data_week, complete)),
                "restock_risk": _safe(lambda: compute_restock_risk(session, rows)),
                "stockout_impact": _safe(lambda: compute_stockout_impact(rows)),
                "overstock_risk": _safe(lambda: compute_overstock_risk(rows)),
            },
            "restock_action": _safe(lambda: build_restock_actions(session, rows)),
            "review_action": _safe(build_review_actions),
        }


def reset_briefing_cache() -> None:
    """清空缓存 (测试 / 导入后显式失效用)。"""
    with _cache_lock:
        _core_cache["key"] = None
        _core_cache["core"] = None
        _core_cache["ts"] = 0.0


def build_briefing_cached(
    as_of: date, generated_at: str, *, ttl: int = _CORE_TTL
) -> dict[str, Any]:
    """路由用。重核心按 (data_week, 数据版本) 缓存; follow_up/data_health 每次现算保新鲜。"""
    data_week, complete = _resolve_data_week(as_of)
    key = (data_week.isoformat() if data_week else None, complete, _data_version())
    with _cache_lock:
        hit = (
            _core_cache["core"] is not None
            and _core_cache["key"] == key
            and (_now() - _core_cache["ts"]) < ttl
        )
        core = _core_cache["core"] if hit else None
    if core is None:
        core = _compute_core(data_week, complete)
        with _cache_lock:
            _core_cache["key"] = key
            _core_cache["core"] = core
            _core_cache["ts"] = _now()

    # 轻叠加: 日期敏感且便宜, 每次现算保新鲜 (不进缓存)。
    rows = core["rows"]
    data_health = _safe(lambda: compute_data_health(rows))
    follow_up = _safe(lambda: build_follow_up_actions(as_of))
    return {
        "ok": True,
        "generated_at": generated_at,
        "data_week": data_week.isoformat() if data_week else None,
        "data_week_complete": complete,
        "cards": {**core["cards"], "data_health": data_health},
        "actions": {
            "restock": core["restock_action"],
            "follow_up": follow_up,
            "review_anomalies": core["review_action"],
        },
    }


def prewarm_briefing() -> None:
    """同步预热重核心 (导入/部署后调, 让用户首载命中)。错误吞掉, 不拖垮调用方。"""
    from datetime import datetime

    from app.services.analytics._shared import _today

    try:
        build_briefing_cached(_today(), datetime.now().isoformat(timespec="seconds"))
    except Exception:  # noqa: BLE001 — 预热失败不影响导入/启动主流程
        import logging

        logging.exception("briefing prewarm 失败")


def prewarm_briefing_async() -> None:
    """后台线程预热 (导入端点用, 不阻塞响应)。"""
    threading.Thread(target=prewarm_briefing, daemon=True, name="briefing-prewarm").start()


def build_follow_up_actions(as_of: date) -> dict[str, Any]:
    from datetime import date as date_cls

    orders = [o for o in _list_orders() if o.get("status") == "placed"]
    if not orders:
        return {"ok": True, "status": "empty", "items": [], "total": 0}

    lead = _supplier_lead_days()
    enriched = []
    for o in orders:
        overdue = None
        try:
            od = date_cls.fromisoformat(o["order_date"])
        except (ValueError, TypeError, KeyError):
            od = None
        md = lead.get(o.get("supplier_id"))
        if od is not None and md is not None:
            overdue = (as_of - (od + timedelta(days=int(md)))).days
        # review #8: 未到期(负数)不能渲染成「逾期 -13 天」, 前端按 state 分支
        if overdue is None:
            state = "unknown"
        elif overdue > 0:
            state = "overdue"
        else:
            state = "not_due"
        enriched.append(
            {
                "id": o["id"],
                "supplier_name": o.get("supplier_name"),
                "supplier_id": o.get("supplier_id"),
                "order_date": o.get("order_date"),
                "total_qty": o.get("total_qty"),
                "overdue_days": overdue,
                "overdue_state": state,
                "_od": od or date_cls.max,
            }
        )
    enriched.sort(key=lambda e: (e["overdue_days"] is None, -(e["overdue_days"] or 0), e["_od"]))
    for e in enriched:
        e.pop("_od", None)
    return {
        "ok": True,
        "status": "ok",
        "items": enriched[:ACTION_LIST_LIMIT],
        "total": len(enriched),
    }
