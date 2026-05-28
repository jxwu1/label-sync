"""考勤 HTTP 路由。"""

import io
from datetime import date as date_cls
from typing import Literal

from flask import Blueprint, jsonify, request, send_file
from pydantic import BaseModel, field_validator

from app.services import attendance as attendance_service
from app.services import attendance_import as attendance_import_service
from app.services import attendance_report as attendance_report_service
from app.utils.route_helpers import NonEmptyStr, OptionalStr, parse_body

bp = Blueprint("attendance", __name__, url_prefix="/attendance")


class _EmployeeCreate(BaseModel):
    name: NonEmptyStr
    start_date: OptionalStr = ""

    @field_validator("start_date")
    @classmethod
    def _check_iso_date(cls, v: str) -> str:
        if not v:
            return v
        try:
            date_cls.fromisoformat(v)
        except ValueError as exc:
            raise ValueError("必须是 YYYY-MM-DD 格式") from exc
        return v


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


class _InactivePeriodUpsert(BaseModel):
    """不在职区间：长期休假回归 / 产假 / 停薪留职等，区间内每天不计考勤。"""

    from_date: NonEmptyStr
    to_date: NonEmptyStr
    reason: OptionalStr = ""


class _InactivePeriodDelete(BaseModel):
    """精确匹配删除一个不在职区间。"""

    from_date: NonEmptyStr
    to_date: NonEmptyStr


class _BindUpsert(BaseModel):
    account: NonEmptyStr
    employee_id: NonEmptyStr


class _IgnoreUpsert(BaseModel):
    account: NonEmptyStr


@bp.get("/employees")
def list_employees():
    return jsonify({"ok": True, "employees": attendance_service.list_employees()})


@bp.post("/employees")
def create_employee():
    body, err = parse_body(_EmployeeCreate)
    if err:
        return err
    emp = attendance_service.create_employee(body.name, start_date=body.start_date or None)
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


@bp.post("/holidays/import-year/<int:year>")
def import_holidays_year(year: int):
    """PR-FE-7d：批量导入指定年份法定节假日。"""
    try:
        result = attendance_service.import_holidays_for_year(year)
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    return jsonify({"ok": True, **result})


@bp.get("/fill-rates/<month>")
def fill_rates(month: str):
    """PR-FE-7d-2：返回每员工在指定月份的填写率，给员工 rail 用。

    口径：仅统计"用户需要填的工作日"，自动的周日 / 节假日 / pre_join 不计。
    - filled = total_workdays（已填：normal / special / leave）
    - total  = total_workdays + absent_days（应填：含未填的 absent）
    - rate = filled / total（0-1，total 为 0 时给 0）
    """
    employees = attendance_service.list_employees()
    try:
        summaries = attendance_service.compute_summaries_batch(employees, month)
    except Exception:
        summaries = {}
    out = []
    for emp in employees:
        summary = summaries.get(emp["id"], {"total_workdays": 0, "absent_days": 0, "detail": []})
        filled = summary.get("total_workdays", 0)
        absent = summary.get("absent_days", 0)
        # 把周日/节假日等"自动满"的天排出 — 但 total_workdays 已经含 sunday/holiday，
        # 需要再减回去；最简单：从 detail 里数 status in {normal, special, leave, absent}
        detail = summary.get("detail", [])
        action_total = sum(
            1
            for r in detail
            if r.get("status") in ("normal", "special", "special_absent", "leave", "absent")
        )
        action_filled = sum(
            1 for r in detail if r.get("status") in ("normal", "special", "special_absent", "leave")
        )
        rate = (action_filled / action_total) if action_total > 0 else 0.0
        out.append(
            {
                "id": emp["id"],
                "name": emp["name"],
                "filled": action_filled,
                "total": action_total,
                "rate": round(rate, 3),
                # 兼容字段（暂未使用，留作前端备选）
                "worked_days": filled,
                "absent_days": absent,
            }
        )
    return jsonify({"ok": True, "employees": out})


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


@bp.get("/inactive-periods/<employee_id>")
def list_inactive_periods(employee_id: str):
    return jsonify({"ok": True, "periods": attendance_service.list_inactive_periods(employee_id)})


@bp.post("/inactive-periods/<employee_id>")
def add_inactive_period(employee_id: str):
    body, err = parse_body(_InactivePeriodUpsert)
    if err:
        return err
    try:
        period = attendance_service.add_inactive_period(
            employee_id, body.from_date, body.to_date, body.reason
        )
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    return jsonify(
        {
            "ok": True,
            "period": period,
            "periods": attendance_service.list_inactive_periods(employee_id),
        }
    )


@bp.delete("/inactive-periods/<employee_id>")
def delete_inactive_period(employee_id: str):
    body, err = parse_body(_InactivePeriodDelete)
    if err:
        return err
    removed = attendance_service.remove_inactive_period(employee_id, body.from_date, body.to_date)
    if not removed:
        return jsonify({"ok": False, "msg": "未找到匹配的不在职区间"}), 404
    return jsonify({"ok": True, "periods": attendance_service.list_inactive_periods(employee_id)})


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


@bp.post("/import/preview")
def import_preview():
    f = request.files.get("file")
    if f is None:
        return jsonify({"ok": False, "msg": "缺少文件"}), 400
    try:
        parsed = attendance_import_service.parse_workbook(f.read(), f.filename or "")
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 400
    month = request.form.get("month") or parsed["detected_month"]
    if not month:
        return jsonify({"ok": False, "msg": "无法判定月份,请手动选择目标月"}), 400
    plan = attendance_import_service.build_plan(parsed["rows"], month)
    return jsonify({"ok": True, **plan})


@bp.post("/import/bind")
def import_bind():
    body, err = parse_body(_BindUpsert)
    if err:
        return err
    try:
        attendance_import_service.bind_account(body.account, body.employee_id)
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    return jsonify({"ok": True})


@bp.post("/import/ignore")
def import_ignore():
    body, err = parse_body(_IgnoreUpsert)
    if err:
        return err
    attendance_import_service.ignore_account(body.account)
    return jsonify({"ok": True})


@bp.post("/import/unignore")
def import_unignore():
    body, err = parse_body(_IgnoreUpsert)
    if err:
        return err
    attendance_import_service.unignore_account(body.account)
    return jsonify({"ok": True})


@bp.post("/import/apply")
def import_apply():
    f = request.files.get("file")
    if f is None:
        return jsonify({"ok": False, "msg": "缺少文件"}), 400
    try:
        parsed = attendance_import_service.parse_workbook(f.read(), f.filename or "")
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 400
    month = request.form.get("month") or parsed["detected_month"]
    if not month:
        return jsonify({"ok": False, "msg": "无法判定月份,请手动选择目标月"}), 400
    result = attendance_import_service.apply_plan(parsed["rows"], month)
    return jsonify({"ok": True, **result})
