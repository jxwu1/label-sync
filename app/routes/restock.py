"""补货决策反馈路由 (P3 数据收集).

POST /restock/decisions       记录一条 (前端「标已下单」/「不进」触发)
POST /restock/decisions/batch 批量记录 (前端勾选多行后一键)
GET  /restock/decisions/recent?limit=200&decision=skipped
GET  /restock/decisions/stats?days=30
GET  /restock/decisions/stale  现算 14 天高分未处理的, 不入库
GET  /restock/decisions/suppressed  skip 抑制集 (14 天内 skipped 且无后续进货, 决策回流)
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.models import get_session
from app.schemas_api import RestockSuppressedList
from app.services import restock_decisions as svc
from app.services.analytics import list_sku_summary

bp = Blueprint("restock", __name__, url_prefix="/restock")


@bp.post("/decisions")
def post_decision():
    """记录单条. body: {barcode, decision, item, reason?}.

    decision = 'ordered' | 'overridden' | 'skipped'.
    'ordered' 时后端按 urgency_score 阈值自动改判 overridden, 前端不必区分.
    """
    body = request.get_json(silent=True) or {}
    barcode = body.get("barcode")
    decision = body.get("decision")
    item = body.get("item") or {}
    reason = body.get("reason")
    if not barcode or decision not in ("ordered", "overridden", "skipped"):
        return jsonify({"ok": False, "msg": "缺 barcode 或 decision 非法"}), 400
    if decision == "ordered":
        decision = svc.classify_ordered(item)
    with get_session() as s:
        row = svc.record_decision(s, barcode, decision, item, reason)
        s.flush()
        rid = row.id
    return jsonify({"ok": True, "id": rid, "decision": decision})


@bp.post("/decisions/batch")
def post_decisions_batch():
    """body: {decision, reason?, items: [{barcode, ...}]} — 一次记一批."""
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    items = body.get("items") or []
    reason = body.get("reason")
    if decision not in ("ordered", "overridden", "skipped"):
        return jsonify({"ok": False, "msg": "decision 非法"}), 400
    if not items:
        return jsonify({"ok": False, "msg": "items 空"}), 400
    n = 0
    overridden_n = 0
    with get_session() as s:
        for it in items:
            bc = it.get("barcode")
            if not bc:
                continue
            d = decision
            if d == "ordered":
                d = svc.classify_ordered(it)
                if d == "overridden":
                    overridden_n += 1
            svc.record_decision(s, bc, d, it, reason)
            n += 1
    return jsonify({"ok": True, "recorded": n, "overridden": overridden_n})


@bp.get("/decisions/recent")
def get_recent():
    limit = min(int(request.args.get("limit", 200)), 1000)
    decision = request.args.get("decision")
    with get_session() as s:
        rows = svc.list_recent(s, limit=limit, decision=decision)
    return jsonify({"ok": True, "items": rows})


@bp.get("/decisions/stats")
def get_stats():
    days = min(int(request.args.get("days", 30)), 365)
    with get_session() as s:
        stats = svc.aggregate_stats(s, days=days)
    return jsonify({"ok": True, **stats})


@bp.get("/decisions/stale")
def get_stale():
    """实时算: urgency>=70 且最近 14 天无 ordered/overridden 决策的 SKU."""
    items = list_sku_summary()
    with get_session() as s:
        stale = svc.list_stale_high_score(s, items)
    return jsonify({"ok": True, "count": len(stale), "items": stale[:200]})


@bp.get("/decisions/suppressed")
def get_suppressed():
    """skip 抑制集: 最近一条是 skipped、14 天内、无后续新进货的 barcode.

    天数走后端常量 SKIP_SUPPRESS_DAYS(业务规则, 不暴露 query).
    """
    with get_session() as s:
        items = svc.list_suppressed(s)
    return jsonify({"ok": True, "items": items})


api_bp = Blueprint("api_restock", __name__, url_prefix="/api/restock")


@api_bp.get("/suppressed")
def api_suppressed():
    with get_session() as s:
        items = svc.list_suppressed(s)
    payload = {"ok": True, "items": items}
    return jsonify(RestockSuppressedList.model_validate(payload).model_dump())
