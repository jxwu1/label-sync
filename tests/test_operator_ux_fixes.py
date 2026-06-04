"""操作员体验修复 (报错说人话 + 消灭静默吞错)。

覆盖:
- A1: 采购 /process 建单失败不静默, 回 order_error 且保留解析结果
- A2: 数量解析失败带 quantity_flagged (对齐 price_flagged); 文件级解析失败给人话
- A3: 考勤 fill_rates 计算失败不静默吐 0%, 回 ok:false
"""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import openpyxl
from flask import Flask


def _excel_bytes(qty="144") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["条码", "col2", "价格", "col4", "col5", "数量"])
    ws.append(["1234567890123", "x", 9.48, "x", "x", qty])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- A2: 解析层 quantity_flagged ----------
class TestQuantityFlagged(unittest.TestCase):
    def test_bad_quantity_is_flagged(self) -> None:
        from app.services.purchase import parse_purchase_excel

        rows = parse_purchase_excel(_excel_bytes(qty="abc"))
        self.assertEqual(rows[0].quantity, 0)
        self.assertTrue(rows[0].quantity_flagged)
        self.assertIn("quantity_flagged", rows[0].to_dict())
        self.assertTrue(rows[0].to_dict()["quantity_flagged"])

    def test_good_quantity_not_flagged(self) -> None:
        from app.services.purchase import parse_purchase_excel

        rows = parse_purchase_excel(_excel_bytes(qty="144"))
        self.assertEqual(rows[0].quantity, 144)
        self.assertFalse(rows[0].quantity_flagged)


# ---------- A1: /process 建单失败不静默 ----------
class TestProcessOrderErrorSurfaced(unittest.TestCase):
    def setUp(self) -> None:
        from app.routes.purchase import bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(bp)
        self.client = app.test_client()

    @patch("app.routes.purchase.purchase_service.create_order", side_effect=RuntimeError("db down"))
    @patch("app.routes.purchase.purchase_service.lookup_dominant_supplier", return_value=None)
    @patch("app.routes.purchase.stockpile_db.query_zero_grade_barcodes_set", return_value=set())
    @patch("app.routes.purchase.stockpile_db.query_all_barcodes_set", return_value={"EXIST"})
    def test_order_failure_surfaced_not_swallowed(self, _q_all, _q_zero, _lookup, _create) -> None:
        resp = self.client.post(
            "/purchase/process",
            data={"files": (io.BytesIO(_excel_bytes()), "supplier.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        # 解析结果仍保留 (操作员的主要目的)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["rows"]), 1)
        # 但建单失败必须明确暴露, 不能静默
        self.assertIsNone(body["order"])
        self.assertIn("db down", body["order_error"])


# ---------- A2: 文件级解析失败给人话 ----------
class TestProcessBadFileMessage(unittest.TestCase):
    def setUp(self) -> None:
        from app.routes.purchase import bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(bp)
        self.client = app.test_client()

    @patch("app.routes.purchase.stockpile_db.query_all_barcodes_set", return_value=set())
    def test_garbage_file_gives_readable_message(self, _q) -> None:
        resp = self.client.post(
            "/purchase/process",
            data={"files": (io.BytesIO(b"not an excel"), "supplier.xlsx")},
            content_type="multipart/form-data",
        )
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("Excel", body["msg"])  # 人话, 提示是 Excel 文件问题


# ---------- A3: fill_rates 不吞异常 ----------
class TestFillRatesNoSilentSwallow(unittest.TestCase):
    def setUp(self) -> None:
        from app.routes.attendance import bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(bp)
        self.client = app.test_client()

    @patch(
        "app.routes.attendance.attendance_service.compute_summaries_batch",
        side_effect=RuntimeError("calc boom"),
    )
    @patch(
        "app.routes.attendance.attendance_service.list_employees",
        return_value=[{"id": "E1", "name": "甲"}],
    )
    def test_compute_failure_returns_error_not_zeros(self, _emps, _calc) -> None:
        resp = self.client.get("/attendance/fill-rates/2026-06")
        body = resp.get_json()
        self.assertFalse(body["ok"])  # 不再静默吐 0%


if __name__ == "__main__":
    unittest.main()
