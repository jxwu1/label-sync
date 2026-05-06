"""recent_changes routes 单测：HTTP 层薄包装，重点覆盖参数解析与错误。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask
from sqlalchemy import insert

import stockpile_db
from models import StockpileChange, StockpileSnapshot
from routes_recent_changes import bp

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_recent_changes_routes"


class RecentChangesRoutesTests(unittest.TestCase):
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

    def _seed(self) -> int:
        with stockpile_db._session() as session:
            r = session.execute(
                insert(StockpileSnapshot).values(
                    taken_at="2026-04-29 14:00:00",
                    trigger="import",
                    total_local=10,
                )
            )
            sid = r.inserted_primary_key[0]
            session.execute(
                insert(StockpileChange).values(
                    product_barcode="B1",
                    field_name="stockpile_location",
                    old_value="A1",
                    new_value="A2",
                    change_type="update",
                    created_at="2026-04-29 13:00:00",
                )
            )
            session.commit()
        return sid

    def test_imports_endpoint(self) -> None:
        self._seed()
        resp = self.client.get("/recent_changes/imports")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["imports"]), 1)

    def test_summary_endpoint(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/summary")
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["location_changes"], 1)

    def test_changes_endpoint_collapsed_default(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/changes")
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["changes"]), 1)
        self.assertEqual(data["changes"][0]["from_value"], "A1")

    def test_changes_endpoint_raw_mode(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/changes?mode=raw")
        data = resp.get_json()
        self.assertEqual(len(data["changes"]), 1)
        self.assertEqual(data["changes"][0]["new_value"], "A2")

    def test_changes_endpoint_invalid_mode_returns_400(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/changes?mode=garbage")
        self.assertEqual(resp.status_code, 400)

    def test_summary_open_batch_negative_id(self) -> None:
        """开放批次 batch_id=-1 不能被 Flask 默认 <int:> 拒掉。"""
        # seed 一个 import snapshot + 之后的 change（构造开放批次）
        with stockpile_db._session() as session:
            from sqlalchemy import insert as sa_insert

            session.execute(
                sa_insert(StockpileSnapshot).values(
                    taken_at="2026-04-29 10:00:00", trigger="import", total_local=100
                )
            )
            session.execute(
                sa_insert(StockpileChange).values(
                    product_barcode="B1",
                    field_name="stockpile_location",
                    old_value="A1",
                    new_value="A2",
                    change_type="update",
                    created_at="2026-04-29 12:00:00",
                )
            )
            session.commit()

        resp = self.client.get("/recent_changes/-1/summary")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["summary"]["location_changes"], 1)

    def test_changes_open_batch_negative_id(self) -> None:
        with stockpile_db._session() as session:
            from sqlalchemy import insert as sa_insert

            session.execute(
                sa_insert(StockpileSnapshot).values(
                    taken_at="2026-04-29 10:00:00", trigger="import", total_local=100
                )
            )
            session.execute(
                sa_insert(StockpileChange).values(
                    product_barcode="B1",
                    field_name="stockpile_location",
                    old_value="A1",
                    new_value="A2",
                    change_type="update",
                    created_at="2026-04-29 12:00:00",
                )
            )
            session.commit()

        resp = self.client.get("/recent_changes/-1/changes?mode=raw")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["changes"]), 1)

    def test_invalid_batch_id_string_returns_400(self) -> None:
        resp = self.client.get("/recent_changes/not_a_number/summary")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
