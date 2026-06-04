from flask import Blueprint, jsonify, request

from app.services import recent_changes as recent_changes_service

bp = Blueprint("recent_changes", __name__, url_prefix="/recent_changes")


@bp.get("/imports")
def list_imports():
    try:
        result = recent_changes_service.list_recent_imports()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "imports": result})


def _parse_batch_id(raw: str) -> int | None:
    """支持负数 batch_id（开放批次 = -1）。Flask 默认 <int:> converter 只匹配 \\d+。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@bp.get("/<batch_id>/summary")
def batch_summary(batch_id: str):
    bid = _parse_batch_id(batch_id)
    if bid is None:
        return jsonify({"ok": False, "msg": f"非法 batch_id: {batch_id}"}), 400
    try:
        result = recent_changes_service.get_batch_summary(bid)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "summary": result})


@bp.get("/<batch_id>/changes")
def batch_changes(batch_id: str):
    bid = _parse_batch_id(batch_id)
    if bid is None:
        return jsonify({"ok": False, "msg": f"非法 batch_id: {batch_id}"}), 400
    mode = request.args.get("mode", "collapsed")
    if mode not in ("collapsed", "raw"):
        return jsonify({"ok": False, "msg": f"非法 mode: {mode}"}), 400
    field = request.args.get("field") or None
    change_type = request.args.get("change_type") or None
    try:
        rows = recent_changes_service.get_batch_changes(
            bid,
            mode=mode,
            filter_field=field,
            filter_change_type=change_type,
        )
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "changes": rows})
