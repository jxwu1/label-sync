"""routes_analytics 单测。HTTP 层薄包装，重点覆盖参数与 404 路径。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask
from sqlalchemy import insert

import stockpile_db
from models import InventoryEvent, Stockpile
from routes_analytics import bp

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_routes_analytics"


class AnalyticsRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()

        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _seed_sku(self, barcode: str = "B1", **fields) -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(Stockpile).values(
                    product_barcode=barcode,
                    product_model=barcode,
                    stockpile_location="",
                    is_active=1,
                    **fields,
                )
            )
            s.commit()

    def _seed_sale(self, barcode: str = "B1", event_at: str = "2026-04-15", qty: int = 10):
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type="sale",
                    product_barcode=barcode,
                    qty=qty,
                    unit_price=2.5,
                    document_no=f"D-{event_at}",
                )
            )
            s.commit()

    def test_unknown_barcode_returns_404(self) -> None:
        resp = self.client.get("/analytics/sku/NOPE")
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()["ok"])

    def test_existing_sku_returns_full_bundle(self) -> None:
        self._seed_sku(
            barcode="B1",
            auto_category="new",
            manual_category=None,
            manual_grade=5,
        )
        self._seed_sale(barcode="B1", event_at="2026-04-15", qty=10)
        resp = self.client.get("/analytics/sku/B1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["barcode"], "B1")
        self.assertIn("sales", data)
        self.assertIn("purchase", data)
        self.assertIn("customer_split", data)
        self.assertEqual(data["auto_category"], "new")
        self.assertEqual(data["manual_grade"], 5)
        # sales metrics 实际有内容
        self.assertEqual(data["sales"]["total_qty"], 10)


if __name__ == "__main__":
    unittest.main()
