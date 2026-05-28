"""企业微信考勤导入：解析层 + 服务 + 计划层单测。"""
import os
import unittest

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
