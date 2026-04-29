from flask import Blueprint, jsonify, request

import recent_changes_service

bp = Blueprint("recent_changes", __name__, url_prefix="/recent_changes")


@bp.get("/imports")
def list_imports():
    try:
        result = recent_changes_service.list_recent_imports()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "imports": result})


@bp.get("/<int:batch_id>/summary")
def batch_summary(batch_id: int):
    try:
        result = recent_changes_service.get_batch_summary(batch_id)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "summary": result})


@bp.get("/<int:batch_id>/changes")
def batch_changes(batch_id: int):
    mode = request.args.get("mode", "collapsed")
    if mode not in ("collapsed", "raw"):
        return jsonify({"ok": False, "msg": f"非法 mode: {mode}"}), 400
    field = request.args.get("field") or None
    change_type = request.args.get("change_type") or None
    try:
        rows = recent_changes_service.get_batch_changes(
            batch_id, mode=mode,
            filter_field=field, filter_change_type=change_type,
        )
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "changes": rows})
