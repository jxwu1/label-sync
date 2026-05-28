# 企业微信考勤导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从企业微信「打卡时间记录」xlsx 解析并填写百货城工作组的月度考勤,首次绑定/忽略账号,之后按月自动导入。

**Architecture:** 纯解析层(无 DB)解析矩阵式 xlsx → 计划层(DB 只读)按账号绑定过滤、fill-blank-only 生成写入计划 → 路由三段(preview/bind/ignore/apply)→ 考勤页弹窗。账号 `wecom_account` 是后台 join key,UI 只显示姓名。

**Tech Stack:** Python 3.12 + Flask + SQLAlchemy 2.x + openpyxl + Alembic;前端 vanilla JS(`static/js/attendance.js` IIFE,`fetch` + `alert`)。

参考 spec:`docs/superpowers/specs/2026-05-28-wecom-attendance-import-design.md`

---

## File Structure

- `app/models.py` — `Employee` 加 `wecom_account` 列(修改)
- `alembic/versions/<new>_add_employee_wecom_account.py` — 迁移(新建)
- `app/services/attendance_import.py` — 解析层 + 绑定/忽略 + 计划层 + apply(新建)
- `app/routes/attendance.py` — 加 `/attendance/import/*` 四个路由(修改)
- `tests/test_attendance_import.py` — 解析 + 计划 + 服务单测(新建)
- `tests/test_attendance_import_routes.py` — 路由集成测(新建)
- `static/js/attendance.js` — 导入按钮 + 弹窗 + 三段交互(修改)
- `templates/index.html` — 无需改(按钮由 JS 注入工具栏)

---

## Task 1: 加 `wecom_account` 列 + 迁移

**Files:**
- Modify: `app/models.py:559-571`(Employee 类)
- Create: `alembic/versions/wecom_acct_0001_add_employee_wecom_account.py`
- Test: `tests/test_attendance_import.py`

- [ ] **Step 1: Write the failing test**

新建 `tests/test_attendance_import.py`:

```python
"""企业微信考勤导入：解析层 + 服务 + 计划层单测。"""
import unittest
from unittest import mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Employee


def _make_memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.cursor().execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, Session


class WecomAccountColumnTests(unittest.TestCase):
    def test_employee_has_wecom_account(self):
        engine, Session = _make_memory_db()
        with Session() as s:
            s.add(Employee(employee_id="e001", name="张三", wecom_account="ZhangSan"))
            s.commit()
        with Session() as s:
            emp = s.get(Employee, "e001")
            self.assertEqual(emp.wecom_account, "ZhangSan")
        engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_attendance_import.py::WecomAccountColumnTests -v`
Expected: FAIL — `TypeError: 'wecom_account' is an invalid keyword argument for Employee`

- [ ] **Step 3: Add the column to the model**

`app/models.py`,在 `Employee` 类 `notes` 字段后加一行:

```python
    notes: Mapped[str | None] = mapped_column(Text)
    wecom_account: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_attendance_import.py::WecomAccountColumnTests -v`
Expected: PASS

- [ ] **Step 5: Create the Alembic migration**

新建 `alembic/versions/wecom_acct_0001_add_employee_wecom_account.py`:

```python
"""add employee.wecom_account

Revision ID: wecom_acct_0001
Revises: cb40fb302571
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "wecom_acct_0001"
down_revision = "cb40fb302571"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("wecom_account", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "wecom_account")
```

- [ ] **Step 6: Apply migration and verify**

Run: `python -m alembic upgrade head && python -m alembic current`
Expected: 输出含 `wecom_acct_0001 (head)`,无报错。

- [ ] **Step 7: Commit**

```bash
git add app/models.py alembic/versions/wecom_acct_0001_add_employee_wecom_account.py tests/test_attendance_import.py
git commit -m "feat(attendance): Employee 加 wecom_account 列 + 迁移"
```

---

## Task 2: 解析层 `parse_cell` / `parse_workbook`

**Files:**
- Create: `app/services/attendance_import.py`
- Test: `tests/test_attendance_import.py`

- [ ] **Step 1: Write failing tests for `parse_cell`**

在 `tests/test_attendance_import.py` 顶部 import 加 `from app.services import attendance_import as imp`,并新增:

