"""数据新鲜度 (#1): max(InventoryEvent.imported_at) 反映 scraper 最后一次灌数。

周抓一次, 距今 > 9 天判定 stale (至少漏了一轮)。
"""

from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import insert

from app.models import InventoryEvent
from app.repositories import stockpile_db


class _Base(unittest.TestCase):
    # DB 隔离由 conftest autouse _isolate_db 负责（unified engine 指向 tmp db_path）

    def _add_event(self, imported_at: str, *, barcode: str = "B1") -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at="2026-05-01",
                    event_type="sale",
                    product_barcode=barcode,
                    qty=1,
                    imported_at=imported_at,
                )
            )
            s.commit()


class TestDataFreshness(_Base):
    def test_empty_db_not_stale_no_date(self) -> None:
        """空库: 无数据不报 stale 红条(避免本地/新系统误报), 日期为 None。"""
        from app.services.analytics import get_data_freshness

        r = get_data_freshness(as_of=date(2026, 6, 3))
        self.assertIsNone(r["last_import_date"])
        self.assertIsNone(r["days_since"])
        self.assertFalse(r["stale"])

    def test_recent_import_fresh(self) -> None:
        from app.services.analytics import get_data_freshness

        self._add_event("2026-06-03 08:00:00")
        r = get_data_freshness(as_of=date(2026, 6, 3))
        self.assertEqual(r["last_import_date"], "2026-06-03")
        self.assertEqual(r["days_since"], 0)
        self.assertFalse(r["stale"])

    def test_uses_latest_imported_at(self) -> None:
        from app.services.analytics import get_data_freshness

        self._add_event("2026-05-01 08:00:00", barcode="OLD")
        self._add_event("2026-05-30 09:00:00", barcode="NEW")
        r = get_data_freshness(as_of=date(2026, 6, 3))
        self.assertEqual(r["last_import_date"], "2026-05-30")
        self.assertEqual(r["days_since"], 4)
        self.assertFalse(r["stale"])

    def test_boundary_9_days_not_stale(self) -> None:
        from app.services.analytics import get_data_freshness

        self._add_event("2026-05-25 08:00:00")  # 距 6-03 = 9 天
        r = get_data_freshness(as_of=date(2026, 6, 3))
        self.assertEqual(r["days_since"], 9)
        self.assertFalse(r["stale"])

    def test_10_days_is_stale(self) -> None:
        from app.services.analytics import get_data_freshness

        self._add_event("2026-05-24 08:00:00")  # 距 6-03 = 10 天
        r = get_data_freshness(as_of=date(2026, 6, 3))
        self.assertEqual(r["days_since"], 10)
        self.assertTrue(r["stale"])


class TestDataFreshnessRoute(_Base):
    def setUp(self) -> None:
        super().setUp()
        from flask import Flask

        from app.routes.analytics import bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(bp)
        self.client = app.test_client()

    def test_endpoint_returns_freshness_shape(self) -> None:
        self._add_event("2026-06-03 08:00:00")
        resp = self.client.get("/analytics/data-freshness")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["last_import_date"], "2026-06-03")
        self.assertIsInstance(body["days_since"], int)
        self.assertIn("stale", body)

    def test_endpoint_empty_db(self) -> None:
        resp = self.client.get("/analytics/data-freshness")
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIsNone(body["last_import_date"])
        self.assertFalse(body["stale"])


if __name__ == "__main__":
    unittest.main()
