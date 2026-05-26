"""一次性迁移脚本：attendance/*.json → DB 6 张表。

用法：
    python tools/migrate_attendance.py [--attendance-dir PATH]

默认从 CONFIG.base_dir / attendance 读取 JSON，写入 DATABASE_URL 指定的数据库。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import (
    AttendanceRecord,
    Employee,
    InactivePeriod,
    LeaveRecord,
    PublicHoliday,
    SpecialDay,
    get_session,
)
from app.config import CONFIG


def _read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def migrate(attendance_dir: Path) -> dict:
    stats = {
        "employees": 0,
        "inactive_periods": 0,
        "holidays": 0,
        "special_days": 0,
        "attendance_records": 0,
        "leave_records": 0,
    }

    employees_data = _read_json(attendance_dir / "employees.json", [])
    holidays_data = _read_json(attendance_dir / "holidays.json", [])
    special_days_data = _read_json(attendance_dir / "special_days.json", {})

    with get_session() as s:
        # ── Employees + inactive_periods ──
        for emp in employees_data:
            eid = emp.get("id") or emp.get("employee_id")
            if not eid:
                continue
            db_emp = Employee(
                employee_id=eid,
                name=emp.get("name", ""),
                created_at=emp.get("created_at"),
                start_date=emp.get("start_date"),
                active=1,
                notes=emp.get("notes"),
            )
            s.merge(db_emp)
            stats["employees"] += 1

            for period in emp.get("inactive_periods", []):
                ip = InactivePeriod(
                    employee_id=eid,
                    start_date=period.get("from", ""),
                    end_date=period.get("to"),
                    reason=period.get("reason"),
                )
                s.add(ip)
                stats["inactive_periods"] += 1

        # ── Public holidays ──
        for date_str in holidays_data:
            s.merge(PublicHoliday(
                holiday_date=date_str,
                name="希腊法定节假日",
                is_paid=1,
            ))
            stats["holidays"] += 1

        # ── Special days ──
        for date_str, info in special_days_data.items():
            s.merge(SpecialDay(
                special_date=date_str,
                label=info.get("label") or info.get("start"),
                end_time=info.get("end"),
            ))
            stats["special_days"] += 1

        # ── Monthly attendance + leaves ──
        month_files = sorted(attendance_dir.glob("????-??.json"))
        for mf in month_files:
            if ".leaves." in mf.name:
                continue
            month_data = _read_json(mf, {})
            month_str = mf.stem

            for emp_id, days in month_data.items():
                for date_str, times in days.items():
                    rec = AttendanceRecord(
                        employee_id=emp_id,
                        work_date=date_str,
                        start_time=times.get("start"),
                        end_time=times.get("end"),
                    )
                    s.merge(rec)
                    stats["attendance_records"] += 1

            leaves_path = attendance_dir / f"{month_str}.leaves.json"
            if leaves_path.exists():
                leaves_data = _read_json(leaves_path, {})
                for emp_id, day_leaves in leaves_data.items():
                    for date_str, entry in day_leaves.items():
                        lr = LeaveRecord(
                            employee_id=emp_id,
                            start_date=date_str,
                            leave_type=entry.get("type", "full"),
                            hours=entry.get("hours"),
                            notes=None,
                        )
                        if entry.get("start"):
                            lr.notes = f"start={entry['start']}"
                            if entry.get("end"):
                                lr.notes += f" end={entry['end']}"
                        s.add(lr)
                        stats["leave_records"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate attendance JSON → DB")
    parser.add_argument(
        "--attendance-dir",
        type=Path,
        default=Path(CONFIG.base_dir) / "attendance",
    )
    args = parser.parse_args()

    if not args.attendance_dir.exists():
        print(f"目录不存在: {args.attendance_dir}")
        sys.exit(1)

    print(f"读取: {args.attendance_dir}")
    stats = migrate(args.attendance_dir)
    print("迁移完成:")
    for k, v in stats.items():
        print(f"   {k}: {v}")


if __name__ == "__main__":
    main()
