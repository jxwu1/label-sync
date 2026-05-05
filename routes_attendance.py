"""考勤 HTTP 路由。"""

import io
from typing import Literal

from flask import Blueprint, jsonify, send_file
from pydantic import BaseModel

import attendance_report_service
import attendance_service
from route_helpers import NonEmptyStr, OptionalStr, parse_body

bp = Blueprint("attendance", __name__, url_prefix="/attendance")


class _EmployeeCreate(BaseModel):
    name: NonEmptyStr


class _HolidayCreate(BaseModel):
    date: NonEmptyStr


class _SpecialDayUpsert(BaseModel):
    date: NonEmptyStr
    start: NonEmptyStr
    end: NonEmptyStr


class _DayUpsert(BaseModel):
    start: NonEmptyStr
    end: NonEmptyStr


class _LeaveUpsert(BaseModel):
    type: Literal["full", "range", "left"]
    start: OptionalStr = ""
    end: OptionalStr = ""


class _LeaveRangeUpsert(BaseModel):
    """区间请假：from_date / to_date / type / 时段。自动跳过周日。"""

    from_date: NonEmptyStr
    to_date: NonEmptyStr
    type: Literal["full", "range", "left"]
    start: OptionalStr = ""
    end: OptionalStr = ""


@bp.get("/employees")
def list_employees():
    return jsonify({"ok": True, "employees": attendance_service.list_employees()})


@bp.post("/employees")
def create_employee():
    body, err = parse_body(_EmployeeCreate)
    if err:
        return err
    emp = attendance_service.create_employee(body.name)
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
    body, err = parse_body(_HolidayCreate)
    if err:
        return err
    attendance_service.add_holiday(body.date)
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
    body, err = parse_body(_SpecialDayUpsert)
    if err:
        return err
    try:
        attendance_service.set_special_day(body.date, body.start, body.end)
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
    body, err = parse_body(_DayUpsert)
    if err:
        return err
    try:
        attendance_service.day_fraction(body.start, body.end)  # 校验
        attendance_service.set_day(employee_id, date, {"start": body.start, "end": body.end})
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
    body, err = parse_body(_LeaveUpsert)
    if err:
        return err
    try:
        attendance_service.set_leave(employee_id, date, body.type, start=body.start, end=body.end)
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    summary = attendance_service.compute_summary(employee_id, date[:7])
    return jsonify({"ok": True, **summary})


@bp.delete("/leave/<employee_id>/<date>")
def clear_leave(employee_id: str, date: str):
    attendance_service.clear_leave(employee_id, date)
    summary = attendance_service.compute_summary(employee_id, date[:7])
    return jsonify({"ok": True, **summary})


@bp.post("/leave-range/<employee_id>")
def set_leave_range(employee_id: str):
    """区间请假：from_date 到 to_date 的每天写一条 leave，自动跳过周日。"""
    body, err = parse_body(_LeaveRangeUpsert)
    if err:
        return err
    try:
        result = attendance_service.set_leave_range(
            employee_id,
            body.from_date,
            body.to_date,
            body.type,
            start=body.start,
            end=body.end,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    # 区间可能跨月，返回 from 月份的 summary 即可（前端拿到刷新当前月就行）
    summary = attendance_service.compute_summary(employee_id, body.from_date[:7])
    return jsonify({"ok": True, **result, **summary})


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