```python
class ParseCellTests(unittest.TestCase):
    def test_in_out(self):
        self.assertEqual(imp.parse_cell("09:21、20:00"), ("ok", "09:21", "20:00"))

    def test_dedupe_takes_min_max(self):
        self.assertEqual(imp.parse_cell("09:22、09:22、20:00"), ("ok", "09:22", "20:00"))

    def test_strips_annotation(self):
        self.assertEqual(imp.parse_cell("09:21、20:00(管理员校准)"), ("ok", "09:21", "20:00"))

    def test_dash_is_empty(self):
        self.assertEqual(imp.parse_cell("--"), ("empty",))

    def test_none_is_empty(self):
        self.assertEqual(imp.parse_cell(None), ("empty",))

    def test_single_punch(self):
        self.assertEqual(imp.parse_cell("09:40"), ("single", "09:40"))

    def test_normalizes_single_digit_hour(self):
        self.assertEqual(imp.parse_cell("9:21、20:00"), ("ok", "09:21", "20:00"))
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_attendance_import.py::ParseCellTests -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: parse_cell`

- [ ] **Step 3: Implement parse layer**

新建 `app/services/attendance_import.py`:

```python
"""企业微信「打卡时间记录」xlsx 解析 + 考勤导入计划。

解析层为纯函数(无 DB);计划层只读 DB,核心逻辑 _build_plan_core 接受注入数据以便测试。
"""
import json
import re
from io import BytesIO

import openpyxl
from sqlalchemy import select, update

from app.models import Employee, SystemSetting, get_session
from app.services import attendance as attendance_service

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_PAREN_RE = re.compile(r"[(（][^)）]*[)）]")
_SPLIT_RE = re.compile(r"[、,，]")
_DAY_HEADER_RE = re.compile(r"^(\d{1,2})")
_FILENAME_DATE_RE = re.compile(r"(\d{4})(\d{2})\d{2}")

_HEADER_ROW = 3  # 0-based:列头在第 4 行
_NAME_COL = 0
_ACCOUNT_COL = 1


def parse_cell(text):
    """单元格 → ('ok', start, end) | ('single', t) | ('empty',)。

    去注释 → 按 、/, 拆 → 抓 HH:MM → 去重排序;0 个 empty,1 个 single,≥2 个 min/max。
    """
    if text is None:
        return ("empty",)
    s = str(text).strip()
    if not s or s == "--":
        return ("empty",)
    s = _PAREN_RE.sub("", s)
    times = []
    for tok in _SPLIT_RE.split(s):
        m = _TIME_RE.search(tok)
        if m:
            times.append(f"{int(m.group(1)):02d}:{int(m.group(2)):02d}")
    uniq = sorted(set(times))
    if not uniq:
        return ("empty",)
    if len(uniq) == 1:
        return ("single", uniq[0])
    return ("ok", uniq[0], uniq[-1])


def detect_month(filename):
    """从文件名 (..._20260501-...) 推 'YYYY-MM';推不出返回 None。"""
    if not filename:
        return None
    m = _FILENAME_DATE_RE.search(filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def parse_workbook(xlsx_bytes, filename=""):
    """xlsx bytes → {'detected_month': 'YYYY-MM'|None, 'rows': [...]}。

    每行:{'account', 'name', 'days': {day_int: ('ok',s,e)|('single',t)}}。
    days 只含非空单元格;不计算日期(留给计划层按确认月份算)。
    """
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    grid = list(ws.iter_rows(values_only=True))
    header = grid[_HEADER_ROW] if len(grid) > _HEADER_ROW else ()
    day_cols = {}
    for ci, cell in enumerate(header):
        if cell is None:
            continue
        txt = str(cell).strip()
        if "星期" in txt:
            m = _DAY_HEADER_RE.match(txt)
            if m:
                day_cols[ci] = int(m.group(1))
    rows = []
    for r in grid[_HEADER_ROW + 1:]:
        if not r:
            continue
        account = str(r[_ACCOUNT_COL]).strip() if len(r) > _ACCOUNT_COL and r[_ACCOUNT_COL] is not None else ""
        if not account:
            continue
        name = str(r[_NAME_COL]).strip() if len(r) > _NAME_COL and r[_NAME_COL] is not None else ""
        days = {}
        for ci, day in day_cols.items():
            parsed = parse_cell(r[ci] if ci < len(r) else None)
            if parsed[0] != "empty":
                days[day] = parsed
        rows.append({"account": account, "name": name, "days": days})
    wb.close()
    return {"detected_month": detect_month(filename), "rows": rows}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_attendance_import.py::ParseCellTests -v`
