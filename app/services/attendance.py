"""考勤服务：员工 CRUD、月度 CRUD、summary 计算。

存储层：SQLAlchemy ORM（app.models 中的 Attendance 相关表）。
所有公共函数签名和返回值结构与旧 JSON 版本完全一致。
"""

from calendar import monthrange
from datetime import date as date_cls
from datetime import datetime, timedelta

from sqlalchemy import select, delete, func

from app.models import (
    AttendanceRecord,
    Employee,
    InactivePeriod,
    LeaveRecord,
    PublicHoliday,
    SpecialDay,
    SystemSetting,
    get_session,
)


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


# ── Employee CRUD ─────────────────────────────────────────────────────


def list_employees() -> list[dict]:
    with get_session() as s:
        emps = s.execute(
            select(Employee).order_by(Employee.employee_id)
        ).scalars().all()
        result = []
        for emp in emps:
            d = {
                "id": emp.employee_id,
                "name": emp.name,
                "created_at": emp.created_at,
            }
            if emp.start_date:
                d["start_date"] = emp.start_date
            periods = [
                _inactive_period_to_dict(ip)
                for ip in emp.inactive_periods
            ]
            if periods:
                d["inactive_periods"] = periods
            result.append(d)
        return result


def _inactive_period_to_dict(ip: InactivePeriod) -> dict:
    d = {"from": ip.start_date, "to": ip.end_date}
    if ip.reason:
        d["reason"] = ip.reason
    return d


def _next_employee_id() -> str:
    with get_session() as s:
        setting = s.get(SystemSetting, "employee_next_id")
        max_id = s.execute(select(func.max(Employee.employee_id))).scalar()
        counter = 0
        if setting and setting.value:
            try:
                counter = int(setting.value)
            except ValueError:
                pass
        if max_id and max_id.startswith("e"):
            try:
                counter = max(counter, int(max_id[1:]))
            except ValueError:
                pass
        counter += 1
        if setting:
            setting.value = str(counter)
        else:
            s.add(SystemSetting(key="employee_next_id", value=str(counter)))
    return f"e{counter:03d}"


def create_employee(name: str, *, start_date: str | None = None) -> dict:
    """新建员工。可选 start_date 决定入职日（之前的天 compute_summary 标 pre_join）。"""
    emp_id = _next_employee_id()
    created_at = datetime.now().isoformat(timespec="seconds")
    emp = Employee(
        employee_id=emp_id,
        name=name,
        created_at=created_at,
        start_date=start_date,
        active=1,
    )
    with get_session() as s:
        s.add(emp)
    result = {"id": emp_id, "name": name, "created_at": created_at}
    if start_date:
        result["start_date"] = start_date
    return result


def delete_employee(employee_id: str) -> None:
    with get_session() as s:
        s.execute(delete(Employee).where(Employee.employee_id == employee_id))


# ── Holidays ──────────────────────────────────────────────────────────


def list_holidays() -> list[str]:
    with get_session() as s:
        rows = s.execute(
            select(PublicHoliday.holiday_date).order_by(PublicHoliday.holiday_date)
        ).scalars().all()
        return list(rows)


def add_holiday(date: str) -> None:
    with get_session() as s:
        existing = s.get(PublicHoliday, date)
        if not existing:
            s.add(PublicHoliday(holiday_date=date, name="希腊法定节假日", is_paid=1))


def remove_holiday(date: str) -> None:
    with get_session() as s:
        s.execute(delete(PublicHoliday).where(PublicHoliday.holiday_date == date))


# 希腊法定节假日 = 8 个固定日 + 4 个 Orthodox Easter 衍生浮动日。
# 浮动：Clean Monday = -48d，Good Friday = -2d，Easter Monday = +1d，Holy Spirit = +50d。
# Easter 周日本身已是周日（不需要单独标），所以不收录。
_GR_HOLIDAY_YEAR_MIN = 2000
_GR_HOLIDAY_YEAR_MAX = 2099


