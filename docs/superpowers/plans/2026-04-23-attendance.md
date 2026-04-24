# 员工月度考勤 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现按月手工录入员工上下班时间、自动计算工作天数、导出 PDF + CSV 的考勤模块。

**Architecture:** Flask blueprint (`routes_attendance`) + 两个服务模块（`attendance_service` 管 CRUD + 计算，`attendance_report_service` 管 PDF/CSV）。前端复用现有 `index.html` 单页导航模式，新增一个 `pageAttendance` 注入月度网格。数据按月存 `attendance/YYYY-MM.json`，员工存 `attendance/employees.json`。

**Tech Stack:** Flask / reportlab / 原生 JS / Python unittest

**Spec:** `docs/superpowers/specs/2026-04-23-attendance-design.md`

---

## 文件结构

**新增文件**
- `attendance_service.py` — 员工 CRUD + 月度 CRUD + day_fraction + compute_summary
- `attendance_report_service.py` — build_pdf + build_csv
- `routes_attendance.py` — Flask blueprint
- `static/js/attendance.js` — 页面逻辑
- `static/css/attendance.css` — 样式
- `tests/test_attendance_service.py`
- `tests/test_attendance_report_service.py`

**修改文件**
- `routes.py` — 注册 attendance blueprint
- `templates/index.html` — 加 nav 项 + page 容器 + script 引用 + css 引用
- `更新日志.md` — v1.8 条目

---

## Task 1: 创建 attendance_service — 员工 CRUD（TDD）

**Files:**
- Create: `attendance_service.py`
- Test: `tests/test_attendance_service.py`

- [ ] **Step 1.1: 写失败测试（员工 CRUD）**

Create `tests/test_attendance_service.py`:

```python
import shutil
import unittest
from pathlib import Path

import attendance_service as svc

_TEST_DIR = Path(__file__).resolve().parent / "_test_attendance"


class TestEmployeeCrud(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._ATTENDANCE_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_list_empty_initially(self):
        self.assertEqual(svc.list_employees(), [])

    def test_create_assigns_id_e001(self):
        emp = svc.create_employee("小王")
        self.assertEqual(emp["id"], "e001")
        self.assertEqual(emp["name"], "小王")
        self.assertIn("created_at", emp)

    def test_create_increments_id(self):
        svc.create_employee("A")
        emp = svc.create_employee("B")
        self.assertEqual(emp["id"], "e002")

    def test_delete_removes_from_list(self):
        emp = svc.create_employee("X")
        svc.delete_employee(emp["id"])
        self.assertEqual(svc.list_employees(), [])

    def test_deleted_id_not_reused(self):
        e1 = svc.create_employee("A")
        svc.delete_employee(e1["id"])
        e2 = svc.create_employee("B")
        self.assertEqual(e2["id"], "e002")
```

- [ ] **Step 1.2: 运行测试确认失败**

Run: `python -m pytest tests/test_attendance_service.py::TestEmployeeCrud -v`
Expected: FAIL with "No module named attendance_service"

- [ ] **Step 1.3: 创建最小实现**

Create `attendance_service.py`:

```python
"""考勤服务：员工 CRUD、月度 CRUD、summary 计算。"""

import json
from datetime import datetime
from pathlib import Path

_ATTENDANCE_DIR = Path(__file__).resolve().parent / "attendance"
_EMPLOYEES_FILE = "employees.json"


def _employees_path() -> Path:
    return _ATTENDANCE_DIR / _EMPLOYEES_FILE


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_employees() -> list[dict]:
    return _read_json(_employees_path(), [])


def _next_employee_id(employees: list[dict]) -> str:
    max_num = 0
    for emp in employees:
        try:
            num = int(emp["id"][1:])
        except (ValueError, KeyError):
            continue
        if num > max_num:
            max_num = num
    return f"e{max_num + 1:03d}"


def create_employee(name: str) -> dict:
    employees = list_employees()
    emp = {
        "id": _next_employee_id(employees),
        "name": name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    employees.append(emp)
    _write_json(_employees_path(), employees)
    return emp


def delete_employee(employee_id: str) -> None:
    employees = [e for e in list_employees() if e["id"] != employee_id]
    _write_json(_employees_path(), employees)
```

- [ ] **Step 1.4: 运行测试确认通过**

