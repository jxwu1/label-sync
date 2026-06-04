import unittest
from unittest import mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base, Employee
from app.services import attendance as svc


def _make_test_db():
    """Create an in-memory SQLite engine with FK enforcement and all tables.

    Uses StaticPool so all connections share the same in-memory DB.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, Session


class _DBTestCase(unittest.TestCase):
    """Base class that patches app.models to use an in-memory SQLite DB."""

    def setUp(self):
        import app.models as models_mod

        self.engine, self.Session = _make_test_db()
        self.patch_engine = mock.patch.object(models_mod, "_engine", self.engine)
        self.patch_session = mock.patch.object(models_mod, "_SessionFactory", self.Session)
        self.patch_engine.start()
        self.patch_session.start()

    def tearDown(self):
        self.patch_session.stop()
        self.patch_engine.stop()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _ensure_employee(
        self, emp_id: str, name: str = "test", start_date: str | None = None
    ) -> None:
        """Insert or update an employee directly via ORM (bypasses service ID generation)."""
        from datetime import datetime

        session = self.Session()
        try:
            existing = session.get(Employee, emp_id)
            if existing:
                existing.name = name
                existing.start_date = start_date
            else:
                session.add(
                    Employee(
                        employee_id=emp_id,
                        name=name,
                        created_at=datetime.now().isoformat(timespec="seconds"),
                        start_date=start_date,
                        active=1,
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class TestEmployeeCrud(_DBTestCase):
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

    def test_delete_employee_with_attendance_keeps_records(self):
        """有考勤记录的员工删除：软删除——不抛外键错，历史记录保留，列表不再显示。"""
        from app.models import AttendanceRecord

        emp = svc.create_employee("有记录的人")
        session = self.Session()
        try:
            session.add(
                AttendanceRecord(
                    employee_id=emp["id"],
                    work_date="2026-05-01",
                    start_time="09:30",
                    end_time="20:00",
                )
            )
            session.commit()
        finally:
            session.close()

        # 删除不应抛外键错（生产环境 PG 上 FK 强制，硬删会 ForeignKeyViolation → 500）
        svc.delete_employee(emp["id"])

        # 列表不再显示
        self.assertEqual(svc.list_employees(), [])

        # 历史考勤记录保留（UI 文案承诺"历史考勤数据保留"）
        session = self.Session()
        try:
            kept = session.query(AttendanceRecord).filter_by(employee_id=emp["id"]).count()
        finally:
            session.close()
        self.assertEqual(kept, 1)


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


class TestDayCrud(_DBTestCase):
    def setUp(self):
        super().setUp()
        # FK constraint requires employee to exist before inserting attendance records
        self._ensure_employee("e001")

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


class TestComputeSummary(_DBTestCase):
    def setUp(self):
        super().setUp()
        # Most tests use e001 without a start_date; create it here.
        self._ensure_employee("e001")

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

    def _seed_employee(self, emp_id: str, name: str, start_date: str = "") -> None:
        """Create an employee via ORM for compute_summary tests."""
        self._ensure_employee(emp_id, name=name, start_date=start_date or None)

    def test_mid_month_hire_excludes_pre_join_sundays_and_absences(self):
        """月底新来员工：入职日之前的天不算（包括周日 / 缺勤）。"""
        # 2026-04-25 入职（周六）。本月 4 个周日 5/12/19/26 中只有 26 在入职日之后
        self._seed_employee("e001", "新工人", "2026-04-25T10:30:00")

        # 入职后录一天工
        svc.set_day("e001", "2026-04-27", {"start": "09:30", "end": "20:00"})  # 周一

        result = svc.compute_summary("e001", "2026-04")

        # detail 长度依然 30（保留完整日历视图）
        self.assertEqual(len(result["detail"]), 30)
        # 入职前 24 天全是 pre_join
        pre_join_rows = [d for d in result["detail"] if d["status"] == "pre_join"]
        self.assertEqual(len(pre_join_rows), 24)
        # 入职后剩 6 天（25-30）
        post_join_rows = [d for d in result["detail"] if d["status"] != "pre_join"]
        self.assertEqual(len(post_join_rows), 6)

        # month_days 反映在职天数（不是日历 30）
        self.assertEqual(result["month_days"], 6)
        # 周日只算入职后那一个（4-26）
        sunday_count = sum(1 for d in post_join_rows if d["status"] == "sunday")
        self.assertEqual(sunday_count, 1)
        # 缺勤只算入职后非周日没录的（25/27 录或不录 + 28/29/30）
        # 27 已录 → 不缺；25/28/29/30 没录 → 4 缺勤；26 周日不算
        self.assertEqual(result["absent_days"], 4)
        # total_workdays = 6 - 4 = 2 (1 周日 + 27 这一天)
        self.assertEqual(result["total_workdays"], 2)
        # worked_days = 1 周日(1.0) + 27 fraction(1.0)
        self.assertAlmostEqual(result["worked_days"], 2.0, places=2)

    def test_employee_without_start_date_unchanged(self):
        """老员工无 start_date（数据迁移 / 历史导入场景）→ 按全月算，不影响。"""
        self._seed_employee("e002", "老工人")  # 不传 start_date
        result = svc.compute_summary("e002", "2026-04")
        # 老逻辑：30 天里 26 缺勤
        self.assertEqual(result["absent_days"], 26)
        self.assertEqual(result["month_days"], 30)

    def test_employee_hired_before_month_unchanged(self):
        """入职日在本月之前 → 没有 pre_join，所有天正常算。"""
        self._seed_employee("e003", "去年来的", "2025-01-01T00:00:00")
        result = svc.compute_summary("e003", "2026-04")
        self.assertEqual(result["month_days"], 30)
        self.assertEqual(sum(1 for d in result["detail"] if d["status"] == "pre_join"), 0)

    def test_inactive_period_excludes_days_within(self):
        """老员工产假回归：4-01 到 4-15 标为不在职，剩 15 天算。"""
        self._seed_employee("e004", "产假回归", "2024-01-01T00:00:00")
        svc.add_inactive_period("e004", "2026-04-01", "2026-04-15", reason="产假")
        result = svc.compute_summary("e004", "2026-04")
        # 4-01 ~ 4-15 共 15 天 pre_join；4-16 ~ 4-30 共 15 天正常
        pre_join = sum(1 for d in result["detail"] if d["status"] == "pre_join")
        self.assertEqual(pre_join, 15)
        self.assertEqual(result["month_days"], 15)
        # 这 15 天里有 4-19 / 4-26 两个周日（含 1.0 各）
        sunday_count = sum(1 for d in result["detail"] if d["status"] == "sunday")
        self.assertEqual(sunday_count, 2)
        # 其余 13 天没记录 → absent
        self.assertEqual(result["absent_days"], 13)

    def test_remove_inactive_period(self):
        self._seed_employee("e005", "X", "2024-01-01T00:00:00")
        svc.add_inactive_period("e005", "2026-04-10", "2026-04-20")
        self.assertEqual(len(svc.list_inactive_periods("e005")), 1)
        removed = svc.remove_inactive_period("e005", "2026-04-10", "2026-04-20")
        self.assertTrue(removed)
        self.assertEqual(svc.list_inactive_periods("e005"), [])

    def test_add_inactive_period_invalid_range(self):
        self._seed_employee("e006", "X", "2024-01-01T00:00:00")
        with self.assertRaises(ValueError):
            svc.add_inactive_period("e006", "2026-04-20", "2026-04-10")

    def test_add_inactive_period_unknown_employee(self):
        with self.assertRaises(ValueError):
            svc.add_inactive_period("notexist", "2026-04-01", "2026-04-15")


class TestHolidays(_DBTestCase):
    def setUp(self):
        super().setUp()
        # compute_summary tests in this class use e001
        self._ensure_employee("e001")

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

    # R3: 算法生成希腊节假日（替换硬编码 dict）
    def test_compute_gr_holidays_2025_matches_legacy_dict(self):
        # 原 _GR_HOLIDAYS_BY_YEAR[2025] 快照（Easter 2025 = 04/20）
        expected = sorted(
            [
                "2025-01-01",
                "2025-01-06",
                "2025-03-03",
                "2025-03-25",
                "2025-04-18",
                "2025-04-21",
                "2025-05-01",
                "2025-06-09",
                "2025-08-15",
                "2025-10-28",
                "2025-12-25",
                "2025-12-26",
            ]
        )
        self.assertEqual(svc._compute_gr_holidays(2025), expected)

    def test_compute_gr_holidays_2026_matches_legacy_dict(self):
        # 原 _GR_HOLIDAYS_BY_YEAR[2026] 快照（Easter 2026 = 04/12）
        expected = sorted(
            [
                "2026-01-01",
                "2026-01-06",
                "2026-02-23",
                "2026-03-25",
                "2026-04-10",
                "2026-04-13",
                "2026-05-01",
                "2026-06-01",
                "2026-08-15",
                "2026-10-28",
                "2026-12-25",
                "2026-12-26",
            ]
        )
        self.assertEqual(svc._compute_gr_holidays(2026), expected)

    def test_compute_gr_holidays_2027_easter_may_2(self):
        # 抽测 2027：Easter = 2027-05-02 →
        # Clean Mon 03-15 / Good Fri 04-30 / Easter Mon 05-03 / Holy Spirit 06-21
        expected = sorted(
            [
                "2027-01-01",
                "2027-01-06",
                "2027-03-15",
                "2027-03-25",
                "2027-04-30",
                "2027-05-01",
                "2027-05-03",
                "2027-06-21",
                "2027-08-15",
                "2027-10-28",
                "2027-12-25",
                "2027-12-26",
            ]
        )
        self.assertEqual(svc._compute_gr_holidays(2027), expected)

    def test_compute_gr_holidays_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            svc._compute_gr_holidays(1900)
        with self.assertRaises(ValueError):
            svc._compute_gr_holidays(2100)

    def test_import_holidays_for_year_2027_writes_file(self):
        result = svc.import_holidays_for_year(2027)
        self.assertEqual(result["added"], 12)
        # Easter Sunday 不收录（已是周日）；Easter Monday / Clean Monday 应在
        self.assertNotIn("2027-05-02", result["holidays"])
        self.assertIn("2027-05-03", result["holidays"])
        self.assertIn("2027-03-15", result["holidays"])

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


class TestSpecialDays(_DBTestCase):
    def setUp(self):
        super().setUp()
        # compute_summary tests in this class use e001
        self._ensure_employee("e001")

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


class TestLeaves(_DBTestCase):
    def setUp(self):
        super().setUp()
        # Most leave tests use e001
        self._ensure_employee("e001")

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

    def test_set_leave_range_writes_full_to_each_non_sunday(self):
        # 2026-04-13 (一) 到 2026-04-19 (日)：7 天，含 1 周日 (4-19)
        result = svc.set_leave_range("e001", "2026-04-13", "2026-04-19", "full")
        self.assertEqual(result["days_set"], 6)
        self.assertEqual(result["days_skipped_sunday"], 1)
        leaves = svc.list_leaves("2026-04").get("e001", {})
        # 6 天非周日全有 leave 记录
        for d in (
            "2026-04-13",
            "2026-04-14",
            "2026-04-15",
            "2026-04-16",
            "2026-04-17",
            "2026-04-18",
        ):
            self.assertIn(d, leaves)
            self.assertEqual(leaves[d]["type"], "full")
        # 周日没写入
        self.assertNotIn("2026-04-19", leaves)

    def test_set_leave_range_invalid_type(self):
        with self.assertRaises(ValueError, msg="leave_type"):
            svc.set_leave_range("e001", "2026-04-01", "2026-04-03", "bogus")

    def test_set_leave_range_from_after_to_raises(self):
        with self.assertRaises(ValueError):
            svc.set_leave_range("e001", "2026-04-10", "2026-04-05", "full")

    def test_set_leave_range_single_day(self):
        # from == to 也合法
        result = svc.set_leave_range("e001", "2026-04-15", "2026-04-15", "full")
        self.assertEqual(result["days_set"], 1)
        self.assertEqual(result["days_skipped_sunday"], 0)

    def test_set_leave_range_cross_month(self):
        # 跨月：4-29 到 5-2 = 4 天，无周日
        result = svc.set_leave_range("e001", "2026-04-29", "2026-05-02", "full")
        self.assertEqual(result["days_set"], 4)
        # leaves 写到对应的月份文件
        self.assertIn("2026-04-29", svc.list_leaves("2026-04").get("e001", {}))
        self.assertIn("2026-05-01", svc.list_leaves("2026-05").get("e001", {}))

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


class TestScannerFlag(_DBTestCase):
    def test_set_scanner_and_list(self):
        emp = svc.create_employee("小王")
        svc.set_scanner(emp["id"], True)
        listed = {e["id"]: e for e in svc.list_employees()}
        self.assertTrue(listed[emp["id"]]["is_scanner"])
        svc.set_scanner(emp["id"], False)
        listed = {e["id"]: e for e in svc.list_employees()}
        self.assertFalse(listed[emp["id"]]["is_scanner"])