Expected: PASS

- [ ] **Step 5: Add `parse_workbook` test against the real file**

```python
import os

_REAL_FILE = r"C:\Users\64474\Downloads\上下班打卡_打卡时间记录_20260501-20260527.xlsx"


class ParseWorkbookTests(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(_REAL_FILE), "需要真实导出文件")
    def test_parses_real_file(self):
        with open(_REAL_FILE, "rb") as f:
            data = f.read()
        out = imp.parse_workbook(data, os.path.basename(_REAL_FILE))
        self.assertEqual(out["detected_month"], "2026-05")
        accts = {row["account"]: row for row in out["rows"]}
        self.assertIn("WengFuYuan", accts)
        # 翁福源 2 号(周六)单元格 "09:29、20:03" → ok
        self.assertEqual(accts["WengFuYuan"]["days"][2], ("ok", "09:29", "20:03"))
```

- [ ] **Step 6: Run to verify pass**

Run: `pytest tests/test_attendance_import.py::ParseWorkbookTests -v`
Expected: PASS(若本机无文件则 SKIP)

- [ ] **Step 7: Commit**

```bash
git add app/services/attendance_import.py tests/test_attendance_import.py
git commit -m "feat(attendance): 企业微信 xlsx 解析层 parse_cell/parse_workbook"
```

---

## Task 3: 账号绑定 / 忽略服务

**Files:**
- Modify: `app/services/attendance_import.py`(追加)
- Test: `tests/test_attendance_import.py`

- [ ] **Step 1: Write failing tests**

```python
import app.models as models_mod


class BindIgnoreTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.Session = _make_memory_db()
        self.p1 = mock.patch.object(models_mod, "_engine", self.engine)
        self.p2 = mock.patch.object(models_mod, "_SessionFactory", self.Session)
        self.p1.start(); self.p2.start()
        with self.Session() as s:
            s.add(Employee(employee_id="e001", name="翁福源"))
            s.add(Employee(employee_id="e002", name="陈建华"))
            s.commit()

    def tearDown(self):
        self.p2.stop(); self.p1.stop()
        Base.metadata.drop_all(self.engine); self.engine.dispose()

    def test_bind_then_map(self):
        imp.bind_account("WengFuYuan", "e001")
        self.assertEqual(imp.get_account_map(), {"WengFuYuan": "e001"})

    def test_bind_is_one_to_one(self):
        imp.bind_account("WengFuYuan", "e001")
        imp.bind_account("WengFuYuan", "e002")  # 改绑到 e002
        self.assertEqual(imp.get_account_map(), {"WengFuYuan": "e002"})

    def test_bind_unknown_employee_raises(self):
        with self.assertRaises(ValueError):
            imp.bind_account("X", "e999")

    def test_ignore_list_roundtrip(self):
        imp.ignore_account("ZhangYuePing")
        imp.ignore_account("ChenRong")
        self.assertEqual(imp.list_ignored(), {"ZhangYuePing", "ChenRong"})
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_attendance_import.py::BindIgnoreTests -v`
Expected: FAIL — `AttributeError: ... bind_account`

- [ ] **Step 3: Implement bind/ignore helpers**

追加到 `app/services/attendance_import.py`:

```python
_IGNORE_KEY = "wecom_ignored_accounts"


def get_account_map():
    """account -> employee_id(仅取已设 wecom_account 的员工)。"""
    with get_session() as s:
        rows = s.execute(
            select(Employee.wecom_account, Employee.employee_id).where(
                Employee.wecom_account.isnot(None)
            )
        ).all()
    return {acc: eid for acc, eid in rows if acc}


def bind_account(account, employee_id):
    """把账号绑到员工(1:1:先把该账号从其他员工清掉)。员工不存在 → ValueError。"""
    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp:
            raise ValueError(f"员工不存在：{employee_id}")
        s.execute(
            update(Employee)
            .where(Employee.wecom_account == account)
            .values(wecom_account=None)
        )
        emp.wecom_account = account


def list_ignored():
    """忽略账号集合(存在 SystemSetting 的 JSON list)。"""
    with get_session() as s:
        st = s.get(SystemSetting, _IGNORE_KEY)
        if not st or not st.value:
            return set()
        try:
            return set(json.loads(st.value))
        except (ValueError, TypeError):
            return set()


def ignore_account(account):
    """把账号加入忽略清单。"""
    accs = list_ignored()
    accs.add(account)
    payload = json.dumps(sorted(accs), ensure_ascii=False)
    with get_session() as s:
        st = s.get(SystemSetting, _IGNORE_KEY)
        if st:
            st.value = payload
        else:
            s.add(SystemSetting(key=_IGNORE_KEY, value=payload))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_attendance_import.py::BindIgnoreTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/attendance_import.py tests/test_attendance_import.py
git commit -m "feat(attendance): 账号绑定 + 忽略清单服务"
```

