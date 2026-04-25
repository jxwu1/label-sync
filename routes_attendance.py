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


@bp.get("/holidays")
def list_holidays():
    return jsonify({"ok": True, "holidays": attendance_service.list_holidays()})


@bp.post("/holidays")
def add_holiday():
    data = request.get_json(silent=True) or {}
    date = (data.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "msg": "缺少 date"}), 400
    attendance_service.add_holiday(date)
    return jsonify({"ok": True, "holidays": attendance_service.list_holidays()})


@bp.delete("/holidays/<date>")
def remove_holiday(date: str):
    attendance_service.remove_holiday(date)
    return jsonify({"ok": True, "holidays": attendance_service.list_holidays()})


@bp.get("/special-days")
def list_special_days():
    return jsonify({"ok": True, "special_days": attendance_service.list_special_days()})


@bp.post("/special-days")
def set_special_day():
    data = request.get_json(silent=True) or {}
    date = (data.get("date") or "").strip()
    start = (data.get("start") or "").strip()
    end = (data.get("end") or "").strip()
    if not date or not start or not end:
        return jsonify({"ok": False, "msg": "缺少 date / start / end"}), 400
    try:
        attendance_service.set_special_day(date, start, end)
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    return jsonify({"ok": True, "special_days": attendance_service.list_special_days()})


@bp.delete("/special-days/<date>")
def remove_special_day(date: str):
    attendance_service.remove_special_day(date)
    return jsonify({"ok": True, "special_days": attendance_service.list_special_days()})


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


@bp.get("/leaves/<month>")
def list_leaves(month: str):
    return jsonify({"ok": True, "leaves": attendance_service.list_leaves(month)})


@bp.post("/leave/<employee_id>/<date>")
def set_leave(employee_id: str, date: str):
    data = request.get_json(silent=True) or {}
    leave_type = (data.get("type") or "").strip()
    start = (data.get("start") or "").strip()
    end = (data.get("end") or "").strip()
    if leave_type not in ("full", "range", "left"):
        return jsonify({"ok": False, "msg": "type 必须为 full / range / left"}), 400
    try:
        attendance_service.set_leave(employee_id, date, leave_type, start=start, end=end)
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    summary = attendance_service.compute_summary(employee_id, date[:7])
    return jsonify({"ok": True, **summary})


@bp.delete("/leave/<employee_id>/<date>")
def clear_leave(employee_id: str, date: str):
    attendance_service.clear_leave(employee_id, date)
    summary = attendance_service.compute_summary(employee_id, date[:7])
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


@bp.get("/payroll-pdf/<month>")
def download_payroll_pdf(month: str):
    try:
        data = attendance_report_service.build_payroll_pdf(month)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"生成工资单 PDF 失败：{exc}"}), 500
    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"月度工资单_{month}.pdf",
    )