Run: `python -m pytest tests/test_attendance_service.py::TestEmployeeCrud -v`
Expected: 5 passed

- [ ] **Step 1.5: Commit**

```bash
git add attendance_service.py tests/test_attendance_service.py
git commit -m "feat: attendance_service 员工 CRUD + 单测"
```

---

## Task 2: day_fraction 计算（纯函数 + TDD）

**Files:**
- Modify: `attendance_service.py` (append)
- Test: `tests/test_attendance_service.py` (append)

- [ ] **Step 2.1: 追加测试**

Append to `tests/test_attendance_service.py`:

```python
class TestDayFraction(unittest.TestCase):
    def test_full_day(self):
        self.assertAlmostEqual(svc.day_fraction("09:30", "20:00"), 1.0)

    def test_half_day(self):
        # 09:30-15:30 = 6h, 6/10.5 ≈ 0.571
        self.assertAlmostEqual(svc.day_fraction("09:30", "15:30"), 6.0 / 10.5)

    def test_overtime_capped_at_one(self):
        # 09:30-21:00 = 11.5h, 封顶 1.0
        self.assertAlmostEqual(svc.day_fraction("09:30", "21:00"), 1.0)

    def test_rejects_end_before_start(self):
        with self.assertRaises(ValueError):
            svc.day_fraction("20:00", "09:30")

    def test_rejects_equal_times(self):
        with self.assertRaises(ValueError):
            svc.day_fraction("09:30", "09:30")
```

- [ ] **Step 2.2: 运行失败**

Run: `python -m pytest tests/test_attendance_service.py::TestDayFraction -v`
Expected: FAIL with "AttributeError: module ... has no attribute 'day_fraction'"

- [ ] **Step 2.3: 实现**

Append to `attendance_service.py`:

```python
STANDARD_HOURS = 10.5


def _parse_hm(hm: str) -> int:
    """HH:MM -> 分钟总数"""
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def day_fraction(start: str, end: str) -> float:
    start_min = _parse_hm(start)
    end_min = _parse_hm(end)
    if end_min <= start_min:
        raise ValueError(f"下班时间必须晚于上班时间：start={start} end={end}")
    hours = (end_min - start_min) / 60
    return min(hours / STANDARD_HOURS, 1.0)
```

- [ ] **Step 2.4: 运行通过**

Run: `python -m pytest tests/test_attendance_service.py::TestDayFraction -v`
Expected: 5 passed

- [ ] **Step 2.5: Commit**

```bash
git add attendance_service.py tests/test_attendance_service.py
git commit -m "feat: attendance_service day_fraction 纯函数 + 单测"
```

---

## Task 3: 月度 CRUD（set_day / clear_day / 读取）

**Files:**
- Modify: `attendance_service.py` (append)
- Test: `tests/test_attendance_service.py` (append)

- [ ] **Step 3.1: 追加测试**

Append to `tests/test_attendance_service.py`:

```python
class TestDayCrud(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._ATTENDANCE_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_set_day_creates_entry(self):
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        data = svc.load_month("2026-04")
        self.assertEqual(data["e001"]["2026-04-01"], {"start": "09:30", "end": "20:00"})

    def test_set_day_overwrites_existing(self):
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        svc.set_day("e001", "2026-04-01", {"start": "10:00", "end": "18:00"})
        data = svc.load_month("2026-04")
        self.assertEqual(data["e001"]["2026-04-01"]["start"], "10:00")

    def test_clear_day_removes_entry(self):
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        svc.clear_day("e001", "2026-04-01")
        data = svc.load_month("2026-04")
        self.assertNotIn("2026-04-01", data.get("e001", {}))

    def test_load_empty_month(self):
        self.assertEqual(svc.load_month("2099-01"), {})
```

- [ ] **Step 3.2: 运行失败**

Run: `python -m pytest tests/test_attendance_service.py::TestDayCrud -v`
Expected: FAIL with "AttributeError: ... set_day"

- [ ] **Step 3.3: 实现**

Append to `attendance_service.py`:

```python
def _month_path(month: str) -> Path:
    return _ATTENDANCE_DIR / f"{month}.json"


def load_month(month: str) -> dict:
    return _read_json(_month_path(month), {})


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
```

- [ ] **Step 3.4: 运行通过**

Run: `python -m pytest tests/test_attendance_service.py::TestDayCrud -v`
Expected: 4 passed

