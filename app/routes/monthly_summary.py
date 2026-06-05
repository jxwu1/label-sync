# routes_monthly_summary.py
import io

from flask import Blueprint, jsonify, send_file
from pydantic import BaseModel

from app.services import monthly_summary as monthly_summary_service
from app.utils.route_helpers import NonEmptyStr, parse_body

bp = Blueprint("monthly_summary", __name__, url_prefix="/monthly-summary")


class _SaveRecord(BaseModel):
    supplier_name: NonEmptyStr
    total_price: float
    tax: float
    invoice_date: NonEmptyStr
    month: NonEmptyStr
    special_tax: float = 0.0


@bp.post("/save")
def save():
    body, err = parse_body(_SaveRecord)
    if err:
        return err
    try:
        record = monthly_summary_service.save_record(
            supplier_name=body.supplier_name,
            total_price=body.total_price,
            tax=body.tax,
            special_tax=body.special_tax,
            invoice_date=body.invoice_date,
            month=body.month,
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


@bp.get("/xlsx/<month>")
def download_xlsx(month: str):
    try:
        xlsx_bytes = monthly_summary_service.build_xlsx(month)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"生成 Excel 失败：{exc}"}), 500
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"月度采购总结_{month}.xlsx",
    )
