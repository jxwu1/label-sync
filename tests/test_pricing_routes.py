import io
import unittest
from unittest import mock

import openpyxl
from flask import Flask

from app.routes.purchase import bp


class PricingRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.app.testing = True
        self.client = self.app.test_client()

    def test_preview_ok(self):
        payload = {"rows": [{"barcode": "OLD1", "price": 1.05, "quantity": 50}],
                   "new_entries": [], "supplier_id": "S1", "supplier_name": "X"}
        with mock.patch("app.routes.purchase.pricing_sheet.preview_pricing",
                        return_value={"target_margin_pct": 30.0, "n_samples": 3,
                                      "n_new": 0, "n_changed": 1, "skipped_no_baseline": 0}):
            res = self.client.post("/purchase/pricing/preview", json=payload)
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["n_changed"], 1)

    def test_preview_empty_returns_not_ok(self):
        with mock.patch("app.routes.purchase.pricing_sheet.preview_pricing",
                        return_value={"target_margin_pct": None, "n_samples": 0,
                                      "n_new": 0, "n_changed": 0, "skipped_no_baseline": 0}):
            res = self.client.post("/purchase/pricing/preview", json={"rows": []})
        self.assertFalse(res.get_json()["ok"])

    def test_export_returns_xlsx(self):
        wb = openpyxl.Workbook(); buf = io.BytesIO(); wb.save(buf)
        with mock.patch("app.routes.purchase.pricing_sheet.export_pricing_bytes",
                        return_value=buf.getvalue()):
            res = self.client.post("/purchase/pricing/export", json={
                "rows": [], "new_entries": [], "supplier_id": "S1",
                "supplier_name": "雅典X", "target_margin_pct": 30.0})
        self.assertEqual(res.status_code, 200)
        self.assertIn("spreadsheetml", res.headers["Content-Type"])

    def test_export_rejects_bad_margin(self):
        res = self.client.post("/purchase/pricing/export", json={
            "rows": [], "new_entries": [], "supplier_id": "S1",
            "supplier_name": "X", "target_margin_pct": 150})
        self.assertEqual(res.status_code, 400)