def _orthodox_easter(year: int) -> date_cls:
    """用 Meeus 算法计算 Orthodox Easter 的 Gregorian 日期。

    仅支持 2000-2099（Julian→Gregorian 偏移固定 +13 天）。2100 起偏移变 +14 天，
    届时需要调整下面的 timedelta 常量。
    """
    if not _GR_HOLIDAY_YEAR_MIN <= year <= _GR_HOLIDAY_YEAR_MAX:
        raise ValueError(
            f"未收录 {year} 年节假日数据（仅支持 {_GR_HOLIDAY_YEAR_MIN}-{_GR_HOLIDAY_YEAR_MAX}）"
        )
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    return date_cls(year, month, day) + timedelta(days=13)


def _compute_gr_holidays(year: int) -> list[str]:
    """生成指定年份希腊法定节假日列表（升序，ISO 日期）。"""
    easter = _orthodox_easter(year)
    fixed = [
        f"{year}-01-01",  # Πρωτοχρονιά New Year
        f"{year}-01-06",  # Θεοφάνεια Epiphany
        f"{year}-03-25",  # Independence Day
        f"{year}-05-01",  # Πρωτομαγιά Labor Day
        f"{year}-08-15",  # Κοίμηση της Θεοτόκου Assumption
        f"{year}-10-28",  # Επέτειος του Όχι Ohi Day
        f"{year}-12-25",  # Christmas
        f"{year}-12-26",  # Σύναξη της Θεοτόκου Synaxis (Boxing Day)
    ]
    floating = [
        (easter + timedelta(days=-48)).isoformat(),  # Καθαρά Δευτέρα Clean Monday
        (easter + timedelta(days=-2)).isoformat(),  # Μεγάλη Παρασκευή Good Friday
        (easter + timedelta(days=1)).isoformat(),  # Δευτέρα του Πάσχα Easter Monday
        (easter + timedelta(days=50)).isoformat(),  # Αγίου Πνεύματος Holy Spirit
    ]
    return sorted(fixed + floating)


def import_holidays_for_year(year: int) -> dict:
    """批量导入指定年份的希腊法定节假日。

    返回 {added: int, holidays: list[str]}。已存在的日期不重复。
    年份超出 _orthodox_easter 支持范围 → ValueError。
    """
    target = _compute_gr_holidays(year)  # 超范围在这里抛 ValueError
    existing = set(list_holidays())
    new_dates = [d for d in target if d not in existing]
    if new_dates:
        with get_session() as s:
            for d in new_dates:
                s.add(PublicHoliday(holiday_date=d, name="希腊法定节假日", is_paid=1))
    return {"added": len(new_dates), "holidays": list_holidays()}


# ── Special Days ──────────────────────────────────────────────────────


def list_special_days() -> dict:
    with get_session() as s:
        rows = s.execute(
            select(SpecialDay).order_by(SpecialDay.special_date)
        ).scalars().all()
        return {
            sd.special_date: {"start": sd.label or "", "end": sd.end_time or ""}
            for sd in rows
        }


def set_special_day(date: str, start: str, end: str) -> None:
    # 校验时段合法
    day_fraction(start, end, standard_hours=1.0)  # 仅触发 end>start 校验
    with get_session() as s:
        existing = s.get(SpecialDay, date)
        if existing:
            existing.label = start
            existing.end_time = end
        else:
            s.add(SpecialDay(special_date=date, label=start, end_time=end))


def remove_special_day(date: str) -> None:
    with get_session() as s:
        s.execute(delete(SpecialDay).where(SpecialDay.special_date == date))


# ── Attendance records (month data) ──────────────────────────────────


def load_month(month: str) -> dict:
    """返回 {emp_id: {date: {"start": "HH:MM", "end": "HH:MM"}}}"""
    date_prefix = month  # "YYYY-MM"
    with get_session() as s:
        rows = s.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.work_date.like(f"{date_prefix}%")
            )
        ).scalars().all()
        result: dict[str, dict[str, dict]] = {}
        for r in rows:
            emp_data = result.setdefault(r.employee_id, {})
            emp_data[r.work_date] = {
                "start": r.start_time or "",
                "end": r.end_time or "",
            }
        return result


