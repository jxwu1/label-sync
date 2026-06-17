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
