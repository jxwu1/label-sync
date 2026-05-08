"""考勤服务：员工 CRUD、月度 CRUD、summary 计算。"""

import json
import os
import time
from calendar import monthrange
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

_ATTENDANCE_DIR = Path(__file__).resolve().parent / "attendance"
_EMPLOYEES_FILE = "employees.json"
_HOLIDAYS_FILE = "holidays.json"
_SPECIAL_DAYS_FILE = "special_days.json"
_METADATA_FILE = "metadata.json"
_IO_RETRY_COUNT = 5
_IO_RETRY_DELAY_SEC = 0.02


def _employees_path() -> Path:
    return _ATTENDANCE_DIR / _EMPLOYEES_FILE


def _metadata_path() -> Path:
    return _ATTENDANCE_DIR / _METADATA_FILE


def _read_json(path: Path, default):
    if not path.exists():
        return default
    last_error = None
    for _ in range(_IO_RETRY_COUNT):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError as exc:
            last_error = exc
            time.sleep(_IO_RETRY_DELAY_SEC)
    raise last_error


def _write_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    temp_path = path.with_name(f"{path.name}.tmp")
    last_error = None
    for _ in range(_IO_RETRY_COUNT):
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, path)
            return
        except (FileNotFoundError, PermissionError) as exc:
            last_error = exc
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except FileExistsError:
                pass
            time.sleep(_IO_RETRY_DELAY_SEC)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except PermissionError:
                    pass
    raise last_error


def list_employees() -> list[dict]:
    return _read_json(_employees_path(), [])


def _next_employee_id() -> str:
    metadata = _read_json(_metadata_path(), {"next_id_num": 0})
    next_num = metadata.get("next_id_num", 0) + 1
    metadata["next_id_num"] = next_num
    _write_json(_metadata_path(), metadata)
    return f"e{next_num:03d}"


