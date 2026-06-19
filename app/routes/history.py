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
# HC-B6: urgency_breakdown 嵌套显式投影字段集（对齐 UrgencyBreakdown schema，extra="forbid"）
_URGENCY_BREAKDOWN_KEYS = ("cover", "recency", "velocity", "margin", "demand_validity")

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
    """HC-B6: 从 list_sku_summary 整行投影出 RestockSnapshot 字段子集。

    urgency_breakdown 嵌套字段也做显式投影，过滤 _attach_urgency_scores 写入的多余计算中间键。
    """
    out = {k: row.get(k) for k in _RESTOCK_PROJECTION_KEYS}
    bd = out.get("urgency_breakdown")
    out["urgency_breakdown"] = (
        {k: bd.get(k) for k in _URGENCY_BREAKDOWN_KEYS} if bd is not None else None
    )
    return out


_RC_VALID_MODES = ("collapsed", "raw")


@api_bp.get("/recent-changes/batches")
def recent_changes_batches():
    from app.schemas_api import RecentChangesBatchList
    from app.services import recent_changes as rc

    payload = {"ok": True, "batches": rc.list_recent_imports()}
    return jsonify(RecentChangesBatchList.model_validate(payload).model_dump())


def _project_change_row(r: dict, mode: str) -> dict:
    """service 内部 key（raw: old/new/created_at, collapsed: from/to/latest_at）
    → ChangeRow schema（from_value/to_value/at），过滤内部 key 泄漏。
    """
    if mode == "raw":
        return {
            "barcode": r["barcode"],
            "model": r["model"],
            "field": r["field"],
            "from_value": r["old_value"],
            "to_value": r["new_value"],
            "change_type": r["change_type"],
            "at": r["created_at"],
        }
    return {
        "barcode": r["barcode"],
        "model": r["model"],
        "field": r["field"],
        "from_value": r["from_value"],
        "to_value": r["to_value"],
        "change_type": r["change_type"],
        "at": r["latest_at"],
    }


@api_bp.get("/recent-changes/<batch_id>/changes")
def recent_changes_detail(batch_id: str):
    from app.schemas_api import RecentChangesDetail
    from app.services import recent_changes as rc

    try:
        bid = int(batch_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_batch_id"}), 400
    mode = request.args.get("mode", "collapsed")
    if mode not in _RC_VALID_MODES:
        return jsonify({"ok": False, "error": "bad_mode"}), 400
    field = request.args.get("field") or None
    change_type = request.args.get("change_type") or None

    detail = rc.get_batch_detail(bid, mode=mode, filter_field=field, filter_change_type=change_type)
    if detail is None:
        return jsonify({"ok": False, "error": "batch_not_found"}), 404
    payload = {
        "ok": True,
        "summary": detail["summary"],
        "changes": [_project_change_row(r, mode) for r in detail["changes"]],
        "total_count": detail["total_count"],
    }
    return jsonify(RecentChangesDetail.model_validate(payload).model_dump())


@api_bp.get("/<barcode>/timeline")
def timeline(barcode: str):
    from app.schemas_api import SkuTimelineResponse
    from app.services import analytics as analytics_service

    bc = barcode.strip()
    payload = {
        "ok": True,
        "timeline": analytics_service.compute_weekly_timeline(bc),
        "monthly_sales": analytics_service.compute_monthly_sales(bc),
    }
    return jsonify(SkuTimelineResponse.model_validate(payload).model_dump())


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
