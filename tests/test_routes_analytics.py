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
        values = {
            "product_barcode": barcode,
            "product_model": barcode,
            "stockpile_location": "",
            "is_active": 1,
        }
        values.update(fields)
        with stockpile_db._session() as s:
            s.execute(insert(Stockpile).values(**values))
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
        self.assertIn("qty_percentile", data)
        self.assertEqual(data["auto_category"], "new")
        self.assertEqual(data["manual_grade"], 5)
        # sales metrics 实际有内容
        self.assertEqual(data["sales"]["total_qty"], 10)

    def test_qty_percentile_lowest(self) -> None:
        """3 个 SKU 销量 1/5/10：销 1 的那个是底部 → 0%。"""
        self._seed_sku("LOW", manual_grade=8)  # 高等级低销 → 等级失真
        self._seed_sku("MID")
        self._seed_sku("HIGH")
        self._seed_sale("LOW", "2026-04-15", 1)
        self._seed_sale("MID", "2026-04-15", 5)
        self._seed_sale("HIGH", "2026-04-15", 10)

        resp = self.client.get("/analytics/sku/LOW")
        data = resp.get_json()
        self.assertEqual(data["qty_percentile"], 0.0)

        resp = self.client.get("/analytics/sku/HIGH")
        data = resp.get_json()
        # 比 1 + 5 都大 = 2/3 = 66.7%
        self.assertAlmostEqual(data["qty_percentile"], 66.7, places=1)


class ManualCategoryTests(AnalyticsRoutesTests):
    def test_set_valid_category(self) -> None:
        self._seed_sku("B1")
        resp = self.client.post(
            "/analytics/sku/B1/manual-category",
            json={"category": "网红昙花"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["manual_category"], "网红昙花")

        # 复查 GET
        resp = self.client.get("/analytics/sku/B1")
        self.assertEqual(resp.get_json()["manual_category"], "网红昙花")

    def test_clear_with_empty_string(self) -> None:
        self._seed_sku("B1", manual_category="滞销")
        resp = self.client.post(
            "/analytics/sku/B1/manual-category",
            json={"category": ""},
        )
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIsNone(data["manual_category"])

    def test_invalid_category_returns_400(self) -> None:
        self._seed_sku("B1")
        resp = self.client.post(
            "/analytics/sku/B1/manual-category",
            json={"category": "随便编一个"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_unknown_barcode_returns_404(self) -> None:
        resp = self.client.post(
            "/analytics/sku/NOPE/manual-category",
            json={"category": "滞销"},
        )
        self.assertEqual(resp.status_code, 404)


class ListEndpointTests(AnalyticsRoutesTests):
    def test_list_returns_active_skus_with_aggregates(self) -> None:
        self._seed_sku("B1", auto_category="stable", manual_grade=5)
        self._seed_sku("B2", auto_category="new")
        self._seed_sku("B3", is_active=0)  # 应被过滤
        self._seed_sale("B1", "2026-04-01", 10)
        self._seed_sale("B1", "2026-04-15", 5)
        self._seed_sale("B2", "2026-04-25", 100)

        resp = self.client.get("/analytics/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        bcs = {it["barcode"] for it in data["items"]}
        self.assertEqual(bcs, {"B1", "B2"})
        b1 = next(it for it in data["items"] if it["barcode"] == "B1")
        self.assertEqual(b1["total_qty"], 15)
        self.assertEqual(b1["lifespan_days"], 14)

    def test_list_grade_inconsistent_flag(self) -> None:
        # 高等级低销 → warn
        self._seed_sku("HI_GRADE_LOW_SALES", manual_grade=9)
        self._seed_sku("MID_QTY")
        self._seed_sale("HI_GRADE_LOW_SALES", "2026-04-01", 1)
        self._seed_sale("MID_QTY", "2026-04-01", 100)

        resp = self.client.get("/analytics/list")
        items = resp.get_json()["items"]
        hi = next(it for it in items if it["barcode"] == "HI_GRADE_LOW_SALES")
        # 1 件 → 排在 0% 分位（mid_qty 100 件比它多）
        self.assertEqual(hi["qty_percentile"], 0.0)
        self.assertTrue(hi["is_grade_inconsistent"])


if __name__ == "__main__":
    unittest.main()
