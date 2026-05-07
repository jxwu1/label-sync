"""attendance routes 单测：HTTP 边界 + Pydantic 校验。

聚焦于 Pydantic 迁移后的参数校验行为：缺字段 / 类型错 / 取值非法 → 400 + 中文 msg；
正常通过 → 200 + 业务字段。
"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import attendance_service
from routes_attendance import bp

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_attendance_routes"


class AttendanceRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch = mock.patch.object(attendance_service, "_ATTENDANCE_DIR", self.test_dir)
        self.patch.start()
        self.addCleanup(self.patch.stop)

        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ---------- /employees ----------

    def test_create_employee_ok(self) -> None:
        rv = self.client.post("/attendance/employees", json={"name": "张三"})
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["employee"]["name"], "张三")

    def test_create_employee_strips_whitespace(self) -> None:
        rv = self.client.post("/attendance/employees", json={"name": "  李四  "})
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json()["employee"]["name"], "李四")

    def test_create_employee_empty_name_400(self) -> None:
        rv = self.client.post("/attendance/employees", json={"name": "   "})
        self.assertEqual(rv.status_code, 400)
        body = rv.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("name", body["msg"])

    def test_create_employee_missing_field_400(self) -> None:
        rv = self.client.post("/attendance/employees", json={})
        self.assertEqual(rv.status_code, 400)
        self.assertFalse(rv.get_json()["ok"])

    def test_create_employee_no_body_400(self) -> None:
        rv = self.client.post("/attendance/employees")
        self.assertEqual(rv.status_code, 400)

    # ---------- /holidays ----------

    def test_add_holiday_ok(self) -> None:
        rv = self.client.post("/attendance/holidays", json={"date": "2026-05-01"})
        self.assertEqual(rv.status_code, 200)
        self.assertIn("2026-05-01", rv.get_json()["holidays"])

    def test_add_holiday_missing_date_400(self) -> None:
        rv = self.client.post("/attendance/holidays", json={})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("date", rv.get_json()["msg"])

    # ---------- /special-days ----------

    def test_set_special_day_ok(self) -> None:
        rv = self.client.post(
            "/attendance/special-days",
            json={"date": "2026-05-02", "start": "09:00", "end": "18:00"},
        )
        self.assertEqual(rv.status_code, 200)

    def test_set_special_day_partial_400(self) -> None:
        rv = self.client.post(
            "/attendance/special-days",
            json={"date": "2026-05-02", "start": "09:00"},
        )
        self.assertEqual(rv.status_code, 400)
        self.assertIn("end", rv.get_json()["msg"])

    # ---------- /leave/<emp>/<date> ----------

    def test_set_leave_invalid_type_400(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "王五"}).get_json()
        rv = self.client.post(
            f"/attendance/leave/{emp['employee']['id']}/2026-05-03",
            json={"type": "weekly"},
        )
        self.assertEqual(rv.status_code, 400)
        self.assertIn("type", rv.get_json()["msg"])

    def test_set_leave_full_ok(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "王五"}).get_json()
        rv = self.client.post(
            f"/attendance/leave/{emp['employee']['id']}/2026-05-03",
            json={"type": "full"},
        )
        self.assertEqual(rv.status_code, 200)
        self.assertTrue(rv.get_json()["ok"])

    # ---------- /leave-range/<emp> ----------

    def test_leave_range_full_ok(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "赵六"}).get_json()
        # 2026-04-13 (一) ~ 2026-04-19 (日) 7 天，1 周日
        rv = self.client.post(
            f"/attendance/leave-range/{emp['employee']['id']}",
            json={
                "from_date": "2026-04-13",
                "to_date": "2026-04-19",
                "type": "full",
            },
        )
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["days_set"], 6)
        self.assertEqual(body["days_skipped_sunday"], 1)

    def test_leave_range_missing_field_400(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "赵六"}).get_json()
        rv = self.client.post(
            f"/attendance/leave-range/{emp['employee']['id']}",
            json={"from_date": "2026-04-13", "type": "full"},  # 缺 to_date
        )
        self.assertEqual(rv.status_code, 400)
        self.assertIn("to_date", rv.get_json()["msg"])

    def test_leave_range_invalid_type_400(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "赵六"}).get_json()
        rv = self.client.post(
            f"/attendance/leave-range/{emp['employee']['id']}",
            json={"from_date": "2026-04-13", "to_date": "2026-04-15", "type": "bogus"},
        )
        self.assertEqual(rv.status_code, 400)

    def test_leave_range_from_after_to_400(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "赵六"}).get_json()
        rv = self.client.post(
            f"/attendance/leave-range/{emp['employee']['id']}",
            json={"from_date": "2026-04-15", "to_date": "2026-04-10", "type": "full"},
        )
        self.assertEqual(rv.status_code, 400)

    # ---------- /inactive-periods/<emp> ----------

    def test_inactive_periods_add_and_list(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "员工A"}).get_json()
        eid = emp["employee"]["id"]
        rv = self.client.post(
            f"/attendance/inactive-periods/{eid}",
            json={"from_date": "2026-04-01", "to_date": "2026-04-15", "reason": "产假"},
        )
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertEqual(body["period"]["from"], "2026-04-01")
        self.assertEqual(body["period"]["reason"], "产假")
        # GET 返回同样
        rv2 = self.client.get(f"/attendance/inactive-periods/{eid}")
        self.assertEqual(len(rv2.get_json()["periods"]), 1)

    def test_inactive_periods_delete(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "员工B"}).get_json()
        eid = emp["employee"]["id"]
        self.client.post(
            f"/attendance/inactive-periods/{eid}",
            json={"from_date": "2026-04-01", "to_date": "2026-04-15"},
        )
        rv = self.client.delete(
            f"/attendance/inactive-periods/{eid}",
            json={"from_date": "2026-04-01", "to_date": "2026-04-15"},
        )
        self.assertEqual(rv.status_code, 200)
        # 再删一次 404
        rv2 = self.client.delete(
            f"/attendance/inactive-periods/{eid}",
            json={"from_date": "2026-04-01", "to_date": "2026-04-15"},
        )
        self.assertEqual(rv2.status_code, 404)

    def test_inactive_periods_invalid_range_400(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "员工C"}).get_json()
        rv = self.client.post(
            f"/attendance/inactive-periods/{emp['employee']['id']}",
            json={"from_date": "2026-04-15", "to_date": "2026-04-01"},
        )
        self.assertEqual(rv.status_code, 400)

    # ---------- /holidays/import-year/<year> (PR-FE-7d) ----------

    def test_import_holidays_year_unknown_404(self) -> None:
        rv = self.client.post("/attendance/holidays/import-year/1900")
        self.assertEqual(rv.status_code, 404)
        self.assertFalse(rv.get_json()["ok"])

    def test_import_holidays_year_2025_ok(self) -> None:
        rv = self.client.post("/attendance/holidays/import-year/2025")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertGreater(body["added"], 0)
        # 元旦肯定在
        self.assertIn("2025-01-01", body["holidays"])

    def test_import_holidays_idempotent(self) -> None:
        r1 = self.client.post("/attendance/holidays/import-year/2025").get_json()
        r2 = self.client.post("/attendance/holidays/import-year/2025").get_json()
        # 第二次添加 0 个新（都是 dedupe 后已存在）
        self.assertGreater(r1["added"], 0)
        self.assertEqual(r2["added"], 0)
        # 列表里日期数量不变
        self.assertEqual(len(r1["holidays"]), len(r2["holidays"]))

    def test_import_holidays_invalid_year_400(self) -> None:
        rv = self.client.post("/attendance/holidays/import-year/abc")
        self.assertIn(rv.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
