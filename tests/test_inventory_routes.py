"""inventory routes 集成测试。"""

import io
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import stockpile_db
from routes_inventory import bp

_TEST_DIR = Path(__file__).resolve().parent / "_test_inventory_routes"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _BaseRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = _TEST_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.input_dir = self.test_dir / "input"
        self.input_dir.mkdir()
        self._patches = [
            mock.patch.object(stockpile_db, "DB_PATH", self.test_db),
            mock.patch("routes_inventory.INPUT_DIR", self.input_dir),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _upload(self, endpoint: str, fixture_name: str) -> object:
        with open(_FIXTURES / fixture_name, "rb") as f:
            data = f.read()
        return self.client.post(
            endpoint,
            data={"file": (io.BytesIO(data), fixture_name)},
            content_type="multipart/form-data",
        )


class PreviewTests(_BaseRouteTest):
    def test_preview_returns_columns_and_sample(self) -> None:
        rv = self._upload("/inventory/preview", "purchase_sample.xls")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["columns"]), 25)
        self.assertIn("条形码", body["columns"])
        self.assertEqual(body["row_count"], 2)
        self.assertEqual(len(body["sample"]), 2)
        # default_mapping 在响应里供前端预填
        self.assertEqual(body["default_mapping"]["条形码"], "product_barcode")
        # internal_fields 也带回去给前端做下拉选项
        self.assertIn("ignore", body["internal_fields"])

    def test_preview_no_file_400(self) -> None:
        rv = self.client.post("/inventory/preview")
        self.assertEqual(rv.status_code, 400)


class ProfileTests(_BaseRouteTest):
    def test_get_unsaved_profile_returns_default(self) -> None:
        rv = self.client.get("/inventory/profiles/purchase")
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["saved"])
        self.assertEqual(body["mapping"]["条形码"], "product_barcode")

    def test_save_then_get_profile(self) -> None:
        custom = {"产品代码": "product_barcode", "购买数量": "qty", "买家": "partner_name"}
        rv = self.client.post(
            "/inventory/profiles/sales",
            data=json.dumps({"mapping": custom}),
            content_type="application/json",
        )
        self.assertEqual(rv.status_code, 200)
        self.assertTrue(rv.get_json()["saved"])

        rv2 = self.client.get("/inventory/profiles/sales")
        body = rv2.get_json()
        self.assertTrue(body["saved"])
        self.assertEqual(body["mapping"], custom)

    def test_invalid_profile_name_400(self) -> None:
        rv = self.client.get("/inventory/profiles/foobar")
        self.assertEqual(rv.status_code, 400)

    def test_save_profile_with_invalid_target_400(self) -> None:
        rv = self.client.post(
            "/inventory/profiles/purchase",
            data=json.dumps({"mapping": {"列1": "not_a_real_field"}}),
            content_type="application/json",
        )
        self.assertEqual(rv.status_code, 400)
        self.assertIn("not_a_real_field", rv.get_json()["msg"])


class ImportTests(_BaseRouteTest):
    def test_import_purchase_uses_default_mapping_when_no_profile(self) -> None:
        rv = self._upload("/inventory/import/purchase", "purchase_sample.xls")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["rows_imported"], 2)
        self.assertEqual(body["new_suppliers"], 1)
        self.assertEqual(body["new_skus"], 2)

    def test_import_sales_classifies_customers(self) -> None:
        rv = self._upload("/inventory/import/sales", "sales_sample.xls")
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["rows_imported"], 3)
        self.assertEqual(body["new_customers"], 2)

    def test_reimport_idempotent(self) -> None:
        r1 = self._upload("/inventory/import/purchase", "purchase_sample.xls").get_json()
        r2 = self._upload("/inventory/import/purchase", "purchase_sample.xls").get_json()
        self.assertEqual(r1["rows_imported"], 2)
        self.assertEqual(r2["rows_imported"], 0)
        self.assertEqual(r2["rows_skipped_duplicate"], 2)

    def test_invalid_file_type_400(self) -> None:
        rv = self._upload("/inventory/import/transfer", "purchase_sample.xls")
        self.assertEqual(rv.status_code, 400)

    def test_import_no_file_400(self) -> None:
        rv = self.client.post("/inventory/import/purchase")
        self.assertEqual(rv.status_code, 400)


class StatsTests(_BaseRouteTest):
    def test_stats_empty(self) -> None:
        rv = self.client.get("/inventory/stats")
        body = rv.get_json()
        self.assertEqual(body["events_total"], 0)
        self.assertEqual(body["customers_total"], 0)

    def test_stats_after_import(self) -> None:
        self._upload("/inventory/import/sales", "sales_sample.xls")
        rv = self.client.get("/inventory/stats")
        body = rv.get_json()
        self.assertEqual(body["events_total"], 3)
        self.assertEqual(body["events_sale"], 3)
        self.assertEqual(body["customers_total"], 2)
        # 客户类型分布：1 foreign + 1 chinese
        self.assertEqual(body["customers_by_type"]["foreign"], 1)
        self.assertEqual(body["customers_by_type"]["chinese"], 1)


if __name__ == "__main__":
    unittest.main()
