"""考勤服务：员工 CRUD、月度 CRUD、summary 计算。"""

import json
from calendar import monthrange
from datetime import date as date_cls, datetime
from pathlib import Path

_ATTENDANCE_DIR = Path(__file__).resolve().parent / "attendance"
_EMPLOYEES_FILE = "employees.json"
_HOLIDAYS_FILE = "holidays.json"
_SPECIAL_DAYS_FILE = "special_days.json"
_METADATA_FILE = "metadata.json"


def _employees_path() -> Path:
    return _ATTENDANCE_DIR / _EMPLOYEES_FILE


def _metadata_path() -> Path:
    return _ATTENDANCE_DIR / _METADATA_FILE


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_employees() -> list[dict]:
    return _read_json(_employees_path(), [])


def _next_employee_id() -> str:
    metadata = _read_json(_metadata_path(), {"next_id_num": 0})
    next_num = metadata.get("next_id_num", 0) + 1
    metadata["next_id_num"] = next_num
    _write_json(_metadata_path(), metadata)
    return f"e{next_num:03d}"


def create_employee(name: str) -> dict:
    employees = list_employees()
    emp = {
        "id": _next_employee_id(),
        "name": name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    employees.append(emp)
    _write_json(_employees_path(), employees)
    return emp


def _holidays_path() -> Path:
    return _ATTENDANCE_DIR / _HOLIDAYS_FILE


def list_holidays() -> list[str]:
    return sorted(_read_json(_holidays_path(), []))


def add_holiday(date: str) -> None:
    holidays = set(list_holidays())
    holidays.add(date)
    _write_json(_holidays_path(), sorted(holidays))


def remove_holiday(date: str) -> None:
    holidays = [d for d in list_holidays() if d != date]
    _write_json(_holidays_path(), holidays)


def _special_days_path() -> Path:
    return _ATTENDANCE_DIR / _SPECIAL_DAYS_FILE


def list_special_days() -> dict:
    return _read_json(_special_days_path(), {})


def set_special_day(date: str, start: str, end: str) -> None:
    # 校验时段合法
    day_fraction(start, end, standard_hours=1.0)  # 仅触发 end>start 校验
    data = list_special_days()
    data[date] = {"start": start, "end": end}
    _write_json(_special_days_path(), dict(sorted(data.items())))


def remove_special_day(date: str) -> None:
    data = list_special_days()
    if date in data:
        del data[date]
        _write_json(_special_days_path(), data)


def delete_employee(employee_id: str) -> None:
    employees = [e for e in list_employees() if e["id"] != employee_id]
    _write_json(_employees_path(), employees)


STANDARD_HOURS = 10.5


def _parse_hm(hm: str) -> int:
    """HH:MM -> 分钟总数"""
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def day_fraction(start: str, end: str, standard_hours: float = STANDARD_HOURS) -> float:
    """计算工作日占比（纯函数）。

    Args:
        start: 上班时间，格式 "HH:MM"
        end: 下班时间，格式 "HH:MM"
        standard_hours: 这一天的标准工时（小时）；默认 10.5。特殊日可传入缩短值。

    Returns:
        [0.0, 1.0] 范围内的占比，超过标准工作时间封顶为 1.0

    Raises:
        ValueError: 若 end <= start 或 standard_hours <= 0
    """
    if standard_hours <= 0:
        raise ValueError(f"standard_hours 必须 > 0：{standard_hours}")
    start_min = _parse_hm(start)
    end_min = _parse_hm(end)
    if end_min <= start_min:
        raise ValueError(f"下班时间必须晚于上班时间：start={start} end={end}")
    hours = (end_min - start_min) / 60
    return min(hours / standard_hours, 1.0)


def _month_path(month: str) -> Path:
    return _ATTENDANCE_DIR / f"{month}.json"


def _leaves_path(month: str) -> Path:
    return _ATTENDANCE_DIR / f"{month}.leaves.json"


def load_month(month: str) -> dict:
    return _read_json(_month_path(month), {})


def list_leaves(month: str) -> dict:
    """{employee_id: {date: hours}}"""
    return _read_json(_leaves_path(month), {})


def set_leave(employee_id: str, date: str, hours: float) -> None:
    if hours <= 0:
        raise ValueError(f"请假小时数必须 > 0：{hours}")
    month = date[:7]
    data = list_leaves(month)
    data.setdefault(employee_id, {})[date] = float(hours)
    _write_json(_leaves_path(month), data)


def clear_leave(employee_id: str, date: str) -> None:
    month = date[:7]
    data = list_leaves(month)
    if employee_id in data and date in data[employee_id]:
        del data[employee_id][date]
        if not data[employee_id]:
            del data[employee_id]
        _write_json(_leaves_path(month), data)


def set_day(employee_id: str, date: str, times: dict) -> None:
    month = date[:7]
    data = load_month(month)
    data.setdefault(employee_id, {})[date] = {
        "start": times["start"],
        "end": times["end"],
    }
    _write_json(_month_path(month), data)


def clear_day(employee_id: str, date: str) -> None:
    month = date[:7]
    data = load_month(month)
    if employee_id in data and date in data[employee_id]:
        del data[employee_id][date]
        if not data[employee_id]:
            del data[employee_id]
        _write_json(_month_path(month), data)


_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def _iter_month_days(month: str):
    """Yields (date_str, weekday_int, weekday_cn) for each day in YYYY-MM."""
    year, mon = int(month[:4]), int(month[5:7])
    _, days = monthrange(year, mon)
    for d in range(1, days + 1):
        dt = date_cls(year, mon, d)
        yield dt.isoformat(), dt.weekday(), _WEEKDAY_CN[dt.weekday()]


def compute_summary(employee_id: str, month: str) -> dict:
    """计算员工月度总结：周日自动作为 1.0，缺勤推断。

    Args:
        employee_id: 员工 ID
        month: 月份，格式 "YYYY-MM"

    Returns:
        {
            "worked_days": float,     # 总工作日数
            "absent_days": int,       # 缺勤天数
            "total_workdays": int,    # 计入考勤的总天数（不含周日）
            "detail": [               # 每日详情
                {
                    "date": "2026-04-01",
                    "weekday": "一",
                    "start": "09:30" or "",
                    "end": "20:00" or "",
                    "day_fraction": 1.0,
                    "status": "normal" | "sunday" | "absent"
                },
                ...
            ]
        }
    """
    month_data = load_month(month).get(employee_id, {})
    holidays = set(list_holidays())
    special_days = list_special_days()
    leaves = list_leaves(month).get(employee_id, {})
    detail = []
    worked_days = 0.0
    absent_days = 0
    leave_hours_total = 0.0
    for date_str, wd_int, wd_cn in _iter_month_days(month):
        leave_h = leaves.get(date_str, 0.0)
        if wd_int == 6:  # Sunday
            detail.append({
                "date": date_str, "weekday": wd_cn,
                "start": "", "end": "",
                "day_fraction": 1.0, "status": "sunday",
                "leave_hours": leave_h,
            })
            worked_days += 1.0
            leave_hours_total += leave_h
            continue
        if date_str in holidays:
            detail.append({
                "date": date_str, "weekday": wd_cn,
                "start": "", "end": "",
                "day_fraction": 1.0, "status": "holiday",
                "leave_hours": leave_h,
            })
            worked_days += 1.0
            leave_hours_total += leave_h
            continue
        if date_str in special_days:
            sd = special_days[date_str]
            sd_hours = (_parse_hm(sd["end"]) - _parse_hm(sd["start"])) / 60
            rec = month_data.get(date_str)
            if rec:
                frac = day_fraction(rec["start"], rec["end"], standard_hours=sd_hours)
                detail.append({
                    "date": date_str, "weekday": wd_cn,
                    "start": rec["start"], "end": rec["end"],
                    "day_fraction": round(frac, 3), "status": "special",
                    "special_start": sd["start"], "special_end": sd["end"],
                    "leave_hours": leave_h,
                })
                worked_days += frac
            else:
                detail.append({
                    "date": date_str, "weekday": wd_cn,
                    "start": "", "end": "",
                    "day_fraction": 0.0, "status": "special_absent",
                    "special_start": sd["start"], "special_end": sd["end"],
                    "leave_hours": leave_h,
                })
                if leave_h <= 0:
                    absent_days += 1
            leave_hours_total += leave_h
            continue
        rec = month_data.get(date_str)
        if leave_h > 0:
            row = {
                "date": date_str, "weekday": wd_cn,
                "start": rec["start"] if rec else "",
                "end": rec["end"] if rec else "",
                "day_fraction": 0.0,
                "status": "leave",
                "leave_hours": leave_h,
            }
            if rec:
                frac = day_fraction(rec["start"], rec["end"])
                row["day_fraction"] = round(frac, 3)
                worked_days += frac
            detail.append(row)
            leave_hours_total += leave_h
            continue
        if rec:
            frac = day_fraction(rec["start"], rec["end"])
            detail.append({
                "date": date_str, "weekday": wd_cn,
                "start": rec["start"], "end": rec["end"],
                "day_fraction": round(frac, 3), "status": "normal",
                "leave_hours": 0.0,
            })
            worked_days += frac
        else:
            detail.append({
                "date": date_str, "weekday": wd_cn,
                "start": "", "end": "",
                "day_fraction": 0.0, "status": "absent",
                "leave_hours": 0.0,
            })
            absent_days += 1
    total_days = len(detail)
    return {
        "worked_days": round(worked_days, 3),
        "absent_days": absent_days,
        "total_workdays": total_days - absent_days,
        "month_days": total_days,
        "leave_hours_total": round(leave_hours_total, 3),
        "leave_days_equivalent": round(leave_hours_total / STANDARD_HOURS, 3),
        "detail": detail,
    }
