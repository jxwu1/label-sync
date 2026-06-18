from flask import Blueprint, jsonify, request

from app.services import history as history_service

bp = Blueprint("history", __name__, url_prefix="/history")


@bp.get("")
def query():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "msg": "缺少查询参数"}), 400
    try:
        result = history_service.build_response(q)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"查询失败：{exc}"}), 500
    return jsonify({"ok": True, **result})


api_bp = Blueprint("api_history", __name__, url_prefix="/api/history")


@api_bp.get("")
def search():
    # HC-7：空 q 走 {ok,msg} 400，不进 schema
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "msg": "缺少查询参数"}), 400
    # 系统级异常不在此吞（对齐 /api/briefing/data）：让其冒泡到 Flask 通用 500。
    from app.schemas_api import HistorySearchData

    result = history_service.build_response(q)
    return jsonify(HistorySearchData.model_validate({"ok": True, **result}).model_dump())


# Phase 2b: restock 显式投影字段集（HC-B6, 逐字段对齐 summary.py 行）
_RESTOCK_PROJECTION_KEYS = (
    "master_sale_price_eur",
    "sale_net_avg",
    "retail_price_observed",
    "retail_price_estimate",
    "retail_qty_26w",
    "last_purchase_unit_price",
    "master_stock_price_eur",
    "margin_pct",
    "qty_total",
    "inventory_sale_value_eur",
    "inventory_cost_value_eur",
    "weeks_of_cover",
    "lifetime_invested_eur",
    "lifetime_purchase_qty",
    "lifetime_sale_revenue_eur",
    "lifetime_sale_qty",
    "realized_profit_eur",
    "net_cashflow_eur",
    "inventory_imbalance_pct",
    "weekly_velocity",
    "weekly_revenue",
    "n_active_weeks_26w",
    "last_purchase_days_ago",
    "urgency_score",
    "urgency_breakdown",
)


def _project_restock(row: dict) -> dict:
    """HC-B6: 从 list_sku_summary 整行投影出 RestockSnapshot 字段子集。"""
    return {k: row.get(k) for k in _RESTOCK_PROJECTION_KEYS}


@api_bp.get("/<barcode>/analytics/extras")
def analytics_extras(barcode: str):
    from app.schemas_api import SkuExtrasResponse
    from app.services import analytics as analytics_service
    from app.services.analytics._shared import _today
    from app.services.forecast_eval import forecast_is_stale

    bc = barcode.strip()
    rows = analytics_service.fetch_event_rows(bc)  # HC-B2: 取一次喂 extras/holding/heatmap
    extras = analytics_service.compute_sku_extras(bc, rows=rows)
    holding = analytics_service.compute_avg_holding_days(bc, rows=rows)
    heatmap = analytics_service.compute_monthly_heatmap(bc, rows=rows)
    fc = analytics_service.compute_forecast_snapshot(bc)
    restock_full = analytics_service.compute_restock_snapshot(bc)

    forecast_brief = None
    if fc is not None:
        forecast_brief = {
            "quarter_mu": fc["quarter_mu"],
            "quarter_p98": fc["quarter_p98"],
            "computed_at": fc["computed_at"],
            "is_stale": forecast_is_stale(fc["computed_at"], _today()),
            "stockout_weeks_excluded": fc["stockout_weeks_excluded"],
        }

    restock_brief = _project_restock(restock_full) if restock_full is not None else None

    payload = {
        "ok": True,
        "extras": extras,
        "holding": holding,
        "heatmap": heatmap,
        "forecast": forecast_brief,
        "restock": restock_brief,
    }
    return jsonify(SkuExtrasResponse.model_validate(payload).model_dump())


@api_bp.get("/<barcode>/analytics")
def analytics(barcode: str):
    from app.schemas_api import SkuAnalyticsData
    from app.services import analytics as analytics_service

    bc = barcode.strip()
    payload = {
        "ok": True,
        "sales": analytics_service.compute_sales_metrics(bc),
        "purchase": analytics_service.compute_purchase_metrics(bc),
        "customer_split": analytics_service.compute_customer_split(bc),
    }
    return jsonify(SkuAnalyticsData.model_validate(payload).model_dump())