---

## Task 4: 计划层 `build_plan`

**Files:**
- Modify: `app/services/attendance_import.py`(追加)
- Test: `tests/test_attendance_import.py`

- [ ] **Step 1: Write failing tests for `_build_plan_core`**

```python
class BuildPlanCoreTests(unittest.TestCase):
    def test_matched_to_write_and_single(self):
        rows = [
            {"account": "WengFuYuan", "name": "翁福源",
             "days": {1: ("ok", "09:25", "20:00"), 2: ("single", "09:40")}},
            {"account": "ZhangYuePing", "name": "张月萍",
             "days": {1: ("ok", "09:29", "17:35")}},      # 已忽略
            {"account": "NewGuy", "name": "新人",
             "days": {1: ("ok", "09:30", "20:00")}},       # 未绑定,无重名建议
        ]
        plan = imp._build_plan_core(
            rows, "2026-05",
            account_map={"WengFuYuan": "e001"},
            ignored={"ZhangYuePing"},
            name_by_id={"e001": "翁福源"},
            month_data={},          # 无已有考勤
            leaves_by_emp={},
        )
        matched = {m["employee_id"]: m for m in plan["matched"]}
        self.assertEqual(matched["e001"]["to_write"],
                         [{"date": "2026-05-01", "start": "09:25", "end": "20:00"}])
        self.assertEqual(matched["e001"]["skip_single"], 1)
        self.assertNotIn("e002", matched)  # 张月萍 已忽略 → 不出现
        self.assertEqual(plan["needs_manual"],
                         [{"employee_id": "e001", "name": "翁福源", "date": "2026-05-02", "time": "09:40"}])
        self.assertEqual(plan["unbound"],
                         [{"account": "NewGuy", "name": "新人", "suggested_employee_id": None}])

    def test_fill_blank_only_skips_existing(self):
        plan = imp._build_plan_core(
            [{"account": "WengFuYuan", "name": "翁福源",
              "days": {1: ("ok", "09:25", "20:00"), 2: ("ok", "09:30", "20:00")}}],
            "2026-05",
            account_map={"WengFuYuan": "e001"},
            ignored=set(),
            name_by_id={"e001": "翁福源"},
            month_data={"e001": {"2026-05-01": {"start": "09:00", "end": "20:00"}}},  # 1 号已有
            leaves_by_emp={},
        )
        m = plan["matched"][0]
        self.assertEqual(m["to_write"], [{"date": "2026-05-02", "start": "09:30", "end": "20:00"}])
        self.assertEqual(m["skip_existing"], 1)

    def test_name_suggestion_when_unique(self):
        plan = imp._build_plan_core(
            [{"account": "abc", "name": "翁福源", "days": {}}],
            "2026-05",
            account_map={},
            ignored=set(),
            name_by_id={"e001": "翁福源"},
            month_data={}, leaves_by_emp={},
        )
        self.assertEqual(plan["unbound"][0]["suggested_employee_id"], "e001")
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_attendance_import.py::BuildPlanCoreTests -v`
Expected: FAIL — `AttributeError: _build_plan_core`

- [ ] **Step 3: Implement plan core + public wrappers**

追加到 `app/services/attendance_import.py`:

