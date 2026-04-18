import unittest
from io import BytesIO
from unittest.mock import patch

from flask import Flask

from routes_import import bp


def make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


class TestImportRoutes(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_recognize_requires_files(self):
        response = self.client.post("/import/recognize")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_recognize_calls_service_and_returns_items(self):
        from import_service import ImportItem
        mock_item = ImportItem(barcode="1234567890123", quantity=5, total_price=100.0)
        with patch("routes_import.import_service.recognize_images", return_value=[mock_item]), \
             patch("routes_import.CONFIG") as mock_cfg:
            mock_cfg.gemini_api_key = "test-key"
            response = self.client.post(
                "/import/recognize",
                data={"files": (BytesIO(b"\xff\xd8\xff"), "invoice.jpg")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["barcode"], "1234567890123")

    def test_export_returns_xlsx(self):
        payload = {
            "items": [
                {"barcode": "1234567890123", "quantity": 3, "total_price": 75.0, "unit_price": 25.0}
            ]
        }
        response = self.client.post("/import/export", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response.content_type)

    def test_export_rejects_flagged_items(self):
        payload = {
            "items": [
                {"barcode": None, "quantity": 3, "total_price": 75.0, "unit_price": 25.0}
            ]
        }
        response = self.client.post("/import/export", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
