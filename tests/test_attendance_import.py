"""企业微信考勤导入：解析层 + 服务 + 计划层单测。"""
import io
import os
import unittest

import openpyxl

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Employee
from app.services import attendance_import as imp


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


_REAL_FILE = r"C:\Users\64474\Downloads\上下班打卡_打卡时间记录_20260501-20260527.xlsx"


class ParseWorkbookTests(unittest.TestCase):
    def test_parses_synthetic_workbook(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "打卡时间记录"
        ws.append(["打卡时间记录"])
        ws.append(["统计时间:05-01 ～ 05-02"])
        ws.append(["姓名", "账号", "基础信息", "", "", "打卡时间记录"])
        ws.append(["", "", "部门", "职务", "工号", "1\n星期五", "2\n星期六"])
        ws.append(["翁福源", "WengFuYuan", "希腊销售部", "--", "--", "09:25、20:00", "09:40"])
        ws.append(["", "", "", "", "", "--", "--"])  # 空账号行应被跳过
        buf = io.BytesIO()
        wb.save(buf)
        out = imp.parse_workbook(buf.getvalue(), "wecom_20260501-20260502.xlsx")
        self.assertEqual(out["detected_month"], "2026-05")
        rows = {row["account"]: row for row in out["rows"]}
        self.assertEqual(list(rows), ["WengFuYuan"])  # 空账号行被跳过
        self.assertEqual(rows["WengFuYuan"]["days"][1], ("ok", "09:25", "20:00"))
        self.assertEqual(rows["WengFuYuan"]["days"][2], ("single", "09:40"))

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
