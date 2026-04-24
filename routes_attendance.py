"""考勤 HTTP 路由。"""
import io

from flask import Blueprint, jsonify, request, send_file

import attendance_service
import attendance_report_service

bp = Blueprint("attendance", __name__, url_prefix="/attendance")


@bp.get("/employees")
def list_employees():
    return jsonify({"ok": True, "employees": attendance_service.list_employees()})


@bp.post("/employees")
def create_employee():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "姓名不能为空"}), 400
    emp = attendance_service.create_employee(name)
    return jsonify({"ok": True, "employee": emp})


@bp.delete("/employees/<employee_id>")
def delete_employee(employee_id: str):
    attendance_service.delete_employee(employee_id)
    return jsonify({"ok": True})


@bp.get("/month/<employee_id>/<month>")
def month_summary(employee_id: str, month: str):
    try:
        summary = attendance_service.compute_summary(employee_id, month)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, **summary})


@bp.post("/day/<employee_id>/<date>")
def set_day(employee_id: str, date: str):
    data = request.get_json(silent=True) or {}
    start, end = data.get("start"), data.get("end")
    if not start or not end:
        return jsonify({"ok": False, "msg": "缺少 start / end"}), 400
    try:
        attendance_service.day_fraction(start, end)  # 校验
        attendance_service.set_day(employee_id, date, {"start": start, "end": end})
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"保存失败：{exc}"}), 500
    month = date[:7]
    summary = attendance_service.compute_summary(employee_id, month)
    return jsonify({"ok": True, **summary})


@bp.delete("/day/<employee_id>/<date>")
def clear_day(employee_id: str, date: str):
    attendance_service.clear_day(employee_id, date)
    month = date[:7]
    summary = attendance_service.compute_summary(employee_id, month)
    return jsonify({"ok": True, **summary})


@bp.get("/pdf/<month>")
def download_pdf(month: str):
    try:
        data = attendance_report_service.build_pdf(month)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"生成 PDF 失败：{exc}"}), 500
    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"月度考勤_{month}.pdf",
    )


@bp.get("/csv/<month>")
def download_csv(month: str):
    try:
        data = attendance_report_service.build_csv(month)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"生成 CSV 失败：{exc}"}), 500
    return send_file(
        io.BytesIO(data),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"月度考勤_{month}.csv",
    )
