# routes_monthly_summary.py
import io

from flask import Blueprint, jsonify, request, send_file

import monthly_summary_service

bp = Blueprint("monthly_summary", __name__, url_prefix="/monthly-summary")


@bp.post("/save")
def save():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": False, "msg": "缺少 JSON 数据"}), 400
    required = ("supplier_name", "total_price", "tax", "invoice_date", "month")
    missing = [k for k in required if not data.get(k) and data.get(k) != 0]
    if missing:
        return jsonify({"ok": False, "msg": f"缺少字段：{', '.join(missing)}"}), 400
    try:
        record = monthly_summary_service.save_record(
            supplier_name=data["supplier_name"],
            total_price=float(data["total_price"]),
            tax=float(data["tax"]),
            special_tax=float(data.get("special_tax") or 0),
            invoice_date=data["invoice_date"],
            month=data["month"],
        )
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"保存失败：{exc}"}), 500
    return jsonify({"ok": True, "record": record})


@bp.get("/months")
def list_months():
    months = monthly_summary_service.list_months()
    return jsonify({"ok": True, "months": months})


@bp.get("/records/<month>")
def get_records(month: str):
    records = monthly_summary_service.load_records(month)
    return jsonify({"ok": True, "records": records, "count": len(records)})


@bp.post("/delete/<month>/<int:index>")
def delete_record(month: str, index: int):
    try:
        removed = monthly_summary_service.delete_record(month, index)
    except IndexError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"删除失败：{exc}"}), 500
    return jsonify({"ok": True, "removed": removed})


@bp.get("/pdf/<month>")
def download_pdf(month: str):
    try:
        pdf_bytes = monthly_summary_service.build_pdf(month)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"生成 PDF 失败：{exc}"}), 500
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"月度采购总结_{month}.pdf",
    )
