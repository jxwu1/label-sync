"""recent_changes_service 单测。"""
import shutil
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import insert

import recent_changes_service
import stockpile_db
from models import StockpileChange, StockpileSnapshot

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_recent_changes"


class RecentChangesTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_snapshot(self, taken_at: str, trigger: str = "import", **kwargs) -> int:
        """直接 INSERT snapshot 返回 id。便于测试控制 taken_at。"""
        with stockpile_db._session() as session:
            result = session.execute(
                insert(StockpileSnapshot).values(
                    taken_at=taken_at,
                    trigger=trigger,
                    total_local=kwargs.get("total_local", 0),
                )
            )
            session.commit()
            return result.inserted_primary_key[0]

    def _insert_change(self, barcode: str, field: str, old: str, new: str,
                       change_type: str = "update", created_at: str | None = None) -> None:
        with stockpile_db._session() as session:
            values = {
                "product_barcode": barcode,
                "field_name": field,
                "old_value": old,
                "new_value": new,
                "change_type": change_type,
            }
            if created_at:
                values["created_at"] = created_at
            session.execute(insert(StockpileChange).values(**values))
            session.commit()

    def test_batch_window_first_snapshot_uses_epoch_start(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 10:00:00")
        with stockpile_db._session() as session:
            start, end = recent_changes_service._batch_window(session, snap_id)
        self.assertEqual(start, "1970-01-01 00:00:00")
        self.assertEqual(end, "2026-04-29 10:00:00")

    def test_batch_window_uses_previous_import_taken_at(self) -> None:
        self._insert_snapshot("2026-04-29 10:00:00")
        snap2 = self._insert_snapshot("2026-04-29 14:30:00")
        with stockpile_db._session() as session:
            start, end = recent_changes_service._batch_window(session, snap2)
        self.assertEqual(start, "2026-04-29 10:00:00")
        self.assertEqual(end, "2026-04-29 14:30:00")

    def test_batch_window_skips_non_import_snapshots(self) -> None:
        """compare snapshot 不算批次锚，不能当 prev。"""
        self._insert_snapshot("2026-04-29 10:00:00", trigger="import")
        self._insert_snapshot("2026-04-29 12:00:00", trigger="compare")
        snap3 = self._insert_snapshot("2026-04-29 14:30:00", trigger="import")
        with stockpile_db._session() as session:
            start, end = recent_changes_service._batch_window(session, snap3)
        self.assertEqual(start, "2026-04-29 10:00:00")  # skip compare

    def test_list_recent_imports_returns_only_import_trigger_desc(self) -> None:
        self._insert_snapshot("2026-04-29 10:00:00", trigger="import", total_local=100)
        self._insert_snapshot("2026-04-29 11:00:00", trigger="compare")
        self._insert_snapshot("2026-04-29 14:00:00", trigger="import", total_local=120)
        result = recent_changes_service.list_recent_imports()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["taken_at"], "2026-04-29 14:00:00")  # 最新在前
        self.assertEqual(result[0]["total_local"], 120)
        self.assertEqual(result[1]["total_local"], 100)

    def test_list_recent_imports_counts_changes_in_window(self) -> None:
        snap1 = self._insert_snapshot("2026-04-29 10:00:00")
        self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:30:00")
        self._insert_change("B2", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:45:00")
        snap2 = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change("B3", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

        result = recent_changes_service.list_recent_imports()
        by_id = {r["batch_id"]: r for r in result}
        self.assertEqual(by_id[snap1]["change_count"], 2)
        self.assertEqual(by_id[snap1]["affected_barcodes"], 2)
        self.assertEqual(by_id[snap2]["change_count"], 1)
        self.assertEqual(by_id[snap2]["affected_barcodes"], 1)


if __name__ == "__main__":
    unittest.main()
