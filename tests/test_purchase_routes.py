import io
import json
import unittest
from unittest.mock import patch

import openpyxl
from flask import Flask

from routes_purchase import bp


def make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


def _excel_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["条码", "col2", "价格", "col4", "col5", "数量"])
    ws.append(["1234567890123", "x", 9.48, "x", "x", 144])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestPurchaseRoutes(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_process_requires_file(self):
        response = self.client.post("/purchase/process")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_process_returns_rows(self):
        from purchase_service import PurchaseRow
        mock_rows = [
            PurchaseRow(barcode="1234567890123", price_raw="9.48",
                        price=9.48, quantity=144, price_flagged=False)
        ]
        with patch("routes_purchase.purchase_service.parse_purchase_excel", return_value=mock_rows):
            response = self.client.post(
                "/purchase/process",
                data={"file": (io.BytesIO(b"fake"), "test.xlsx")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["rows"][0]["barcode"], "1234567890123")
        self.assertEqual(body["rows"][0]["formatted"], "1234567890123,9.48,,144")

    def test_export_requires_file(self):
        response = self.client.post("/purchase/export",
                                    data={"rows": "[]"},
                                    content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)

    def test_export_returns_xlsx(self):
        rows_json = json.dumps([{"formatted": "1234567890123,9.48,,144"}])
        response = self.client.post(
            "/purchase/export",
            data={
                "file": (io.BytesIO(_excel_bytes()), "test.xlsx"),
                "rows": rows_json,
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response.content_type)
