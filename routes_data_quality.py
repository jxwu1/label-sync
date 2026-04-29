from flask import Blueprint, jsonify

import data_quality_service

bp = Blueprint("data_quality", __name__, url_prefix="/data_quality")


@bp.get("")
def report():
    try:
        result = data_quality_service.build_report()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"分析失败：{exc}"}), 500
    return jsonify({"ok": True, **result})
