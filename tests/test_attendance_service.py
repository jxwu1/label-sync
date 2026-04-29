import shutil
import unittest
from pathlib import Path
from unittest import mock

import attendance_service as svc

_TEST_ROOT = Path(__file__).resolve().parent


class TestEmployeeCrud(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_attendance_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

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
        self.test_dir = _TEST_ROOT / f"_test_attendance_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

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


class TestComputeSummary(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_attendance_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

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


class TestHolidays(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_attendance_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_holidays_initially(self):
        self.assertEqual(svc.list_holidays(), [])

    def test_add_and_list_holiday(self):
        svc.add_holiday("2026-05-01")
        self.assertEqual(svc.list_holidays(), ["2026-05-01"])

    def test_add_duplicate_is_idempotent(self):
        svc.add_holiday("2026-05-01")
        svc.add_holiday("2026-05-01")
        self.assertEqual(svc.list_holidays(), ["2026-05-01"])

    def test_remove_holiday(self):
        svc.add_holiday("2026-05-01")
        svc.remove_holiday("2026-05-01")
        self.assertEqual(svc.list_holidays(), [])

    def test_holiday_counts_as_one_day_in_summary(self):
        svc.add_holiday("2026-04-01")  # 周三
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-01")
        self.assertEqual(row["status"], "holiday")
        self.assertEqual(row["day_fraction"], 1.0)

    def test_sunday_takes_priority_over_holiday(self):
        svc.add_holiday("2026-04-05")  # 周日
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-05")
        self.assertEqual(row["status"], "sunday")

    def test_holiday_does_not_count_as_absent(self):
        svc.add_holiday("2026-04-01")
        result = svc.compute_summary("e001", "2026-04")
        # 30 天 - 4 周日 - 1 节假日 = 25 缺勤
        self.assertEqual(result["absent_days"], 25)


class TestSpecialDays(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_attendance_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_list_empty_initially(self):
        self.assertEqual(svc.list_special_days(), {})

    def test_add_and_list(self):
        svc.set_special_day("2026-04-02", "09:30", "14:30")
        self.assertEqual(
            svc.list_special_days(), {"2026-04-02": {"start": "09:30", "end": "14:30"}}
        )

    def test_remove(self):
        svc.set_special_day("2026-04-02", "09:30", "14:30")
        svc.remove_special_day("2026-04-02")
        self.assertEqual(svc.list_special_days(), {})

    def test_full_attendance_on_special_day_is_one(self):
        svc.set_special_day("2026-04-02", "09:30", "14:30")  # 5h 缩短标准
        svc.set_day("e001", "2026-04-02", {"start": "09:30", "end": "14:30"})
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-02")
        self.assertEqual(row["status"], "special")
        self.assertEqual(row["day_fraction"], 1.0)

    def test_partial_on_special_day_is_prorated(self):
        svc.set_special_day("2026-04-02", "09:30", "14:30")  # 5h 缩短
        svc.set_day("e001", "2026-04-02", {"start": "09:30", "end": "12:30"})  # 3h / 5h
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-02")
        self.assertAlmostEqual(row["day_fraction"], 0.6, places=3)

    def test_special_day_no_record_is_absent(self):
        svc.set_special_day("2026-04-02", "09:30", "14:30")
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-02")
        self.assertEqual(row["status"], "special_absent")
        self.assertEqual(row["day_fraction"], 0.0)

    def test_holiday_takes_priority_over_special(self):
        svc.add_holiday("2026-04-02")
        svc.set_special_day("2026-04-02", "09:30", "14:30")
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-02")
        self.assertEqual(row["status"], "holiday")

    def test_day_fraction_with_custom_standard(self):
        # 09:30-12:30 = 3h; custom standard 5h -> 0.6
        self.assertAlmostEqual(
            svc.day_fraction("09:30", "12:30", standard_hours=5.0), 0.6, places=3
        )
        # 10h with custom 5h -> 1.0 cap
        self.assertAlmostEqual(svc.day_fraction("09:00", "19:00", standard_hours=5.0), 1.0)


class TestLeaves(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_attendance_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_list_empty_initially(self):
        self.assertEqual(svc.list_leaves("2026-04"), {})

    def test_summary_has_leave_fields_when_no_leaves(self):
        # 无请假月份，service 仍须返回完整字段
        result = svc.compute_summary("e001", "2026-04")
        self.assertEqual(result["leave_hours_total"], 0.0)
        self.assertEqual(result["leave_days_equivalent"], 0.0)
        for row in result["detail"]:
            self.assertEqual(row["leave_hours"], 0.0)
            self.assertEqual(row["leave_type"], "")
            self.assertEqual(row["leave_start"], "")
            self.assertEqual(row["leave_end"], "")

    def test_set_full_day(self):
        entry = svc.set_leave("e001", "2026-04-15", "full")
        self.assertEqual(entry["type"], "full")
        self.assertEqual(entry["hours"], 10.5)

    def test_set_range(self):
        entry = svc.set_leave("e001", "2026-04-15", "range", start="10:00", end="12:00")
        self.assertEqual(entry["type"], "range")
        self.assertEqual(entry["hours"], 2.0)
        self.assertEqual(entry["start"], "10:00")
        self.assertEqual(entry["end"], "12:00")

    def test_set_left(self):
        # 14:00 离开，标准下班 20:00 → 6h
        entry = svc.set_leave("e001", "2026-04-15", "left", start="14:00")
        self.assertEqual(entry["type"], "left")
        self.assertEqual(entry["hours"], 6.0)

    def test_set_left_on_special_day(self):
        # 特殊日 09:30-14:30，14:00 离开 → 0.5h
        svc.set_special_day("2026-04-15", "09:30", "14:30")
        entry = svc.set_leave("e001", "2026-04-15", "left", start="14:00")
        self.assertEqual(entry["hours"], 0.5)

    def test_set_full_on_special_day(self):
        # 特殊日 09:30-14:30 = 5h，全天请假应为 5h
        svc.set_special_day("2026-04-15", "09:30", "14:30")
        entry = svc.set_leave("e001", "2026-04-15", "full")
        self.assertEqual(entry["hours"], 5.0)

    def test_set_overwrites(self):
        svc.set_leave("e001", "2026-04-15", "full")
        svc.set_leave("e001", "2026-04-15", "range", start="10:00", end="12:00")
        stored = svc.list_leaves("2026-04")["e001"]["2026-04-15"]
        self.assertEqual(stored["type"], "range")

    def test_clear_removes(self):
        svc.set_leave("e001", "2026-04-15", "full")
        svc.clear_leave("e001", "2026-04-15")
        self.assertEqual(svc.list_leaves("2026-04"), {})

    def test_range_rejects_invalid_times(self):
        with self.assertRaises(ValueError):
            svc.set_leave("e001", "2026-04-15", "range", start="12:00", end="10:00")

    def test_left_rejects_after_standard_end(self):
        with self.assertRaises(ValueError):
            svc.set_leave("e001", "2026-04-15", "left", start="20:00")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            svc.set_leave("e001", "2026-04-15", "bogus")

    def test_leave_not_counted_as_absent(self):
        svc.set_leave("e001", "2026-04-01", "full")  # 周三，全天请假
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-01")
        self.assertEqual(row["status"], "leave")
        self.assertEqual(row["leave_hours"], 10.5)
        self.assertEqual(row["leave_type"], "full")
        # 30 天 - 4 周日 - 1 请假（不计缺勤） = 25 缺勤
        self.assertEqual(result["absent_days"], 25)

    def test_leave_does_not_inflate_worked_days(self):
        svc.set_leave("e001", "2026-04-01", "full")
        result = svc.compute_summary("e001", "2026-04")
        self.assertEqual(result["worked_days"], 4.0)

    def test_leave_hours_total(self):
        svc.set_leave("e001", "2026-04-01", "full")  # 10.5
        svc.set_leave("e001", "2026-04-02", "range", start="09:30", end="14:45")  # 5.25
        result = svc.compute_summary("e001", "2026-04")
        self.assertAlmostEqual(result["leave_hours_total"], 15.75)
        self.assertAlmostEqual(result["leave_days_equivalent"], 15.75 / 10.5, places=3)

    def test_holiday_priority_over_leave(self):
        svc.add_holiday("2026-04-01")
        svc.set_leave("e001", "2026-04-01", "full")
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-01")
        self.assertEqual(row["status"], "holiday")

    def test_leave_with_clock_in_same_day(self):
        svc.set_leave("e001", "2026-04-01", "range", start="09:30", end="12:30")
        svc.set_day("e001", "2026-04-01", {"start": "13:00", "end": "20:00"})
        result = svc.compute_summary("e001", "2026-04")
        row = next(d for d in result["detail"] if d["date"] == "2026-04-01")
        self.assertEqual(row["status"], "leave")
        self.assertEqual(row["leave_hours"], 3.0)
        self.assertEqual(row["leave_type"], "range")
        self.assertEqual(row["start"], "13:00")
        self.assertEqual(row["end"], "20:00")
        self.assertAlmostEqual(row["day_fraction"], 7.0 / 10.5, places=3)