```python
def _build_plan_core(rows, month, *, account_map, ignored, name_by_id, month_data, leaves_by_emp):
    """纯计算计划核心。共享数据由调用方注入(便于测试)。"""
    # 姓名 -> employee_id 建议(仅唯一姓名才建议,重名留空)
    name_counts = {}
    for nm in name_by_id.values():
        name_counts[nm] = name_counts.get(nm, 0) + 1
    id_by_name = {nm: eid for eid, nm in name_by_id.items() if name_counts[nm] == 1}

    matched = []
    unbound = []
    needs_manual = []
    for row in rows:
        acc = row["account"]
        nm = row["name"]
        if acc in ignored:
            continue
        eid = account_map.get(acc)
        if not eid:
            unbound.append(
                {"account": acc, "name": nm, "suggested_employee_id": id_by_name.get(nm)}
            )
            continue
        disp = name_by_id.get(eid, nm)
        existing = month_data.get(eid, {})
        leaves = leaves_by_emp.get(eid, {})
        to_write = []
        skip_existing = 0
        skip_single = 0
        for day_int in sorted(row["days"]):
            parsed = row["days"][day_int]
            date = f"{month}-{day_int:02d}"
            if date in existing or date in leaves:
                skip_existing += 1
                continue
            if parsed[0] == "single":
                skip_single += 1
                needs_manual.append(
                    {"employee_id": eid, "name": disp, "date": date, "time": parsed[1]}
                )
                continue
            _, start, end = parsed
            if start >= end:  # 异常时段,转手动
                skip_single += 1
                needs_manual.append(
                    {"employee_id": eid, "name": disp, "date": date, "time": f"{start}-{end}"}
                )
                continue
            to_write.append({"date": date, "start": start, "end": end})
        matched.append(
            {
                "employee_id": eid,
                "name": disp,
                "to_write": to_write,
                "skip_existing": skip_existing,
                "skip_single": skip_single,
            }
        )
    return {
        "month": month,
        "matched": matched,
        "unbound": unbound,
        "needs_manual": needs_manual,
        "counts": {
            "matched": len(matched),
            "unbound": len(unbound),
            "needs_manual": len(needs_manual),
            "to_write": sum(len(m["to_write"]) for m in matched),
        },
    }


def build_plan(rows, month):
    """读 DB(绑定/忽略/已有考勤/请假)并产出导入计划。"""
    employees = attendance_service.list_employees()
    name_by_id = {e["id"]: e["name"] for e in employees}
    return _build_plan_core(
        rows,
        month,
        account_map=get_account_map(),
        ignored=list_ignored(),
        name_by_id=name_by_id,
        month_data=attendance_service.load_month(month),
        leaves_by_emp=attendance_service.list_leaves(month),
    )


def apply_plan(rows, month):
    """对计划里的 to_write 天调 set_day 写入。返回写入/跳过计数。"""
    plan = build_plan(rows, month)
    written = 0
    for m in plan["matched"]:
        for d in m["to_write"]:
            attendance_service.set_day(
                m["employee_id"], d["date"], {"start": d["start"], "end": d["end"]}
            )
            written += 1
    return {
        "written": written,
        "skipped_existing": sum(m["skip_existing"] for m in plan["matched"]),
        "skipped_single": sum(m["skip_single"] for m in plan["matched"]),
        "unbound": len(plan["unbound"]),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_attendance_import.py::BuildPlanCoreTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/attendance_import.py tests/test_attendance_import.py
git commit -m "feat(attendance): 导入计划层 build_plan/apply_plan"
```

---

## Task 5: 路由 preview / bind / ignore / apply

**Files:**
- Modify: `app/routes/attendance.py`(import + 4 个路由)
- Test: `tests/test_attendance_import_routes.py`

- [ ] **Step 1: Write failing integration test**

新建 `tests/test_attendance_import_routes.py`:

