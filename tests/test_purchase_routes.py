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

    def test_export_requires_file(self):
        response = self.client.post(
            "/purchase/export", data={"rows": "[]"}, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 400)


class TestProcessSingleFile(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    @patch("routes_purchase.stockpile_db.query_all_barcodes_set")
    def test_single_file_succeeds(self, mock_query):
        mock_query.return_value = {"EXIST-IN-SYSTEM"}
        response = self.client.post(
            "/purchase/process",
            data={"files": (io.BytesIO(_excel_bytes()), "supplier.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["new_barcodes"], ["1234567890123"])
        self.assertIn("EXIST-IN-SYSTEM", body["system_barcodes"])

    @patch("routes_purchase.stockpile_db.query_all_barcodes_set")
    def test_all_existing_returns_no_new(self, mock_query):
        mock_query.return_value = {"1234567890123"}
        response = self.client.post(
            "/purchase/process",
            data={"files": (io.BytesIO(_excel_bytes()), "supplier.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["new_barcodes"], [])


class TestImportToStockpile(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_requires_entries(self):
        response = self.client.post(
            "/purchase/import-to-stockpile",
            json={},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("routes_purchase.purchase_service.import_new_barcodes")
    def test_returns_count_on_success(self, mock_import):
        mock_import.return_value = 3
        response = self.client.post(
            "/purchase/import-to-stockpile",
            json={"entries": [{"barcode": "A"}, {"barcode": "B"}, {"barcode": "C"}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["count"], 3)

    def test_empty_entries_list_400(self):
        response = self.client.post(
            "/purchase/import-to-stockpile",
            json={"entries": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("entries", response.get_json()["msg"])

    def test_entries_not_a_list_400(self):
        # Pydantic 引入的强化：原本 truthy 字符串能通过 `not data.get` 判断、
        # 在 service 里 iterate 报错 → 500；现在边界 400
        response = self.client.post(
            "/purchase/import-to-stockpile",
            json={"entries": "not a list"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class TestExportZip(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_export_no_new_entries_returns_zip_with_only_xlsx(self):
        import zipfile as _z

        response = self.client.post(
            "/purchase/export",
            data={
                "file": (io.BytesIO(_excel_bytes()), "test.xlsx"),
                "rows": json.dumps([{"formatted": "1234567890123,9.48,,144"}]),
                "new_entries": "[]",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/zip")
        with _z.ZipFile(io.BytesIO(response.data)) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("采购订单") and names[0].endswith(".xlsx"))

    def test_export_with_new_entries_returns_zip_with_both(self):
        import zipfile as _z

        entries = [
            {
                "barcode": "NEW1",
                "name": "测试品",
                "invoice_name": "发票品名",
                "supplier_id": "S01",
                "supplier_name": "某供应商",
            }
        ]
        response = self.client.post(
            "/purchase/export",
            data={
                "file": (io.BytesIO(_excel_bytes()), "test.xlsx"),
                "rows": json.dumps([{"formatted": "NEW1,9.48,,144"}]),
                "new_entries": json.dumps(entries),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        with _z.ZipFile(io.BytesIO(response.data)) as zf:
            names = sorted(zf.namelist())
        self.assertEqual(len(names), 2)
        self.assertIn("产品信息导入模板.csv", names)