- [ ] **Step 3.5: Commit**

```bash
git add attendance_service.py tests/test_attendance_service.py
git commit -m "feat: attendance_service 月度 CRUD（set_day/clear_day/load_month）"
```

---

## Task 4: compute_summary（含周日自动、缺勤推断）

**Files:**
- Modify: `attendance_service.py` (append)
- Test: `tests/test_attendance_service.py` (append)

- [ ] **Step 4.1: 追加测试**

Append to `tests/test_attendance_service.py`:

```python
class TestComputeSummary(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._ATTENDANCE_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_sunday_auto_one(self):
        # 2026-04 有 4 个周日: 5, 12, 19, 26
        result = svc.compute_summary("e001", "2026-04")
        sunday_rows = [d for d in result["detail"] if d["status"] == "sunday"]
        self.assertEqual(len(sunday_rows), 4)
        self.assertTrue(all(r["day_fraction"] == 1.0 for r in sunday_rows))

    def test_all_absent_when_no_records(self):
        result = svc.compute_summary("e001", "2026-04")
        # 30 天 - 4 周日 = 26 缺勤
        self.assertEqual(result["absent_days"], 26)
        self.assertEqual(result["worked_days"], 4.0)  # 4 周日

    def test_normal_day_records(self):
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        svc.set_day("e001", "2026-04-03", {"start": "09:30", "end": "15:30"})
        result = svc.compute_summary("e001", "2026-04")
        # 4 周日 + 1.0 + 0.571 = 5.571
        self.assertAlmostEqual(result["worked_days"], 4.0 + 1.0 + 6.0 / 10.5, places=3)
        # 30 天 - 4 周日 - 2 已录 = 24 缺勤
        self.assertEqual(result["absent_days"], 24)

    def test_total_workdays_excludes_absent(self):
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        result = svc.compute_summary("e001", "2026-04")
        # 30 - 24 缺勤 = 6
        self.assertEqual(result["total_workdays"], 30 - result["absent_days"])

    def test_detail_contains_all_days(self):
        result = svc.compute_summary("e001", "2026-04")
        self.assertEqual(len(result["detail"]), 30)
```

- [ ] **Step 4.2: 运行失败**

Run: `python -m pytest tests/test_attendance_service.py::TestComputeSummary -v`
Expected: FAIL with "AttributeError: ... compute_summary"

- [ ] **Step 4.3: 实现**

Append to `attendance_service.py`:

```python
from calendar import monthrange
from datetime import date as date_cls

_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def _iter_month_days(month: str):
    """yields (date_str, weekday_int, weekday_cn) for each day in YYYY-MM."""
    year, mon = int(month[:4]), int(month[5:7])
    _, days = monthrange(year, mon)
    for d in range(1, days + 1):
        dt = date_cls(year, mon, d)
        yield dt.isoformat(), dt.weekday(), _WEEKDAY_CN[dt.weekday()]


def compute_summary(employee_id: str, month: str) -> dict:
    month_data = load_month(month).get(employee_id, {})
    detail = []
    worked_days = 0.0
    absent_days = 0
    for date_str, wd_int, wd_cn in _iter_month_days(month):
        if wd_int == 6:  # Sunday
            detail.append({
                "date": date_str, "weekday": wd_cn,
                "start": "", "end": "",
                "day_fraction": 1.0, "status": "sunday",
            })
            worked_days += 1.0
            continue
        rec = month_data.get(date_str)
        if rec:
            frac = day_fraction(rec["start"], rec["end"])
            detail.append({
                "date": date_str, "weekday": wd_cn,
                "start": rec["start"], "end": rec["end"],
                "day_fraction": round(frac, 3), "status": "normal",
            })
            worked_days += frac
        else:
            detail.append({
                "date": date_str, "weekday": wd_cn,
                "start": "", "end": "",
                "day_fraction": 0.0, "status": "absent",
            })
            absent_days += 1
    total_days = len(detail)
    return {
        "worked_days": round(worked_days, 2),
        "absent_days": absent_days,
        "total_workdays": total_days - absent_days,
        "detail": detail,
    }
```

- [ ] **Step 4.4: 运行通过**

Run: `python -m pytest tests/test_attendance_service.py::TestComputeSummary -v`
Expected: 5 passed

- [ ] **Step 4.5: 运行全部测试**

