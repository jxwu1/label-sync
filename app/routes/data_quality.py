import io
from datetime import datetime

from flask import Blueprint, jsonify, send_file

from app.services import data_quality as data_quality_service

bp = Blueprint("data_quality", __name__, url_prefix="/data_quality")


@bp.get("")
def report():
    try:
        result = data_quality_service.build_report()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"分析失败：{exc}"}), 500
    return jsonify({"ok": True, **result})


@bp.get("/whitespace_fix_template")
def whitespace_fix_template():
    """全量 whitespace 异常货号的「产品信息导入模板」CSV，浏览器直接下载。"""
    try:
        df = data_quality_service.build_whitespace_fix_dataframe()
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 500
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"生成失败：{exc}"}), 500

    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"数据质量-空白修复-{timestamp}.csv",
    )
