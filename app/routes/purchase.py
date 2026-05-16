import io
import json
from datetime import date

from flask import Blueprint, jsonify, request, send_file
from pydantic import BaseModel, Field

from app.services import purchase as purchase_service
from app.repositories import stockpile_db
from app.utils.route_helpers import parse_body

bp = Blueprint("purchase", __name__, url_prefix="/purchase")


class _ImportEntries(BaseModel):
    entries: list[dict] = Field(min_length=1)


@bp.post("/process")
def process():
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        if single:
            files = [single]
    if not files:
        return jsonify({"ok": False, "msg": "请上传供应商 Excel 文件"}), 400
    supplier = files[0]
    if not supplier or not supplier.filename:
        return jsonify({"ok": False, "msg": "请上传供应商 Excel 文件"}), 400
    try:
        rows = purchase_service.parse_purchase_excel(supplier.read())
        # 采购路径带 inactive：下架货在系统里有记录，不应被识别为"新条码"
        system_set = stockpile_db.query_all_barcodes_set(include_inactive=True)
        new_bcs = purchase_service.find_new_barcodes(rows, system_set)
        # 本次解析行里有哪些是「停用货号」（manual_grade=0），前端标 OFF
        zero_grade_global = stockpile_db.query_zero_grade_barcodes_set()
        parsed_inactive = sorted({r.barcode for r in rows} & zero_grade_global)
        suggested_supplier = purchase_service.lookup_dominant_supplier([r.barcode for r in rows])
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 500
    return jsonify(
        {
            "ok": True,
            "rows": [r.to_dict() for r in rows],
            "system_barcodes": list(system_set),
            "new_barcodes": new_bcs,
            "inactive_barcodes": parsed_inactive,
            "suggested_supplier": suggested_supplier,
        }
    )


@bp.post("/import-to-stockpile")
def import_to_stockpile():
    body, err = parse_body(_ImportEntries)
    if err:
        return err
    try:
        count = purchase_service.import_new_barcodes(body.entries)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"入库失败：{exc}"}), 500
    return jsonify({"ok": True, "count": count})


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