Run: `python -m pytest tests/test_attendance_service.py -v`
Expected: 19 passed

- [ ] **Step 4.6: Commit**

```bash
git add attendance_service.py tests/test_attendance_service.py
git commit -m "feat: attendance_service compute_summary（周日自动 + 缺勤推断）"
```

---

## Task 5: attendance_report_service — CSV（TDD）

**Files:**
- Create: `attendance_report_service.py`
- Create: `tests/test_attendance_report_service.py`

- [ ] **Step 5.1: 写测试**

Create `tests/test_attendance_report_service.py`:

```python
import shutil
import unittest
from pathlib import Path

import attendance_service as svc
import attendance_report_service as rpt

_TEST_DIR = Path(__file__).resolve().parent / "_test_attendance_rpt"


class TestBuildCsv(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._ATTENDANCE_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_csv_has_utf8_bom(self):
        svc.create_employee("小王")
        data = rpt.build_csv("2026-04")
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))

    def test_csv_contains_employee_name(self):
        svc.create_employee("小王")
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        data = rpt.build_csv("2026-04")
        text = data.decode("utf-8-sig")
        self.assertIn("小王", text)
        self.assertIn("2026-04-01", text)

    def test_empty_month_returns_header_only(self):
        data = rpt.build_csv("2099-01")
        text = data.decode("utf-8-sig")
        lines = [l for l in text.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)  # header only
```

- [ ] **Step 5.2: 运行失败**

Run: `python -m pytest tests/test_attendance_report_service.py -v`
Expected: FAIL with "No module named attendance_report_service"

- [ ] **Step 5.3: 实现**

Create `attendance_report_service.py`:

```python
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
```

- [ ] **Step 5.4: 运行通过**

Run: `python -m pytest tests/test_attendance_report_service.py -v`
Expected: 3 passed

- [ ] **Step 5.5: Commit**

```bash
git add attendance_report_service.py tests/test_attendance_report_service.py
git commit -m "feat: attendance_report_service build_csv + 单测"
```

---

## Task 6: attendance_report_service — PDF（冒烟测试）

**Files:**
- Modify: `attendance_report_service.py` (append)
- Modify: `tests/test_attendance_report_service.py` (append)

- [ ] **Step 6.1: 追加冒烟测试**

Append to `tests/test_attendance_report_service.py`:

```python
class TestBuildPdf(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._ATTENDANCE_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_pdf_returns_non_empty_bytes(self):
        svc.create_employee("小王")
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        data = rpt.build_pdf("2026-04")
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 100)
        self.assertTrue(data.startswith(b"%PDF"))

    def test_pdf_empty_month_still_works(self):
        data = rpt.build_pdf("2099-01")
        self.assertTrue(data.startswith(b"%PDF"))
```

- [ ] **Step 6.2: 运行失败**

Run: `python -m pytest tests/test_attendance_report_service.py::TestBuildPdf -v`
Expected: FAIL with "AttributeError: ... build_pdf"

- [ ] **Step 6.3: 实现**

Append to `attendance_report_service.py`:

```python
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_NAME = "AttnSC"
_FONT_REGISTERED = False
_FONT_CANDIDATES = [
    Path(__file__).resolve().parent / "static" / "fonts" / "NotoSansSC-Regular.ttf",
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
]


def _register_font() -> None:
    global _FONT_REGISTERED, _FONT_NAME
    if _FONT_REGISTERED:
        return
    for fp in _FONT_CANDIDATES:
        if fp.exists():
            try:
                pdfmetrics.registerFont(TTFont(_FONT_NAME, str(fp)))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue
    _FONT_NAME = "Helvetica"
    _FONT_REGISTERED = True


_PDF_TABLE_HEADER = ["日期", "星期", "上班", "下班", "天数", "状态"]


def _build_employee_block(emp: dict, summary: dict) -> list:
    styles = getSampleStyleSheet()
    title = styles["Heading2"].clone("attn_h2")
    title.fontName = _FONT_NAME
    normal = styles["Normal"].clone("attn_n")
    normal.fontName = _FONT_NAME

    header = Paragraph(
        f"{emp['name']} — 累计 {summary['worked_days']} 天 / 缺勤 {summary['absent_days']} 天 / 总工作日 {summary['total_workdays']}",
        title,
    )
    rows = [_PDF_TABLE_HEADER]
    for r in summary["detail"]:
        rows.append([
            r["date"], r["weekday"], r["start"] or "—", r["end"] or "—",
            f"{r['day_fraction']:.2f}", r["status"],
        ])
    table = Table(rows, colWidths=[28 * mm, 14 * mm, 20 * mm, 20 * mm, 16 * mm, 20 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
    ]))
    return [header, Spacer(1, 4 * mm), table, Spacer(1, 10 * mm)]


def build_pdf(month: str) -> bytes:
    _register_font()
    employees = attendance_service.list_employees()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("attn_title")
    title_style.fontName = _FONT_NAME
    elements.append(Paragraph(f"{month} 月度考勤报表", title_style))
    elements.append(Spacer(1, 8 * mm))

    if not employees:
        normal = styles["Normal"].clone("attn_empty")
        normal.fontName = _FONT_NAME
        elements.append(Paragraph("暂无员工", normal))
    else:
        for emp in employees:
            summary = attendance_service.compute_summary(emp["id"], month)
            elements.append(KeepTogether(_build_employee_block(emp, summary)))

    doc.build(elements)
    return buf.getvalue()
```

