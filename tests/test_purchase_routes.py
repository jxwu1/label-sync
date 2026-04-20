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
        response = self.client.post("/purchase/export",
                                    data={"rows": "[]"},
                                    content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)


def _stockpile_bytes():
    return b"c1,c2,c3,barcode\na,b,c,EXIST-IN-SYSTEM\n"


class TestProcessTwoFiles(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_requires_two_files(self):
        response = self.client.post(
            "/purchase/process",
            data={"files": (io.BytesIO(_excel_bytes()), "supplier.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_stockpile_file(self):
        response = self.client.post(
            "/purchase/process",
            data={
                "files": [
                    (io.BytesIO(_excel_bytes()), "supplier.xlsx"),
                    (io.BytesIO(b"x,y"), "other.csv"),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_returns_rows_and_new_barcodes(self):
        response = self.client.post(
            "/purchase/process",
            data={
                "files": [
                    (io.BytesIO(_excel_bytes()), "supplier.xlsx"),
                    (io.BytesIO(_stockpile_bytes()), "stockpile_export.csv"),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["new_barcodes"], ["1234567890123"])
        self.assertIn("EXIST-IN-SYSTEM", body["system_barcodes"])


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
        entries = [{
            "barcode": "NEW1", "name": "测试品", "invoice_name": "发票品名",
            "supplier_id": "S01", "supplier_name": "某供应商",
        }]
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
