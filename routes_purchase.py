import io
import json
from datetime import date

from flask import Blueprint, jsonify, request, send_file

import purchase_service

bp = Blueprint("purchase", __name__, url_prefix="/purchase")


def _classify_files(files):
    stockpile, supplier = None, None
    for f in files:
        if not f or not f.filename:
            continue
        if f.filename.lower().startswith("stockpile"):
            stockpile = f
        else:
            supplier = f
    return supplier, stockpile


@bp.post("/process")
def process():
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        if single:
            files = [single]
    if len(files) < 2:
        return jsonify({"ok": False, "msg": "请同时上传供应商 Excel 和 stockpile CSV"}), 400
    supplier, stockpile = _classify_files(files)
    if not supplier or not stockpile:
        return jsonify({"ok": False, "msg": "缺少供应商 Excel 或 stockpile CSV"}), 400
    try:
        rows = purchase_service.parse_purchase_excel(supplier.read())
        system_set = purchase_service.parse_stockpile_csv(stockpile.read())
        new_bcs = purchase_service.find_new_barcodes(rows, system_set)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 500
    return jsonify({
        "ok": True,
        "rows": [r.to_dict() for r in rows],
        "system_barcodes": list(system_set),
        "new_barcodes": new_bcs,
    })


@bp.post("/export")
def export():
    f = request.files.get("file")
    if not f or f.filename == "":
        return jsonify({"ok": False, "msg": "请先上传 Excel 文件"}), 400
    rows_data = json.loads(request.form.get("rows", "[]"))
    new_entries = json.loads(request.form.get("new_entries", "[]"))
    try:
        xlsx_bytes = purchase_service.build_output_excel(f.read(), rows_data)
        template_csv = purchase_service.build_template_csv(new_entries) if new_entries else None
        date_str = date.today().strftime("%Y%m%d")
        zip_bytes = purchase_service.build_zip(xlsx_bytes, template_csv, date_str)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"导出失败：{exc}"}), 500
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"采购订单{date_str}.zip",
    )