- [ ] **Step 6.4: 运行通过**

Run: `python -m pytest tests/test_attendance_report_service.py -v`
Expected: 5 passed

- [ ] **Step 6.5: Commit**

```bash
git add attendance_report_service.py tests/test_attendance_report_service.py
git commit -m "feat: attendance_report_service build_pdf + 冒烟测试"
```

---

## Task 7: routes_attendance blueprint

**Files:**
- Create: `routes_attendance.py`

- [ ] **Step 7.1: 创建 blueprint**

Create `routes_attendance.py`:

```python
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
```

- [ ] **Step 7.2: 验证可导入**

Run: `python -c "from routes_attendance import bp; print(bp.name, len(list(bp.deferred_functions)))"`
Expected: `attendance <number>`

- [ ] **Step 7.3: Commit**

```bash
git add routes_attendance.py
git commit -m "feat: routes_attendance blueprint（员工 + 月度 + PDF + CSV）"
```

---

## Task 8: 注册 blueprint

**Files:**
- Modify: `routes.py`

- [ ] **Step 8.1: 修改 routes.py**

Edit `routes.py` — add import and register:

```python
from routes_attendance import bp as attendance_bp
from routes_monthly_summary import bp as monthly_summary_bp
from routes_pages_tasks import bp as pages_tasks_bp
from routes_purchase import bp as purchase_bp
from routes_query import bp as query_bp

from config import CONFIG


def register_routes(app) -> None:
    app.register_blueprint(pages_tasks_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(purchase_bp)
    app.register_blueprint(monthly_summary_bp)
    app.register_blueprint(attendance_bp)
    if CONFIG.dual_mode:
        from routes_transfer import bp as transfer_bp
        from routes_collab import bp as collab_bp
        app.register_blueprint(transfer_bp)
        app.register_blueprint(collab_bp)
```

- [ ] **Step 8.2: 验证路由注册**

Run:
```bash
python -c "from server import app; print('\n'.join(str(r) for r in app.url_map.iter_rules() if 'attendance' in str(r)))"
```
Expected: 输出 8 条 `/attendance/...` 路由

- [ ] **Step 8.3: Commit**

```bash
git add routes.py
git commit -m "feat: 注册 attendance blueprint"
```

---

## Task 9: 前端 HTML 挂载点 + 样式

**Files:**
- Modify: `templates/index.html:13`（nav 加一项）
- Modify: `templates/index.html:40`（page 加 div）
- Modify: `templates/index.html`（底部加 script）
- Modify: `templates/index.html:8`（head 加 css）
- Create: `static/css/attendance.css`

- [ ] **Step 9.1: index.html 加 css**

