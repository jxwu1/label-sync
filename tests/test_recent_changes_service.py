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

    def _insert_change(
        self,
        barcode: str,
        field: str,
        old: str,
        new: str,
        change_type: str = "update",
        created_at: str | None = None,
    ) -> None:
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
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:30:00"
        )
        self._insert_change(
            "B2", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:45:00"
        )
        snap2 = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B3", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )

        result = recent_changes_service.list_recent_imports()
        by_id = {r["batch_id"]: r for r in result}
        self.assertEqual(by_id[snap1]["change_count"], 2)
        self.assertEqual(by_id[snap1]["affected_barcodes"], 2)
        self.assertEqual(by_id[snap2]["change_count"], 1)
        self.assertEqual(by_id[snap2]["affected_barcodes"], 1)

    def test_open_batch_appears_when_changes_after_last_snapshot(self) -> None:
        """上次 import 之后有 changes（标签修改 / 单条修正）→ 顶部加开放批次。"""
        self._insert_snapshot("2026-04-29 10:00:00", trigger="import", total_local=100)
        # 这条 change 在最后 snapshot 之后，没新 snapshot 闭合窗口
        self._insert_change(
            "B1", "stockpile_location", "A1", "B7", created_at="2026-04-29 12:30:00"
        )
        self._insert_change(
            "B2", "stockpile_location", "A2", "C5", created_at="2026-04-29 13:00:00"
        )

        result = recent_changes_service.list_recent_imports()
        # 顶部是开放批次
        self.assertEqual(result[0]["batch_id"], -1)
        self.assertTrue(result[0]["is_open"])
        self.assertEqual(result[0]["change_count"], 2)
        self.assertEqual(result[0]["affected_barcodes"], 2)
        self.assertEqual(result[0]["taken_at"], "2026-04-29 13:00:00")  # 最后 change 时间
        self.assertIsNone(result[0]["total_local"])
        # 已闭合批次仍在
        self.assertEqual(len(result), 2)

    def test_open_batch_not_in_list_when_no_post_snapshot_changes(self) -> None:
        """所有 changes 都在 snapshot 之前 → 不该有开放批次。"""
        self._insert_change("B1", "stockpile_location", "A", "B", created_at="2026-04-29 09:00:00")
        self._insert_snapshot("2026-04-29 10:00:00", trigger="import", total_local=100)

        result = recent_changes_service.list_recent_imports()
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result[0]["batch_id"], -1)
        self.assertFalse(result[0]["is_open"])

    def test_open_batch_window_start_at_last_import(self) -> None:
        """开放批次的 window_start = 最近一次 import snapshot taken_at。"""
        self._insert_snapshot("2026-04-29 08:00:00", trigger="import")
        self._insert_snapshot("2026-04-29 10:00:00", trigger="import")
        with stockpile_db._session() as session:
            start, end = recent_changes_service._batch_window(session, -1)
        self.assertEqual(start, "2026-04-29 10:00:00")
        # end 是 far future（不限定上限）
        self.assertTrue(end.startswith("9999"))

    def test_open_batch_window_no_snapshot_uses_epoch(self) -> None:
        """没有任何 snapshot 时 → 开放窗口 = (epoch, far_future) 收所有 changes。"""
        with stockpile_db._session() as session:
            start, end = recent_changes_service._batch_window(session, -1)
        self.assertEqual(start, "1970-01-01 00:00:00")
        self.assertTrue(end.startswith("9999"))

    def test_open_batch_summary_and_changes_work(self) -> None:
        """get_batch_summary(-1) 和 get_batch_changes(-1) 应该正常返回开放窗口的数据。"""
        self._insert_snapshot("2026-04-29 08:00:00", trigger="import")
        self._insert_change(
            "B1", "stockpile_location", "A1", "B7", created_at="2026-04-29 09:30:00"
        )
        self._insert_change("B2", "product_model", "M1", "M2", created_at="2026-04-29 10:00:00")

        s = recent_changes_service.get_batch_summary(-1)
        self.assertEqual(s["location_changes"], 1)
        self.assertEqual(s["model_changes"], 1)

        changes = recent_changes_service.get_batch_changes(-1, mode="raw")
        self.assertEqual(len(changes), 2)

    def test_get_batch_summary_counts_by_field_and_change_type(self) -> None:
        """5 个数字 + roundtrip count。所有按 (barcode, field) 维度。"""
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        base = "2026-04-29 13:"
        # B1 location 单变 → location_changes +1
        self._insert_change("B1", "stockpile_location", "A1", "A2", created_at=base + "01:00")
        # B2 location 来回（A→B→A）→ roundtrip
        self._insert_change("B2", "stockpile_location", "A1", "A2", created_at=base + "02:00")
        self._insert_change("B2", "stockpile_location", "A2", "A1", created_at=base + "02:30")
        # B3 model 变 → model_changes +1
        self._insert_change("B3", "product_model", "M1", "M2", created_at=base + "03:00")
        # B4 insert → inserts +1
        self._insert_change(
            "B4", "product_barcode", None, "B4", "insert", created_at=base + "04:00"
        )
        # B5 deactivate
        self._insert_change("B5", "is_active", "1", "0", "deactivate", created_at=base + "05:00")
        # B6 reactivate
        self._insert_change("B6", "is_active", "0", "1", "reactivate", created_at=base + "06:00")

        s = recent_changes_service.get_batch_summary(snap_id)
        self.assertEqual(s["location_changes"], 1)
        self.assertEqual(s["model_changes"], 1)
        self.assertEqual(s["inserts"], 1)
        self.assertEqual(s["deactivates"], 1)
        self.assertEqual(s["reactivates"], 1)
        self.assertEqual(s["roundtrip_count"], 1)  # B2 location

    def test_get_batch_summary_excludes_changes_outside_window(self) -> None:
        self._insert_snapshot("2026-04-29 10:00:00")  # prev import
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        # 这条在 prev 之前，不该算
        self._insert_change(
            "B0", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:00:00"
        )
        # 这条在窗口内
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )

        s = recent_changes_service.get_batch_summary(snap_id)
        self.assertEqual(s["location_changes"], 1)

    def test_get_batch_changes_collapsed_single_change(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["barcode"], "B1")
        self.assertEqual(rows[0]["field"], "stockpile_location")
        self.assertEqual(rows[0]["from_value"], "A1")
        self.assertEqual(rows[0]["to_value"], "A2")

    def test_get_batch_changes_collapsed_roundtrip_excluded(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        self._insert_change(
            "B1", "stockpile_location", "A2", "A1", created_at="2026-04-29 13:30:00"
        )
        rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
        self.assertEqual(rows, [])

    def test_get_batch_changes_collapsed_multi_step_keeps_endpoints(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        self._insert_change(
            "B1", "stockpile_location", "A2", "A3", created_at="2026-04-29 13:30:00"
        )
        rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["from_value"], "A1")
        self.assertEqual(rows[0]["to_value"], "A3")

    def test_get_batch_changes_collapsed_multi_field_split_rows(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        self._insert_change("B1", "product_model", "M1", "M2", created_at="2026-04-29 13:01:00")
        rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
        self.assertEqual(len(rows), 2)
        fields = sorted(r["field"] for r in rows)
        self.assertEqual(fields, ["product_model", "stockpile_location"])

    def test_get_batch_changes_collapsed_sorted_by_latest_event_desc(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        self._insert_change(
            "B2", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:30:00"
        )
        rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
        self.assertEqual([r["barcode"] for r in rows], ["B2", "B1"])  # B2 更晚

    def test_get_batch_changes_raw_returns_all_rows_with_intermediate_steps(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        self._insert_change(
            "B1", "stockpile_location", "A2", "A1", created_at="2026-04-29 13:30:00"
        )
        rows = recent_changes_service.get_batch_changes(snap_id, mode="raw")
        self.assertEqual(len(rows), 2)  # raw 不剔除 roundtrip
        # 倒序：最新在前
        self.assertEqual(rows[0]["new_value"], "A1")
        self.assertEqual(rows[1]["new_value"], "A2")

    def test_get_batch_changes_filter_by_field(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        self._insert_change("B2", "product_model", "M1", "M2", created_at="2026-04-29 13:01:00")
        rows = recent_changes_service.get_batch_changes(
            snap_id, mode="collapsed", filter_field="stockpile_location"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["barcode"], "B1")

    def test_get_batch_changes_filter_by_change_type(self) -> None:
        snap_id = self._insert_snapshot("2026-04-29 14:00:00")
        self._insert_change(
            "B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00"
        )
        self._insert_change(
            "B2", "product_barcode", None, "B2", "insert", created_at="2026-04-29 13:01:00"
        )
        rows = recent_changes_service.get_batch_changes(
            snap_id, mode="raw", filter_change_type="insert"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["barcode"], "B2")


if __name__ == "__main__":
    unittest.main()
