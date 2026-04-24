"""考勤报表：PDF + CSV。"""

import csv
import io

import attendance_service

_CSV_HEADER = ["员工", "日期", "星期", "上班", "下班", "天数", "状态"]


def build_csv(month: str) -> bytes:
    employees = attendance_service.list_employees()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_HEADER)
    for emp in employees:
        summary = attendance_service.compute_summary(emp["id"], month)
        for row in summary["detail"]:
            writer.writerow([
                emp["name"], row["date"], row["weekday"],
                row["start"], row["end"],
                row["day_fraction"], row["status"],
            ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
