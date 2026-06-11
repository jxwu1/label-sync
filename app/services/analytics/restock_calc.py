"""补货 / 预测快照 + 紧迫分计算 (split-only 拆分自 analytics)。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import StockpileInventorySnapshot
from app.repositories import stockpile_db
from app.services.analytics._shared import (
    _URGENCY_COVER_TARGET_WEEKS,
    _URGENCY_RECENCY_FULL_DAYS,
    _today,
)


def compute_restock_snapshot(barcode: str) -> dict[str, Any] | None:
    """单 SKU 补货决策快照 (2026-05-23): 给货号历史复用补货 drawer 的指标.

    实现: 调 list_sku_summary 整表算一遍 (含 by-origin pctile), 再 filter 出
    目标 barcode. 是否在批量列表里(active + 非真停用) 都能拉到; 否则返 None.

    性能: 优先按 PK 读物化表单行 (~1ms); 表空/过期才回退 list_sku_summary
    (其本身再回退实时计算 + filter). 货号历史页高频开页不再触发整表重算.
    """
    from app.services.analytics.summary import _read_sku_summary_row, list_sku_summary

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
            "quarter_mu": round(float(row.mu) * 13, 0),  # 均值可线性相加，保留
            # RL-1: 季度 p98 用 bootstrap 列；旧行未刷则回退线性值（过渡期）
            "quarter_p98": (
                round(float(row.p98_13w), 0)
                if row.p98_13w is not None
                else round(float(row.p98) * 13, 0)
            ),
            "horizon_weeks": row.horizon_weeks,
            "p50_h": round(float(row.p50_h), 2) if row.p50_h is not None else None,
            "p98_h": round(float(row.p98_h), 2) if row.p98_h is not None else None,
            "stockout_weeks_excluded": row.stockout_weeks_excluded,
            "computed_at": row.computed_at,
        }

    if session is not None:
        return _q(session)
    with stockpile_db._session() as s:
        return _q(s)


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
            None
            if breakdown["total"] is None
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
            "total": None,
            "velocity": None,
            "cover": None,
            "recency": None,
            "margin": None,
            "demand_validity": None,
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


_RESTOCK_TARGET_WEEKS = _URGENCY_COVER_TARGET_WEEKS  # 默认 8 周


def _round_up_to_pack(qty: int | None, pack: int | None) -> int | None:
    """向上凑整到 pack 的倍数。qty=0 或 pack 无效时原样返回。"""
    if qty is None or qty <= 0 or not pack or pack <= 1:
        return qty
    import math

    return math.ceil(qty / pack) * pack


_CHURN_MIN_FRACTION = 0.25  # 反震荡: 缺口 < 25% S 且不足一个中包 → 持有 (RL-8)
_SANITY_HISTORICAL_MULT = 3  # 合理性闸: 推荐 > 历史最大单次进货 × 3 → 标记 (RL-6)
_SANITY_PACK_MULT = 10


def _churn_gate(qty: int, s_level: int, stock: int, pack: int | None) -> int:
    """RL-8 反震荡触发阈值（ADR-0001 D6）。断货必触发；缺口不足阈值 → 持有(0)。"""
    if qty <= 0:
        return 0
    if stock <= 0 and s_level > 0:
        return qty
    threshold = max(pack or 1, _CHURN_MIN_FRACTION * s_level)
    return qty if qty >= threshold else 0


def _restock_recommendation(
    barcode: str,
    qty_total: int,
    weekly_velocity: float,
    forecast_by_bc: dict,
    last_purchase_qty_by_bc: dict,
    middle_qty: int | None = None,
    on_order: int = 0,
) -> dict:
    """推荐补货量 = max(0, S − IP)，S = horizon 分位数（ADR-0001 D2）.

    IP = 现库存(负取0) + 在途(RL-2)。fc 元组为 (p50_h, p98_h, model, szw8) ——
    forecast_output 的 horizon 列，已是 H 周总量，不得再乘周数（RL-1）。
    回退链: forecast → velocity(×8周口径) → last_purchase。
    结果向上凑整到中包倍数 (middle_qty)。"""
    import math

    target = _RESTOCK_TARGET_WEEKS  # 仅 velocity 回退路径使用
    last_pq = last_purchase_qty_by_bc.get(barcode)
    fc = forecast_by_bc.get(barcode)
    stock = max(0, qty_total or 0)
    ip = stock + max(0, on_order)

    if fc:
        p50_h, p98_h, model, _stockout_zw8 = fc
        s50, s98 = math.ceil(p50_h), math.ceil(p98_h)
        qty_p50 = _churn_gate(max(0, s50 - ip), s50, stock, middle_qty)
        qty_p98 = _churn_gate(max(0, s98 - ip), s98, stock, middle_qty)
        source = f"forecast:{model}"
    elif weekly_velocity > 0:
        qty_p50 = max(0, math.ceil(weekly_velocity * target) - ip)
        qty_p98 = max(0, math.ceil(weekly_velocity * target * 1.5) - ip)
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

    # RL-6 合理性闸: 只标记不截断（截断会掩盖上游 bug）
    sanity_flag = None
    if qty_p98 and last_pq:
        cap = max(
            last_pq * _SANITY_HISTORICAL_MULT,
            (middle_qty or 1) * _SANITY_PACK_MULT,
        )
        if qty_p98 > cap:
            sanity_flag = "exceeds_historical_max"

    return {
        "restock_qty_p50": qty_p50,
        "restock_qty_p98": qty_p98,
        "restock_source": source,
        "last_purchase_qty": last_pq,
        "forecast_p50": round(fc[0], 2) if fc else None,
        "forecast_p98": round(fc[1], 2) if fc else None,
        "stockout_zero_weeks_last8": fc[3] if fc else 0,
        "on_order": on_order,
        "sanity_flag": sanity_flag,
    }