def create_employee(name: str, *, start_date: str | None = None) -> dict:
    """新建员工。可选 start_date 决定入职日（之前的天 compute_summary 标 pre_join）。"""
    employees = list_employees()
    emp = {
        "id": _next_employee_id(),
        "name": name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if start_date:
        emp["start_date"] = start_date
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


# 希腊法定节假日。固定日期 + Orthodox Easter 衍生的几个浮动日。
# Easter 浮动衍生：Clean Monday = -48d，Good Friday = -2d，Easter Monday = +1d，Holy Spirit = +50d。
# Easter 复活节周日本身已是周日（不需要单独标），所以这里不收录。
# 每年新加之前请核对 Easter 日期（如 2027 = 5/2）。
_GR_HOLIDAYS_BY_YEAR: dict[int, list[str]] = {
    # Easter 2025 = 04/20
    2025: [
        "2025-01-01",  # Πρωτοχρονιά New Year
        "2025-01-06",  # Θεοφάνεια Epiphany
        "2025-03-03",  # Καθαρά Δευτέρα Clean Monday
        "2025-03-25",  # Independence Day
        "2025-04-18",  # Μεγάλη Παρασκευή Good Friday
        "2025-04-21",  # Δευτέρα του Πάσχα Easter Monday
        "2025-05-01",  # Πρωτομαγιά Labor Day
        "2025-06-09",  # Αγίου Πνεύματος Holy Spirit (Whit Monday)
        "2025-08-15",  # Κοίμηση της Θεοτόκου Assumption
        "2025-10-28",  # Επέτειος του Όχι Ohi Day
        "2025-12-25",  # Christmas
        "2025-12-26",  # Σύναξη της Θεοτόκου Synaxis (Boxing Day)
    ],
    # Easter 2026 = 04/12
    2026: [
        "2026-01-01",
        "2026-01-06",
        "2026-02-23",  # Clean Monday
        "2026-03-25",
        "2026-04-10",  # Good Friday
        "2026-04-13",  # Easter Monday
        "2026-05-01",
        "2026-06-01",  # Holy Spirit
        "2026-08-15",
        "2026-10-28",
        "2026-12-25",
        "2026-12-26",
    ],
}


def import_holidays_for_year(year: int) -> dict:
    """批量导入指定年份的希腊法定节假日。

    返回 {added: int, holidays: list[str]}。已存在的日期不重复。
    年份未收录 → ValueError。
    """
    if year not in _GR_HOLIDAYS_BY_YEAR:
        raise ValueError(f"未收录 {year} 年节假日数据，请手动添加或在 _GR_HOLIDAYS_BY_YEAR 补全")
    existing = set(list_holidays())
    new_dates = [d for d in _GR_HOLIDAYS_BY_YEAR[year] if d not in existing]
    if new_dates:
        merged = sorted(existing.union(new_dates))
        _write_json(_holidays_path(), merged)
    return {"added": len(new_dates), "holidays": list_holidays()}


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
STANDARD_END = "20:00"


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
    """{employee_id: {date: {type, start?, end?, hours}}}"""
    return _read_json(_leaves_path(month), {})


def _compute_leave_hours(
    leave_type: str, start: str, end: str, day_standard_hours: float, day_end: str
) -> float:
    if leave_type == "full":
        return day_standard_hours
    if leave_type == "range":
        if not start or not end:
            raise ValueError("range 类型必须提供 start 和 end")
        s, e = _parse_hm(start), _parse_hm(end)
        if e <= s:
            raise ValueError(f"end 必须晚于 start：{start}-{end}")
        return (e - s) / 60
    if leave_type == "left":
        if not start:
            raise ValueError("left 类型必须提供 start")
        s, e = _parse_hm(start), _parse_hm(day_end)
        if e <= s:
            raise ValueError(f"离开时间必须早于下班时间 {day_end}：{start}")
        return (e - s) / 60
    raise ValueError(f"未知请假类型：{leave_type}")


def set_leave(employee_id: str, date: str, leave_type: str, start: str = "", end: str = "") -> dict:
    """记录请假。返回写入的条目（含 hours）。

    leave_type:
      - "full": 全天，hours = 当天标准时长
      - "range": 离开后回来，需 start + end
      - "left":  离开未回来，需 start
    """
    special_days = list_special_days()
    sd = special_days.get(date)
    if sd:
        day_hours = (_parse_hm(sd["end"]) - _parse_hm(sd["start"])) / 60
        day_end = sd["end"]
    else:
        day_hours = STANDARD_HOURS
        day_end = STANDARD_END
    hours = _compute_leave_hours(leave_type, start, end, day_hours, day_end)
    if hours <= 0:
        raise ValueError(f"请假小时数必须 > 0：{hours}")
    entry = {"type": leave_type, "hours": round(hours, 3)}
    if start:
        entry["start"] = start
    if end:
        entry["end"] = end
    month = date[:7]
    data = list_leaves(month)
    data.setdefault(employee_id, {})[date] = entry
    _write_json(_leaves_path(month), data)
    return entry


def clear_leave(employee_id: str, date: str) -> None:
    month = date[:7]
    data = list_leaves(month)
    if employee_id in data and date in data[employee_id]:
        del data[employee_id][date]
        if not data[employee_id]:
            del data[employee_id]
        _write_json(_leaves_path(month), data)


def set_leave_range(
    employee_id: str,
    from_date: str,
    to_date: str,
    leave_type: str,
    start: str = "",
    end: str = "",
) -> dict:
    """批量设置区间请假。

    每天调用 set_leave。**自动跳过周日**（auto-paid，不需要标 leave）；
    leave_type 必须是 'full' / 'range' / 'left'。leave_type='full' 是日常最常见
    用法，单次扫平整段假期。

    返回 {days_set: int, days_skipped_sunday: int}。
    """
    if leave_type not in ("full", "range", "left"):
        raise ValueError(f"未知请假类型：{leave_type}")
    f = date_cls.fromisoformat(from_date)
    t = date_cls.fromisoformat(to_date)
    if f > t:
        raise ValueError(f"from {from_date} 不能晚于 to {to_date}")
    days_set = 0
    days_skipped_sunday = 0
    cur = f
    while cur <= t:
        if cur.weekday() == 6:
            days_skipped_sunday += 1
        else:
            set_leave(employee_id, cur.isoformat(), leave_type, start=start, end=end)
            days_set += 1
        cur = date_cls.fromordinal(cur.toordinal() + 1)
    return {"days_set": days_set, "days_skipped_sunday": days_skipped_sunday}


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


def _employee_start_date(employee_id: str) -> date_cls | None:
    """读员工显式 start_date 字段。这一日之前的天计为 pre_join。

    **不再 fallback 到 created_at**：created_at 是系统建档时间，不等于入职日；
    用户先有历史考勤数据、后才在系统建账号的场景下，回退会把历史数据全部
    挡掉变成 pre_join（实际数据未删，仅视图遮蔽）。

    缺 start_date / 解析失败 → None → 全月正常显示，无 pre_join 过滤。
    新员工想用 pre_join 时手动加 start_date 字段（或将来 UI 加入职日 field）。
    """
    for emp in list_employees():
        if emp.get("id") != employee_id:
            continue
        s = emp.get("start_date")
        if not s:
            return None
        try:
            return datetime.fromisoformat(s).date()
        except (ValueError, TypeError):
            return None
    return None


def list_inactive_periods(employee_id: str) -> list[dict]:
    """读员工的不在职区间列表（长期休假/产假/停薪留职等）。"""
    for emp in list_employees():
        if emp.get("id") == employee_id:
            return emp.get("inactive_periods", [])
    return []


def add_inactive_period(employee_id: str, from_date: str, to_date: str, reason: str = "") -> dict:
    """添加一个不在职区间。这段期间内每天都不计入考勤（包括周日 / 节假日）。

    适用场景：长期病假回归后回到本月、产假、停薪留职等。
    与单日 set_leave 区别：本接口的天完全不计任何数字（pre_join 状态）；
    leave 的天周日仍算 1.0、accumulated leave_hours_total 也会算。
    """
    f = date_cls.fromisoformat(from_date)
    t = date_cls.fromisoformat(to_date)
    if f > t:
        raise ValueError(f"from {from_date} 不能晚于 to {to_date}")
    employees = list_employees()
    for emp in employees:
        if emp.get("id") != employee_id:
            continue
        periods = emp.setdefault("inactive_periods", [])
        period = {"from": from_date, "to": to_date}
        if reason:
            period["reason"] = reason
        periods.append(period)
        _write_json(_employees_path(), employees)
        return period
    raise ValueError(f"员工不存在：{employee_id}")


def remove_inactive_period(employee_id: str, from_date: str, to_date: str) -> bool:
    """按 from+to 精确匹配删除一个不在职区间。返回 True 如果删了一条。"""
    employees = list_employees()
    for emp in employees:
        if emp.get("id") != employee_id:
            continue
        periods = emp.get("inactive_periods", [])
        for i, p in enumerate(periods):
            if p.get("from") == from_date and p.get("to") == to_date:
                periods.pop(i)
                if not periods:
                    emp.pop("inactive_periods", None)
                _write_json(_employees_path(), employees)
                return True
        return False
    return False


def _date_in_inactive_periods(d: date_cls, periods: list[dict]) -> bool:
    for p in periods:
        try:
            f = date_cls.fromisoformat(p["from"])
            t = date_cls.fromisoformat(p["to"])
            if f <= d <= t:
                return True
        except (KeyError, ValueError, TypeError):
            continue
    return False


def _make_row(
    date: str,
    weekday: str,
    status: str,
    *,
    start: str = "",
    end: str = "",
    day_fraction: float = 0.0,
    leave_entry: dict | None = None,
    special: dict | None = None,
) -> dict:
    """构造单日 detail 行：保证字段完整，避免分散 dict 字面量遗漏字段。"""
    row = {
        "date": date,
        "weekday": weekday,
        "status": status,
        "start": start,
        "end": end,
        "day_fraction": day_fraction,
        "leave_hours": leave_entry["hours"] if leave_entry else 0.0,
        "leave_type": leave_entry["type"] if leave_entry else "",
        "leave_start": leave_entry.get("start", "") if leave_entry else "",
        "leave_end": leave_entry.get("end", "") if leave_entry else "",
    }
    if special:
        row["special_start"] = special["start"]
        row["special_end"] = special["end"]
    return row


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
    employees_by_id = {emp.get("id"): emp for emp in list_employees()}
    return _compute_one_summary(
        employee_id,
        month,
        employees_by_id=employees_by_id,
        month_data=load_month(month),
        holidays=set(list_holidays()),
        special_days=list_special_days(),
        leaves_by_emp=list_leaves(month),
    )


def compute_summaries_batch(employees: list[dict], month: str) -> dict[str, dict]:
    """批量算多员工月度总结，共享数据只读一次。

    与循环调 compute_summary 行为完全一致；省的是 6 倍磁盘 JSON 读
    （employees / month / holidays / special_days / leaves，外加 _employee_start_date /
    list_inactive_periods 共用 employees）。调用方传入已读的 employees 列表
    复用，避免本函数再读一次。fill_rates 跑 N=20 员工时实测 _read_json 从
    6N+1=121 次降到 5 次（month / leaves / holidays / special_days + 路由层
    list_employees）。
    """
    employees_by_id = {emp.get("id"): emp for emp in employees}
    month_data = load_month(month)
    holidays = set(list_holidays())
    special_days = list_special_days()
    leaves_by_emp = list_leaves(month)
    return {
        eid: _compute_one_summary(
            eid,
            month,
            employees_by_id=employees_by_id,
            month_data=month_data,
            holidays=holidays,
            special_days=special_days,
            leaves_by_emp=leaves_by_emp,
        )
        for eid in employees_by_id
    }


def _compute_one_summary(
    employee_id: str,
    month: str,
    *,
    employees_by_id: dict[str, dict],
    month_data: dict,
    holidays: set[str],
    special_days: dict,
    leaves_by_emp: dict,
) -> dict:
    """compute_summary 的纯计算核心，所有共享数据由调用方预读后传入。"""
    emp = employees_by_id.get(employee_id, {})
    start_str = emp.get("start_date") if emp else None
    if start_str:
        try:
            emp_start: date_cls | None = datetime.fromisoformat(start_str).date()
        except (ValueError, TypeError):
            emp_start = None
    else:
        emp_start = None
    inactive_periods = emp.get("inactive_periods", []) if emp else []
    month_data_emp = month_data.get(employee_id, {})
    leaves = leaves_by_emp.get(employee_id, {})
    detail = []
    worked_days = 0.0
    absent_days = 0
    leave_hours_total = 0.0
    for date_str, wd_int, wd_cn in _iter_month_days(month):
        # 入职日之前 + 不在职区间内的天都不计入：含周日 / 节假日 / 缺勤都不算。
        # 月底新来 / 长期休假回归 / 产假等场景统一用 pre_join 状态。
        cur_d = date_cls.fromisoformat(date_str)
        if emp_start is not None and cur_d < emp_start:
            detail.append(_make_row(date_str, wd_cn, "pre_join"))
            continue
        if _date_in_inactive_periods(cur_d, inactive_periods):
            detail.append(_make_row(date_str, wd_cn, "pre_join"))
            continue
        leave_entry = leaves.get(date_str)
        leave_h = leave_entry["hours"] if leave_entry else 0.0
        leave_hours_total += leave_h
        if wd_int == 6:  # Sunday
            detail.append(
                _make_row(date_str, wd_cn, "sunday", day_fraction=1.0, leave_entry=leave_entry)
            )
            worked_days += 1.0
            continue
        if date_str in holidays:
            detail.append(
                _make_row(date_str, wd_cn, "holiday", day_fraction=1.0, leave_entry=leave_entry)
            )
            worked_days += 1.0
            continue
        if date_str in special_days:
            sd = special_days[date_str]
            sd_hours = (_parse_hm(sd["end"]) - _parse_hm(sd["start"])) / 60
            rec = month_data_emp.get(date_str)
            if rec:
                frac = day_fraction(rec["start"], rec["end"], standard_hours=sd_hours)
                detail.append(
                    _make_row(
                        date_str,
                        wd_cn,
                        "special",
                        start=rec["start"],
                        end=rec["end"],
                        day_fraction=round(frac, 3),
                        leave_entry=leave_entry,
                        special=sd,
                    )
                )
                worked_days += frac
            else:
                detail.append(
                    _make_row(
                        date_str, wd_cn, "special_absent", leave_entry=leave_entry, special=sd
                    )
                )
                if leave_h <= 0:
                    absent_days += 1
            continue
        rec = month_data_emp.get(date_str)
        if leave_h > 0:
            frac = round(day_fraction(rec["start"], rec["end"]), 3) if rec else 0.0
            detail.append(
                _make_row(
                    date_str,
                    wd_cn,
                    "leave",
                    start=rec["start"] if rec else "",
                    end=rec["end"] if rec else "",
                    day_fraction=frac,
                    leave_entry=leave_entry,
                )
            )
            if rec:
                worked_days += frac
            continue
        if rec:
            frac = day_fraction(rec["start"], rec["end"])
            detail.append(
                _make_row(
                    date_str,
                    wd_cn,
                    "normal",
                    start=rec["start"],
                    end=rec["end"],
                    day_fraction=round(frac, 3),
                )
            )
            worked_days += frac
        else:
            detail.append(_make_row(date_str, wd_cn, "absent"))
            absent_days += 1
    # 在职天数（detail 里非 pre_join 的天）。所有派生数字都基于这个，让月底新来
    # 的员工看到一致的在职期间统计而不是被算上未入职的周日和缺勤。
    total_days = sum(1 for r in detail if r["status"] != "pre_join")
    return {
        "worked_days": round(worked_days, 3),
        "absent_days": absent_days,
        "total_workdays": total_days - absent_days,
        "month_days": total_days,
        "leave_hours_total": round(leave_hours_total, 3),
        "leave_days_equivalent": round(leave_hours_total / STANDARD_HOURS, 3),
        "detail": detail,
    }