```python
"""企业微信导入路由集成测:preview→bind→ignore→apply。"""
import io
import unittest
from unittest import mock

import openpyxl
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as models_mod
from app.models import Base, Employee
from app.routes.attendance import bp


def _xlsx_bytes():
    """造一个最小「打卡时间记录」xlsx:1 个百货城人 + 1 个待绑定人。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "打卡时间记录"
    ws.append(["打卡时间记录"])
    ws.append(["统计时间:05-01 ～ 05-02"])
    ws.append(["姓名", "账号", "基础信息", "", "", "打卡时间记录"])
    ws.append(["", "", "部门", "职务", "工号", "1\n星期五", "2\n星期六"])
    ws.append(["翁福源", "WengFuYuan", "希腊销售部", "--", "--", "09:25、20:00", "09:40"])
    ws.append(["新人", "NewGuy", "希腊销售部", "--", "--", "09:30、20:00", "--"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class WecomImportRoutesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _fk(dbapi_conn, _):
            dbapi_conn.cursor().execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.p1 = mock.patch.object(models_mod, "_engine", self.engine)
        self.p2 = mock.patch.object(models_mod, "_SessionFactory", self.Session)
        self.p1.start(); self.p2.start()
        with self.Session() as s:
            s.add(Employee(employee_id="e001", name="翁福源"))
            s.commit()
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def tearDown(self):
        self.p2.stop(); self.p1.stop()
        Base.metadata.drop_all(self.engine); self.engine.dispose()

    def _upload(self, url, **form):
        data = {"file": (io.BytesIO(_xlsx_bytes()), "wecom_20260501-20260502.xlsx")}
        data.update(form)
        return self.client.post(url, data=data, content_type="multipart/form-data")

    def test_preview_lists_unbound_and_matched(self):
        rv = self._upload("/attendance/import/preview")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["month"], "2026-05")
        accs = {u["account"] for u in body["unbound"]}
        self.assertIn("WengFuYuan", accs)  # 未绑定
        self.assertIn("NewGuy", accs)

    def test_bind_then_preview_matches(self):
        self.client.post("/attendance/import/bind",
                         json={"account": "WengFuYuan", "employee_id": "e001"})
        body = self._upload("/attendance/import/preview").get_json()
        matched = {m["employee_id"] for m in body["matched"]}
        self.assertIn("e001", matched)

    def test_ignore_hides_account(self):
        self.client.post("/attendance/import/ignore", json={"account": "NewGuy"})
        body = self._upload("/attendance/import/preview").get_json()
        accs = {u["account"] for u in body["unbound"]}
        self.assertNotIn("NewGuy", accs)

    def test_apply_writes_only_ok_days(self):
        self.client.post("/attendance/import/bind",
                         json={"account": "WengFuYuan", "employee_id": "e001"})
        rv = self._upload("/attendance/import/apply", month="2026-05")
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["written"], 1)       # 1 号写入
        self.assertEqual(body["skipped_single"], 1) # 2 号单次跳过
        summ = self.client.get("/attendance/month/e001/2026-05").get_json()
        day1 = next(d for d in summ["detail"] if d["date"] == "2026-05-01")
        self.assertEqual(day1["start"], "09:25")
        self.assertEqual(day1["end"], "20:00")
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_attendance_import_routes.py -v`
Expected: FAIL — 404(路由不存在)

- [ ] **Step 3: Implement the routes**

`app/routes/attendance.py` 顶部 import 区:把 `from flask import Blueprint, jsonify, send_file` 改为补上 `request`,并追加 service import:

```python
from flask import Blueprint, jsonify, request, send_file
```
```python
from app.services import attendance_import as attendance_import_service
```

在 `_DayUpsert` 等 Pydantic 模型附近加两个 body 模型:

```python
class _BindUpsert(BaseModel):
    account: NonEmptyStr
    employee_id: NonEmptyStr


class _IgnoreUpsert(BaseModel):
    account: NonEmptyStr
```

在文件末尾(PDF 路由之后)追加四个路由:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_attendance_import_routes.py -v`
Expected: PASS(4 个用例全绿)

- [ ] **Step 5: Run full attendance suite for regressions**

Run: `pytest tests/test_attendance_import.py tests/test_attendance_import_routes.py tests/test_attendance_routes.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add app/routes/attendance.py tests/test_attendance_import_routes.py
git commit -m "feat(attendance): 企业微信导入路由 preview/bind/ignore/apply"
```

---

## Task 6: 前端导入弹窗

**Files:**
- Modify: `static/js/attendance.js`

> 说明:`attendance.js` 是 IIFE,UI 由 JS 注入 `#pageAttendance`。沿用现有 `fetch` + `alert` 风格(无 toast 库)。`employees` 是该 IIFE 顶部已有的模块级数组(`loadEmployees()` 填充),`loadMonth()` 是已有刷新函数。本任务无自动化测试,Step 5 是浏览器手动验证。

- [ ] **Step 1: 在工具栏加按钮**

`static/js/attendance.js` 的 `init()` 内,工具栏模板 `attn-top` 里(`attnLeaveRange` 按钮后)加一个:

```javascript
          <button class="attn-btn" id="attnLeaveRange">区间请假</button>
          <button class="attn-btn" id="attnWecomImport">导入企业微信</button>
```

- [ ] **Step 2: 绑定点击事件**

