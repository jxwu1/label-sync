"""attendance routes 单测：HTTP 边界 + Pydantic 校验。

聚焦于 Pydantic 迁移后的参数校验行为：缺字段 / 类型错 / 取值非法 → 400 + 中文 msg；
正常通过 → 200 + 业务字段。
"""

import unittest

from flask import Flask

from app.routes.attendance import bp
from app.services import attendance as attendance_service


class AttendanceRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        # DB 隔离由 conftest autouse 提供；这里只建最小 app。
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

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

    def test_create_employee_with_start_date_persists(self) -> None:
        """R8：可选入职日字段写入 employees.json，被 compute_summary 用作 pre_join 起点。"""
        rv = self.client.post(
            "/attendance/employees",
            json={"name": "赵六", "start_date": "2026-04-15"},
        )
        self.assertEqual(rv.status_code, 200)
        eid = rv.get_json()["employee"]["id"]
        # 落到磁盘的 employees.json 含 start_date
        emps = attendance_service.list_employees()
        self.assertEqual(next(e for e in emps if e["id"] == eid)["start_date"], "2026-04-15")
        # compute_summary 在该日之前的天应该是 pre_join
        summary = attendance_service.compute_summary(eid, "2026-04")
        before_start = next(r for r in summary["detail"] if r["date"] == "2026-04-01")
        on_start = next(r for r in summary["detail"] if r["date"] == "2026-04-15")
        self.assertEqual(before_start["status"], "pre_join")
        self.assertNotEqual(on_start["status"], "pre_join")

    def test_create_employee_no_start_date_backwards_compat(self) -> None:
        """不传 start_date / 传空串 → 200，employees.json 不写该字段。"""
        rv = self.client.post("/attendance/employees", json={"name": "钱七"})
        self.assertEqual(rv.status_code, 200)
        eid = rv.get_json()["employee"]["id"]
        emp = next(e for e in attendance_service.list_employees() if e["id"] == eid)
        self.assertNotIn("start_date", emp)

        rv2 = self.client.post("/attendance/employees", json={"name": "孙八", "start_date": ""})
        self.assertEqual(rv2.status_code, 200)
        eid2 = rv2.get_json()["employee"]["id"]
        emp2 = next(e for e in attendance_service.list_employees() if e["id"] == eid2)
        self.assertNotIn("start_date", emp2)

    def test_create_employee_bad_start_date_400(self) -> None:
        rv = self.client.post(
            "/attendance/employees", json={"name": "周九", "start_date": "2026/04/15"}
        )
        self.assertEqual(rv.status_code, 400)
        self.assertIn("start_date", rv.get_json()["msg"])

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

    # ---------- /fill-rates/<month> (PR-FE-7d-2) ----------

    def test_fill_rates_empty_no_employees(self) -> None:
        rv = self.client.get("/attendance/fill-rates/2026-04")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["employees"], [])

    def test_fill_rates_returns_per_employee_stats(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "张三"}).get_json()
        eid = emp["employee"]["id"]
        rv = self.client.get("/attendance/fill-rates/2026-04")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertEqual(len(body["employees"]), 1)
        row = body["employees"][0]
        self.assertEqual(row["id"], eid)
        self.assertEqual(row["name"], "张三")
        self.assertIn("filled", row)
        self.assertIn("total", row)
        self.assertIn("rate", row)
        # 没填任何天 → filled=0
        self.assertEqual(row["filled"], 0)
        self.assertGreater(row["total"], 0)
        self.assertEqual(row["rate"], 0.0)

    def test_fill_rates_reflects_filled_days(self) -> None:
        emp = self.client.post("/attendance/employees", json={"name": "李四"}).get_json()
        eid = emp["employee"]["id"]
        # 填 1 天
        self.client.post(
            f"/attendance/day/{eid}/2026-04-01",
            json={"start": "09:30", "end": "20:00"},
        )
        rv = self.client.get("/attendance/fill-rates/2026-04")
        row = rv.get_json()["employees"][0]
        self.assertGreater(row["filled"], 0)
        self.assertGreater(row["rate"], 0.0)

    def test_fill_rates_batch_returns_all_employees(self) -> None:
        """fill-rates 批量接口应返回所有员工的数据。"""
        for i in range(20):
            self.client.post("/attendance/employees", json={"name": f"员工{i}"})

        rv = self.client.get("/attendance/fill-rates/2026-04")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(len(rv.get_json()["employees"]), 20)


if __name__ == "__main__":
    unittest.main()
