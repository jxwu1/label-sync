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