Edit `templates/index.html:8` (add after purchase.css):

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/purchase.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/attendance.css') }}">
```

- [ ] **Step 9.2: index.html 加 nav 项**

Edit `templates/index.html:13` — 末尾追加一个 nav-item：

```html
<div class="nav" id="nav"><div class="nav-item active" id="navMain" onclick="switchPage('main')">标签处理</div><div class="nav-item" id="navDup" onclick="switchPage('dup')">重复检查</div><div class="nav-item" id="navPurchase" onclick="switchPage('purchase')">采购订单</div><div class="nav-item" id="navAttendance" onclick="switchPage('attendance')">考勤</div></div>
```

- [ ] **Step 9.3: index.html 加 page 容器**

Edit `templates/index.html`，在 `<div class="page" id="pagePurchase"></div>` 下一行添加：

```html
<div class="page" id="pagePurchase"></div>
<div class="page" id="pageAttendance"></div>
```

- [ ] **Step 9.4: index.html 引入 JS**

在文件末尾现有的 `<script src=".../purchase.js"></script>` 之后加一行：

```html
<script src="{{ url_for('static', filename='js/attendance.js') }}"></script>
```

（如果现有是 `type="module"` 则保持一致）

- [ ] **Step 9.5: 创建 attendance.css**

Create `static/css/attendance.css`:

```css
.attn-wrap{display:flex;flex-direction:column;gap:12px;padding:16px;overflow:auto}
.attn-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.attn-top label{color:#94a3b8;font-size:13px}
.attn-inp{padding:4px 8px;border-radius:4px;border:1px solid #334155;background:#0f172a;color:#e2e8f0}
.attn-btn{padding:5px 12px;border-radius:4px;border:1px solid #334155;background:#1e293b;color:#e2e8f0;cursor:pointer;font-size:13px}
.attn-btn:hover{background:#334155}
.attn-btn-danger{border-color:#b91c1c;color:#fca5a5}
.attn-btn-dl{background:#4f46e5;border-color:#4f46e5;color:#fff}
.attn-stats{display:flex;gap:20px;color:#e2e8f0;font-size:14px;padding:8px 12px;background:#1e293b;border-radius:6px}
.attn-stats span{display:flex;gap:6px}
.attn-stats b{color:#4ade80}
.attn-grid{width:100%;border-collapse:collapse;color:#e2e8f0;font-size:13px}
.attn-grid th,.attn-grid td{padding:5px 8px;border:1px solid #334155;text-align:center}
.attn-grid th{background:#1e293b;font-weight:600}
.attn-grid td input[type=time]{background:transparent;border:1px solid #334155;color:#e2e8f0;padding:2px 4px;border-radius:3px}
.attn-grid tr.sunday td{background:#1e1b4b;color:#a5b4fc}
.attn-grid tr.absent td{background:#1a0f0f;color:#fca5a5}
.attn-grid .attn-status{font-size:12px}
```

- [ ] **Step 9.6: 验证**

刷新浏览器，点击"考勤"导航项，应该切到空白 `pageAttendance`，无报错。

- [ ] **Step 9.7: Commit**

```bash
git add templates/index.html static/css/attendance.css
git commit -m "feat: 前端 index.html 挂载 pageAttendance + attendance.css"
```

---

## Task 10: 前端 attendance.js — 骨架与员工下拉

**Files:**
- Create: `static/js/attendance.js`

- [ ] **Step 10.1: 创建骨架**

Create `static/js/attendance.js`:

```javascript
(function () {
  let employees = [];
  let currentEmployeeId = '';
  let currentMonth = '';
  let currentSummary = null;

  function init() {
    const page = document.getElementById('pageAttendance');
    if (!page) return;
    page.innerHTML = `
      <div class="attn-wrap">
        <div class="attn-top">
          <label>月份 <input class="attn-inp" id="attnMonth" type="month"></label>
          <label>员工 <select class="attn-inp" id="attnEmployee"></select></label>
          <button class="attn-btn" id="attnEmpNew">+ 新建</button>
          <button class="attn-btn attn-btn-danger" id="attnEmpDel">删除员工</button>
          <button class="attn-btn attn-btn-dl" id="attnPdf">下载 PDF</button>
          <button class="attn-btn attn-btn-dl" id="attnCsv">下载 CSV</button>
        </div>
        <div class="attn-stats">
          <span>累计 <b id="attnWorked">0</b> 天</span>
          <span>缺勤 <b id="attnAbsent">0</b> 天</span>
          <span>总工作日 <b id="attnTotal">0</b></span>
        </div>
        <div id="attnGridWrap"></div>
      </div>`;

    document.getElementById('attnEmpNew').addEventListener('click', createEmployee);
    document.getElementById('attnEmpDel').addEventListener('click', deleteEmployee);
    document.getElementById('attnEmployee').addEventListener('change', onEmployeeChange);
    document.getElementById('attnMonth').addEventListener('change', onMonthChange);
    document.getElementById('attnPdf').addEventListener('click', downloadPdf);
    document.getElementById('attnCsv').addEventListener('click', downloadCsv);

    document.getElementById('attnMonth').value = new Date().toISOString().slice(0, 7);
    currentMonth = document.getElementById('attnMonth').value;
    loadEmployees();
  }

  async function loadEmployees() {
    try {
      const res = await fetch('/attendance/employees');
      const body = await res.json();
      employees = body.employees || [];
    } catch (e) {
      employees = [];
    }
    renderEmployeeSelect();
    if (employees.length && !currentEmployeeId) {
      currentEmployeeId = employees[0].id;
      document.getElementById('attnEmployee').value = currentEmployeeId;
    }
    loadMonth();
  }

  function renderEmployeeSelect() {
    const sel = document.getElementById('attnEmployee');
    sel.innerHTML = employees.map(e => `<option value="${e.id}">${escapeHtml(e.name)}</option>`).join('');
    if (currentEmployeeId) sel.value = currentEmployeeId;
  }

  async function createEmployee() {
    const name = prompt('新员工姓名：');
    if (!name || !name.trim()) return;
    try {
      const res = await fetch('/attendance/employees', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
      currentEmployeeId = body.employee.id;
      await loadEmployees();
    } catch (e) { alert('新建失败：' + e.message); }
  }

  async function deleteEmployee() {
    if (!currentEmployeeId) return;
    const emp = employees.find(e => e.id === currentEmployeeId);
    if (!emp) return;
    if (!confirm(`删除员工 ${emp.name}？历史考勤数据保留但不再显示。`)) return;
    try {
      const res = await fetch(`/attendance/employees/${currentEmployeeId}`, { method: 'DELETE' });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
      currentEmployeeId = '';
      await loadEmployees();
    } catch (e) { alert('删除失败：' + e.message); }
  }

  function onEmployeeChange(e) {
    currentEmployeeId = e.target.value;
    loadMonth();
  }

  function onMonthChange(e) {
    currentMonth = e.target.value;
    loadMonth();
  }

  async function loadMonth() {
    const wrap = document.getElementById('attnGridWrap');
    if (!currentEmployeeId || !currentMonth) {
      wrap.innerHTML = '<div style="color:#64748b;padding:20px;">请先选择员工和月份</div>';
      updateStats(null);
      return;
    }
    try {
      const res = await fetch(`/attendance/month/${currentEmployeeId}/${currentMonth}`);
      const body = await res.json();
      if (!body.ok) { wrap.innerHTML = `<div style="color:#fca5a5;">${body.msg}</div>`; return; }
      currentSummary = body;
      renderGrid(body.detail);
      updateStats(body);
    } catch (e) { wrap.innerHTML = `<div style="color:#fca5a5;">加载失败：${e.message}</div>`; }
  }

  function renderGrid(detail) {
    const wrap = document.getElementById('attnGridWrap');
    const rows = detail.map(r => {
      const cls = r.status === 'sunday' ? 'sunday' : (r.status === 'absent' ? 'absent' : '');
      const startCell = r.status === 'sunday'
        ? '<td colspan="2">自动（周日）</td>'
        : `<td><input type="time" data-date="${r.date}" data-field="start" value="${r.start}"></td>
           <td><input type="time" data-date="${r.date}" data-field="end" value="${r.end}"></td>`;
      const statusText = r.status === 'sunday' ? '🔒' : (r.status === 'absent' ? '缺勤' : '✓');
      return `<tr class="${cls}" data-date="${r.date}">
        <td>${r.date.slice(5)}</td>
        <td>${r.weekday}</td>
        ${startCell}
        <td>${r.day_fraction.toFixed(2)}</td>
        <td class="attn-status">${statusText}</td>
      </tr>`;
    }).join('');
    wrap.innerHTML = `
      <table class="attn-grid">
        <thead><tr><th>日期</th><th>星期</th><th>上班</th><th>下班</th><th>天数</th><th>状态</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    wrap.querySelectorAll('input[type=time]').forEach(inp => {
      inp.addEventListener('change', () => onCellChange(inp.dataset.date));
    });
  }

  async function onCellChange(date) {
    const row = document.querySelector(`tr[data-date="${date}"]`);
    if (!row) return;
    const startInp = row.querySelector('input[data-field="start"]');
    const endInp = row.querySelector('input[data-field="end"]');
    const start = startInp ? startInp.value : '';
    const end = endInp ? endInp.value : '';
    if (!start && !end) {
      await fetch(`/attendance/day/${currentEmployeeId}/${date}`, { method: 'DELETE' });
    } else if (start && end) {
      const res = await fetch(`/attendance/day/${currentEmployeeId}/${date}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start, end }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } else {
      return; // 只填了一半，不保存
    }
    await loadMonth();
  }

  function updateStats(summary) {
    document.getElementById('attnWorked').textContent = summary ? summary.worked_days : 0;
    document.getElementById('attnAbsent').textContent = summary ? summary.absent_days : 0;
    document.getElementById('attnTotal').textContent = summary ? summary.total_workdays : 0;
  }

  function downloadPdf() {
    if (!currentMonth) return;
    window.location.href = `/attendance/pdf/${currentMonth}`;
  }

  function downloadCsv() {
    if (!currentMonth) return;
    window.location.href = `/attendance/csv/${currentMonth}`;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  document.addEventListener('DOMContentLoaded', init);
})();
```

- [ ] **Step 10.2: 浏览器手工测试**

1. 重启 `server.py`，Ctrl+F5 刷新
2. 点击"考勤"导航 → 月份自动填当前月
3. 点"+ 新建" → 输入名字 → 员工下拉出现
4. 看到 30 行表格，周日灰底显示"自动（周日）"，其他行初始为缺勤
5. 填一行上/下班时间 → change 触发保存 → 顶部累计天数更新
6. 清空一行时间 → 该天变回缺勤
7. 下载 PDF / CSV → 浏览器下载文件并能打开

若任一步骤失败，修复后重测。

- [ ] **Step 10.3: Commit**

```bash
git add static/js/attendance.js
git commit -m "feat: attendance.js 员工/月度/网格/保存/下载 全流程"
```

---

## Task 11: 更新日志

**Files:**
- Modify: `更新日志.md`

- [ ] **Step 11.1: 在文件顶部追加 v1.8 条目**

Edit `更新日志.md` — 在 `# 双端处理 更新日志` 下紧跟的 `---` 之后插入：

```markdown
## v1.8 — 2026-04-23

### 新增

- **员工月度考勤**：新增"考勤"导航页，按月网格录入每员工每日上下班时间，自动计算工作天数（标准 09:30–20:00 = 10.5h = 1.0 天，封顶 1.0），周日自动 1.0，非周日未录入视为缺勤
- **员工管理**：可新建 / 删除员工（id 自增 e001/e002，删除后 id 不复用，历史数据保留）
- **月度导出**：`GET /attendance/pdf/<month>` 和 `/attendance/csv/<month>` 下载全员月度报表（PDF 含中文字体；CSV 带 UTF-8 BOM 兼容 Excel）
- **后端模块**：`attendance_service.py`（员工/月度 CRUD + day_fraction + compute_summary）、`attendance_report_service.py`（PDF/CSV 生成）、`routes_attendance.py`（blueprint）

---
```

- [ ] **Step 11.2: Commit**

```bash
git add 更新日志.md
git commit -m "docs: 更新日志 v1.8 — 员工月度考勤"
```

---

## Task 12: 合入 main + push

- [ ] **Step 12.1: 全量回归**

Run: `python -m pytest tests/ -v`
Expected: 所有已有测试 + 新增考勤测试全部通过

- [ ] **Step 12.2: 路由验证**

Run:
```bash
python -c "from server import app; print([str(r) for r in app.url_map.iter_rules() if 'attendance' in str(r)])"
```
Expected: 8 条 `/attendance/...` 路由

- [ ] **Step 12.3: 合入 main**

```bash
git checkout main
git merge --no-ff feature/attendance -m "merge: feature/attendance 员工月度考勤"
git push origin main
```

- [ ] **Step 12.4: 手动烟雾测试**

1. 启动 `server.py`
2. 浏览器打开 A 端 → 考勤 tab
3. 新建一个员工 → 填几行时间 → 累计数字变化 → 下载 PDF（能打开）+ 下载 CSV（Excel 能识别中文不乱码）