def set_day(employee_id: str, date: str, times: dict) -> None:
    with get_session() as s:
        existing = s.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.work_date == date,
            )
        ).scalar_one_or_none()
        if existing:
            existing.start_time = times["start"]
            existing.end_time = times["end"]
        else:
            s.add(AttendanceRecord(
                employee_id=employee_id,
                work_date=date,
                start_time=times["start"],
                end_time=times["end"],
            ))


def clear_day(employee_id: str, date: str) -> None:
    with get_session() as s:
        s.execute(
            delete(AttendanceRecord).where(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.work_date == date,
            )
        )


# ── Leave records ────────────────────────────────────────────────────


def list_leaves(month: str) -> dict:
    """{employee_id: {date: {type, start?, end?, hours}}}"""
    date_prefix = month  # "YYYY-MM"
    with get_session() as s:
        rows = s.execute(
            select(LeaveRecord).where(
                LeaveRecord.start_date.like(f"{date_prefix}%")
            )
        ).scalars().all()
        result: dict[str, dict[str, dict]] = {}
        for r in rows:
            entry: dict = {"type": r.leave_type, "hours": r.hours or 0.0}
            # notes 格式: "start=HH:MM end=HH:MM" 或 "start=HH:MM"
            if r.notes:
                for part in r.notes.split():
                    if part.startswith("start="):
                        entry["start"] = part[6:]
                    elif part.startswith("end="):
                        entry["end"] = part[4:]
            emp_data = result.setdefault(r.employee_id, {})
            emp_data[r.start_date] = entry
        return result


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
    # Build notes from start/end
    notes = None
    if start:
        notes = f"start={start}"
        if end:
            notes += f" end={end}"
    with get_session() as s:
        existing = s.execute(
            select(LeaveRecord).where(
                LeaveRecord.employee_id == employee_id,
                LeaveRecord.start_date == date,
            )
        ).scalar_one_or_none()
        if existing:
            existing.leave_type = leave_type
            existing.hours = round(hours, 3)
            existing.notes = notes
        else:
            s.add(LeaveRecord(
                employee_id=employee_id,
                start_date=date,
                leave_type=leave_type,
                hours=round(hours, 3),
                notes=notes,
            ))
    return entry


def clear_leave(employee_id: str, date: str) -> None:
    with get_session() as s:
        s.execute(
            delete(LeaveRecord).where(
                LeaveRecord.employee_id == employee_id,
                LeaveRecord.start_date == date,
            )
        )


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


# ── Inactive Periods ─────────────────────────────────────────────────


def list_inactive_periods(employee_id: str) -> list[dict]:
    """读员工的不在职区间列表（长期休假/产假/停薪留职等）。"""
    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp:
            return []
        return [_inactive_period_to_dict(ip) for ip in emp.inactive_periods]


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
    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp:
            raise ValueError(f"员工不存在：{employee_id}")
        ip = InactivePeriod(
            employee_id=employee_id,
            start_date=from_date,
            end_date=to_date,
            reason=reason or None,
        )
        s.add(ip)
    period = {"from": from_date, "to": to_date}
    if reason:
        period["reason"] = reason
    return period


def remove_inactive_period(employee_id: str, from_date: str, to_date: str) -> bool:
    """按 from+to 精确匹配删除一个不在职区间。返回 True 如果删了一条。"""
    with get_session() as s:
        row = s.execute(
            select(InactivePeriod).where(
                InactivePeriod.employee_id == employee_id,
                InactivePeriod.start_date == from_date,
                InactivePeriod.end_date == to_date,
            )
        ).scalar_one_or_none()
        if row:
            s.delete(row)
            return True
        return False


# ── Summary computation ──────────────────────────────────────────────

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
    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp or not emp.start_date:
            return None
        try:
            return datetime.fromisoformat(emp.start_date).date()
        except (ValueError, TypeError):
            return None


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
    employees_by_id = {emp["id"]: emp for emp in list_employees()}
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

    与循环调 compute_summary 行为完全一致；省的是 N 倍数据库查询
    （employees / month / holidays / special_days / leaves）。调用方传入已读
    的 employees 列表复用，避免本函数再读一次。
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
