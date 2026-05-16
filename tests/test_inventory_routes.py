"""inventory routes 集成测试。"""

import io
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

from app.repositories import stockpile_db
from app.routes.inventory import bp

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
            mock.patch("app.routes.inventory.INPUT_DIR", self.input_dir),
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


class ProductMasterImportRouteTests(_BaseRouteTest):
    def _make_csv(self, rows: list[dict]) -> bytes:
        import pandas as pd

        df = pd.DataFrame(rows)
        return df.to_csv(index=False).encode("utf-8-sig")

    def test_import_product_master_creates_stockpile_and_supplier(self) -> None:
        csv = self._make_csv(
            [
                {
                    "product_barcode": "5828079113422",
                    "product_model": "11342",
                    "product_description": "测试鱼竿",
                    "local_description": "ΚΑΛΑΜΙ",
                    "stockpile_location": "A14-12-01",
                    "product_kind_id": "FL004-01",
                    "product_kind_name": "渔具鱼竿",
                    "valid_grade": 3,
                    "stock_price": 8.5,
                    "sale_price": 15.0,
                    "provider_id": "GR0001",
                    "provider_name": "FORMOPLAST",
                    "web_status": "Y",
                }
            ]
        )
        rv = self.client.post(
            "/inventory/import/product-master",
            data={"file": (io.BytesIO(csv), "product.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["rows_imported"], 1)
        self.assertEqual(body["new_suppliers"], 1)

    def test_import_no_file_400(self) -> None:
        rv = self.client.post("/inventory/import/product-master")
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


class RecentImportsTests(_BaseRouteTest):
    """PR-FE-5b：每次 import 写一行 audit；GET /inventory/imports 返回近期列表。"""

    def test_imports_endpoint_empty_returns_empty_list(self) -> None:
        rv = self.client.get("/inventory/imports")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["imports"], [])

    def test_do_import_writes_audit_row(self) -> None:
        self._upload("/inventory/import/purchase", "purchase_sample.xls")
        rv = self.client.get("/inventory/imports")
        body = rv.get_json()
        self.assertEqual(len(body["imports"]), 1)
        row = body["imports"][0]
        self.assertEqual(row["event_type"], "purchase")
        self.assertEqual(row["filename"], "purchase_sample.xls")
        self.assertEqual(row["ok_count"], 2)
        self.assertEqual(row["dup_count"], 0)
        self.assertEqual(row["error_count"], 0)
        self.assertEqual(row["operator"], "admin")
        self.assertIn("imported_at", row)

    def test_imports_endpoint_returns_recent_desc(self) -> None:
        self._upload("/inventory/import/purchase", "purchase_sample.xls")
        self._upload("/inventory/import/sales", "sales_sample.xls")
        rv = self.client.get("/inventory/imports")
        body = rv.get_json()
        self.assertEqual(len(body["imports"]), 2)
        # 最新（sales）在前
        self.assertEqual(body["imports"][0]["event_type"], "sale")
        self.assertEqual(body["imports"][1]["event_type"], "purchase")

    def test_reimport_records_dup_count(self) -> None:
        self._upload("/inventory/import/purchase", "purchase_sample.xls")
        self._upload("/inventory/import/purchase", "purchase_sample.xls")
        rv = self.client.get("/inventory/imports")
        body = rv.get_json()
        # 第二次（同文件）→ dup=2 ok=0
        self.assertEqual(body["imports"][0]["dup_count"], 2)
        self.assertEqual(body["imports"][0]["ok_count"], 0)


if __name__ == "__main__":
    unittest.main()