在 `init()` 里绑定其他工具栏按钮的地方(搜索 `attnFillAll` 的 `addEventListener`),加一行:

```javascript
    document.getElementById('attnWecomImport').addEventListener('click', openWecomImport);
```

- [ ] **Step 3: 实现弹窗 + 三段交互**

在 IIFE 内(其他 `async function` 旁,如 `importHolidaysYear` 附近)加入以下函数:

```javascript
  let _wecomFile = null;
  let _wecomMonth = '';

  function _wecomOverlay() {
    let ov = document.getElementById('wecomImportOverlay');
    if (ov) return ov;
    ov = document.createElement('div');
    ov.id = 'wecomImportOverlay';
    ov.className = 'attn-modal-overlay';
    ov.innerHTML = `
      <div class="attn-modal" style="max-width:680px">
        <div class="attn-modal-hd">
          <b>导入企业微信考勤</b>
          <button class="attn-btn" id="wecomClose">关闭</button>
        </div>
        <div class="attn-modal-bd" id="wecomBody">
          <p>选择企业微信导出的「打卡时间记录」xlsx：</p>
          <input type="file" id="wecomFileInput" accept=".xlsx">
        </div>
      </div>`;
    document.body.appendChild(ov);
    ov.addEventListener('click', (e) => { if (e.target === ov) ov.remove(); });
    ov.querySelector('#wecomClose').addEventListener('click', () => ov.remove());
    ov.querySelector('#wecomFileInput').addEventListener('change', _wecomOnFile);
    return ov;
  }

  function openWecomImport() {
    _wecomFile = null;
    _wecomMonth = '';
    const ov = _wecomOverlay();
    ov.style.display = 'flex';
  }

  async function _wecomOnFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    _wecomFile = file;
    await _wecomPreview();
  }

  async function _wecomPreview() {
    if (!_wecomFile) return;
    const fd = new FormData();
    fd.append('file', _wecomFile);
    if (_wecomMonth) fd.append('month', _wecomMonth);
    let body;
    try {
      const res = await fetch('/attendance/import/preview', { method: 'POST', body: fd });
      body = await res.json();
    } catch (err) { alert('预览失败：' + err.message); return; }
    if (!body.ok) { alert(body.msg); return; }
    _wecomMonth = body.month;
    _wecomRender(body);
  }

  function _wecomRender(plan) {
    const empOpts = employees.map(e => `<option value="${e.id}">${e.name}</option>`).join('');
    const unboundHtml = plan.unbound.length === 0
      ? '<p class="attn-muted">无待绑定账号 ✓</p>'
      : plan.unbound.map(u => `
          <div class="wecom-bind-row" data-account="${u.account}">
            <span class="wecom-bind-name">${u.name || '(无名)'}</span>
            <select class="attn-inp wecom-bind-sel">
              <option value="">— 选择员工 —</option>${empOpts}
            </select>
            <button class="attn-btn wecom-bind-go">绑定</button>
            <button class="attn-btn wecom-ignore-go">忽略</button>
          </div>`).join('');
    const manualHtml = plan.needs_manual.length === 0
      ? ''
      : `<details><summary>需手动补 ${plan.needs_manual.length} 天(单次打卡)</summary>
           <ul>${plan.needs_manual.map(m => `<li>${m.name} ${m.date} ${m.time}</li>`).join('')}</ul>
         </details>`;
    document.getElementById('wecomBody').innerHTML = `
      <div class="wecom-summary">
        目标月 <b>${plan.month}</b> ·
        已匹配 <b>${plan.counts.matched}</b> 人 ·
        待写 <b>${plan.counts.to_write}</b> 天 ·
        待绑定 <b>${plan.counts.unbound}</b> ·
        需手动 <b>${plan.counts.needs_manual}</b>
      </div>
      <h4>待绑定账号</h4>
      ${unboundHtml}
      ${manualHtml}
      <div class="wecom-actions">
        <button class="attn-btn attn-btn-primary" id="wecomApply">写入 ${plan.counts.to_write} 天</button>
      </div>`;
    plan.unbound.forEach(u => {
      if (u.suggested_employee_id) {
        const sel = document.querySelector(`.wecom-bind-row[data-account="${u.account}"] .wecom-bind-sel`);
        if (sel) sel.value = u.suggested_employee_id;
      }
    });
    document.querySelectorAll('.wecom-bind-go').forEach(btn =>
      btn.addEventListener('click', _wecomBind));
    document.querySelectorAll('.wecom-ignore-go').forEach(btn =>
      btn.addEventListener('click', _wecomIgnore));
    document.getElementById('wecomApply').addEventListener('click', _wecomApply);
  }

  async function _wecomBind(e) {
    const row = e.target.closest('.wecom-bind-row');
    const account = row.dataset.account;
    const employee_id = row.querySelector('.wecom-bind-sel').value;
    if (!employee_id) { alert('请先选择员工'); return; }
    const res = await fetch('/attendance/import/bind', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account, employee_id }),
    });
    const body = await res.json();
    if (!body.ok) { alert(body.msg); return; }
    await _wecomPreview();
  }

  async function _wecomIgnore(e) {
    const account = e.target.closest('.wecom-bind-row').dataset.account;
    const res = await fetch('/attendance/import/ignore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account }),
    });
    const body = await res.json();
    if (!body.ok) { alert(body.msg); return; }
    await _wecomPreview();
  }

  async function _wecomApply() {
    if (!_wecomFile || !confirm('确认写入?只填空白天,不覆盖已有考勤。')) return;
    const fd = new FormData();
    fd.append('file', _wecomFile);
    fd.append('month', _wecomMonth);
    const res = await fetch('/attendance/import/apply', { method: 'POST', body: fd });
    const body = await res.json();
    if (!body.ok) { alert(body.msg); return; }
    alert(`写入 ${body.written} 天,跳过已有 ${body.skipped_existing}、单次 ${body.skipped_single}。`);
    document.getElementById('wecomImportOverlay').remove();
    await loadMonth();  // 刷新当前月视图
  }
```

