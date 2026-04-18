import io
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

import import_service
from config import CONFIG

bp = Blueprint("import", __name__, url_prefix="/import")


@bp.post("/recognize")
def recognize():
    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"ok": False, "msg": "请先上传图片"}), 400
    image_data = [(f.read(), f.content_type or "image/jpeg") for f in files]
    try:
        items = import_service.recognize_images(image_data, CONFIG.gemini_api_key)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"识别失败：{exc}"}), 500
    return jsonify({"ok": True, "items": [item.to_dict() for item in items]})


@bp.post("/export")
def export():
    data = request.get_json(silent=True) or {}
    rows = data.get("items", [])
    if any(
        row.get("barcode") is None or row.get("quantity") is None or row.get("total_price") is None
        for row in rows
    ):
        return jsonify({"ok": False, "msg": "存在未填写的红色单元格，请补全后再导出"}), 400
    items = [
        import_service.ImportItem(
            barcode=row["barcode"],
            quantity=int(row["quantity"]),
            total_price=float(row["total_price"]),
        )
        for row in rows
    ]
    xlsx_bytes = import_service.build_excel_bytes(items)
    filename = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
