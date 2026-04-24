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
