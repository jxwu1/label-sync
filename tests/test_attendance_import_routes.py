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
        self.p1.start()
        self.p2.start()
        with self.Session() as s:
            s.add(Employee(employee_id="e001", name="翁福源"))
            s.commit()
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def tearDown(self):
        self.p2.stop()
        self.p1.stop()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

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
        self.assertIn("WengFuYuan", accs)
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

    def test_unignore_restores_account(self):
        self.client.post("/attendance/import/ignore", json={"account": "NewGuy"})
        # ignored: NewGuy no longer in unbound
        body = self._upload("/attendance/import/preview").get_json()
        self.assertNotIn("NewGuy", {u["account"] for u in body["unbound"]})
        self.assertIn("NewGuy", {i["account"] for i in body["ignored"]})
        # un-ignore: back in unbound, gone from ignored
        self.client.post("/attendance/import/unignore", json={"account": "NewGuy"})
        body2 = self._upload("/attendance/import/preview").get_json()
        self.assertIn("NewGuy", {u["account"] for u in body2["unbound"]})
        self.assertEqual(body2["ignored"], [])

    def test_apply_writes_only_ok_days(self):
        self.client.post("/attendance/import/bind",
                         json={"account": "WengFuYuan", "employee_id": "e001"})
        rv = self._upload("/attendance/import/apply", month="2026-05")
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["written"], 1)        # 1 号写入
        self.assertEqual(body["skipped_single"], 1) # 2 号单次跳过
        summ = self.client.get("/attendance/month/e001/2026-05").get_json()
        day1 = next(d for d in summ["detail"] if d["date"] == "2026-05-01")
        self.assertEqual(day1["start"], "09:25")
        self.assertEqual(day1["end"], "20:00")