> 注:`attn-modal-overlay` / `attn-modal` / `attn-btn-primary` 复用现有考勤弹窗样式。若 `attn-btn-primary` 不存在,改用 `attn-btn`(功能不受影响)。`wecom-summary` / `wecom-bind-row` 等无样式也能用(纯布局,继承默认)。

- [ ] **Step 4: 无需前端构建**

未新增 Tailwind utility class(仅复用现有 attn-* + 行内 style),跳过构建步骤。

- [ ] **Step 5: 浏览器手动验证**

```bash
python server.py
```

打开 http://127.0.0.1:5000 → 考勤页 → 点「导入企业微信」:
1. 选 `打卡时间记录_20260501-20260527.xlsx` → 出现预览,顶部计数正确,待绑定区列出陌生账号(只显示姓名,无账号字符串)。
2. 给「翁福源」选员工 → 绑定 → 该行消失、已匹配 +1。
3. 给采购部某人点「忽略」→ 该行消失。
4. 点「写入 N 天」→ 确认 → alert 写入计数 → 月历刷新,翁福源对应天填上。
5. 再次导入同文件 → 已绑定的人自动匹配、已忽略的不再出现、已填天计入 skipped。

Expected:全部符合;全程不出现账号字符串。

- [ ] **Step 6: Commit**

```bash
git add static/js/attendance.js
git commit -m "feat(attendance): 企业微信导入前端弹窗(绑定/忽略/写入)"
```

---

## Task 7: 全量回归 + 真实文件冒烟

- [ ] **Step 1: 跑全量单元测试**

Run: `pytest tests/`
Expected: 原有 + 新增用例全 PASS,无回归。

- [ ] **Step 2: 真实文件端到端冒烟(本机有导出文件时)**

按 Task 6 Step 5 走一遍,核对某员工(如翁福源)当月填写天数与 Excel 一致。

---

## Self-Review 记录

- **Spec 覆盖**:身份匹配(Task 1/3)、解析含注释/单次/`--`(Task 2)、绑定即过滤 + 忽略清单(Task 3/4)、fill-blank-only(Task 4)、三段路由(Task 5)、UI 只显示姓名(Task 6)、测试(Task 2/4/5/7)。✓
- **占位符**:无 TBD/TODO;每步含完整代码与命令。✓
- **类型一致**:`parse_cell` 返回 tuple 形态在 Task 2 定义、Task 4 消费一致;`build_plan(rows, month)` / `apply_plan(rows, month)` 签名 Task 4 定义、Task 5 调用一致;`_build_plan_core` 关键字参数 Task 4 自洽;前端 `employees`/`loadMonth` 引用 Task 6 已注明来源。✓
