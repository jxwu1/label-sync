import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import stockpile_db

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_stockpile_db"


def _clean_tables() -> None:
    stockpile_db.ensure_db()
    conn = stockpile_db._connect()
    conn.execute("DELETE FROM stockpile")
    conn.execute("DELETE FROM stockpile_changes")
    conn.execute("DELETE FROM schema_meta")
    conn.commit()
    conn.close()


class StockpileDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / f"_test_stockpile_db_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test_stockpile.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        _clean_tables()

    def tearDown(self) -> None:
        _clean_tables()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_ensure_db_creates_tables(self) -> None:
        stockpile_db.ensure_db()
        with stockpile_db._connect() as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row["name"] for row in cur]
        self.assertIn("stockpile", tables)
        self.assertIn("stockpile_changes", tables)
        self.assertIn("schema_meta", tables)

    def test_ensure_db_creates_is_active_column(self) -> None:
        stockpile_db.ensure_db()
        with stockpile_db._connect() as conn:
            cur = conn.execute("PRAGMA table_info(stockpile)")
            columns = {row["name"] for row in cur}
        self.assertIn("is_active", columns)

    def test_get_schema_version_returns_current_version(self) -> None:
        stockpile_db.ensure_db()
        self.assertEqual(stockpile_db.get_schema_version(), stockpile_db.SCHEMA_VERSION)

    def test_is_initialized_returns_false_for_empty_db(self) -> None:
        stockpile_db.ensure_db()
        self.assertFalse(stockpile_db.is_initialized())

    def test_is_initialized_returns_true_after_import(self) -> None:
        df = pd.DataFrame(
            [{"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"}]
        )
        stockpile_db.import_from_dataframe(df)
        self.assertTrue(stockpile_db.is_initialized())

    def test_import_from_dataframe_inserts_records(self) -> None:
        df = pd.DataFrame(
            [
                {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
            ]
        )
        count = stockpile_db.import_from_dataframe(df)
        self.assertEqual(count, 2)
        self.assertEqual(stockpile_db.count_records(), 2)

    def test_import_handles_extra_columns_in_json(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "product_barcode": "A1",
                    "product_model": "M1",
                    "stockpile_location": "L1",
                    "price": "100",
                    "stock": "50",
                }
            ]
        )
        stockpile_db.import_from_dataframe(df)
        record = stockpile_db.query_by_barcode("A1")
        self.assertIsNotNone(record)
        extra = json.loads(record["extra"])
        self.assertEqual(extra["price"], "100")
        self.assertEqual(extra["stock"], "50")

    def test_import_skip_nan_barcode(self) -> None:
        df = pd.DataFrame(
            [{"product_barcode": float("nan"), "product_model": "M1", "stockpile_location": "L1"}]
        )
        count = stockpile_db.import_from_dataframe(df)
        self.assertEqual(count, 0)

    def test_query_by_barcode_returns_none_for_missing(self) -> None:
        self.assertIsNone(stockpile_db.query_by_barcode("NOPE"))

    def test_query_by_barcode_returns_record(self) -> None:
        df = pd.DataFrame(
            [{"product_barcode": "X99", "product_model": "MX", "stockpile_location": "LX"}]
        )
        stockpile_db.import_from_dataframe(df)
        record = stockpile_db.query_by_barcode("X99")
        self.assertIsNotNone(record)
        self.assertEqual(record["product_model"], "MX")
        self.assertEqual(record["is_active"], 1)

    def test_query_all_as_system_records_returns_maps(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "product_barcode": "111",
                    "product_model": "M-111",
                    "stockpile_location": "A-01-01/X-01-01",
                },
                {
                    "product_barcode": "222",
                    "product_model": "M-222",
                    "stockpile_location": "B-02-02",
                },
            ]
        )
        stockpile_db.import_from_dataframe(df)
        barcode_model_map, system_records = stockpile_db.query_all_as_system_records()
        self.assertEqual(barcode_model_map["111"], "M-111")
        self.assertEqual(system_records["111"]["stockpile_location"], "A-01-01/X-01-01")
        self.assertEqual(system_records["222"]["model"], "M-222")
        self.assertNotIn("333", system_records)

    def test_insert_or_update_inserts_new(self) -> None:
        stockpile_db.insert_or_update("NEW1", "ModelNew", "LocNew", source="scan_new")
        record = stockpile_db.query_by_barcode("NEW1")
        self.assertEqual(record["product_model"], "ModelNew")
        self.assertEqual(record["source"], "scan_new")

    def test_insert_or_update_updates_existing(self) -> None:
        df = pd.DataFrame(
            [{"product_barcode": "U1", "product_model": "Old", "stockpile_location": "OldLoc"}]
        )
        stockpile_db.import_from_dataframe(df)
        stockpile_db.insert_or_update("U1", "New", "NewLoc", source="user_correction")
        record = stockpile_db.query_by_barcode("U1")
        self.assertEqual(record["product_model"], "New")
        self.assertEqual(record["source"], "user_correction")

    def test_changes_logged_on_update(self) -> None:
        df = pd.DataFrame(
            [{"product_barcode": "C1", "product_model": "Old", "stockpile_location": "OldLoc"}]
        )
        stockpile_db.import_from_dataframe(df)
        stockpile_db.insert_or_update("C1", "New", "NewLoc")

        conn = stockpile_db._connect()
        cur = conn.execute("SELECT * FROM stockpile_changes WHERE product_barcode = ?", ("C1",))
        changes = cur.fetchall()
        conn.close()
        self.assertGreaterEqual(len(changes), 1)

    def test_query_all_barcodes_set(self) -> None:
        df = pd.DataFrame(
            [
                {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "L1"},
                {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "L2"},
            ]
        )
        stockpile_db.import_from_dataframe(df)
        result = stockpile_db.query_all_barcodes_set()
        self.assertEqual(result, {"B1", "B2"})

    def test_compare_with_dataframe_finds_matches_and_mismatches(self) -> None:
        df_local = pd.DataFrame(
            [
                {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "A/X"},
                {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "B/Y"},
            ]
        )
        stockpile_db.import_from_dataframe(df_local)

        df_export = pd.DataFrame(
            [
                {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "A/X"},
                {
                    "product_barcode": "A2",
                    "product_model": "M2_CHANGED",
                    "stockpile_location": "B/Y",
                },
                {"product_barcode": "A3", "product_model": "M3", "stockpile_location": "C/Z"},
            ]
        )
        result = stockpile_db.compare_with_dataframe(df_export)
        self.assertEqual(result["total_local"], 2)
        self.assertEqual(result["total_export"], 3)
        self.assertEqual(result["only_in_local"], [])
        self.assertEqual(result["only_in_export"], ["A3"])
        # model diff = substantive
        self.assertEqual(len(result["substantive_mismatches"]), 1)
        self.assertEqual(result["substantive_mismatches"][0]["barcode"], "A2")
        self.assertEqual(len(result["cosmetic_mismatches"]), 0)
        # 向后兼容 mismatches = 并集
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertEqual(result["consistent"], 1)
        self.assertFalse(result["alert"])  # 1 < 3

    def test_compare_classifies_trailing_space_as_cosmetic(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": "B1",
                        "product_model": "M1",
                        "stockpile_location": "A22/X11",
                    },
                ]
            )
        )
        # 老系统老导出有空格；本地是干净版
        result = stockpile_db.compare_with_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": "B1",
                        "product_model": "M1",
                        "stockpile_location": "A22 /X11",
                    },
                ]
            )
        )
        self.assertEqual(len(result["cosmetic_mismatches"]), 1)
        self.assertEqual(len(result["substantive_mismatches"]), 0)
        self.assertEqual(result["consistent"], 0)

    def test_compare_classifies_real_location_change_as_substantive(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": "B1",
                        "product_model": "M1",
                        "stockpile_location": "A22/X11",
                    },
                ]
            )
        )
        result = stockpile_db.compare_with_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": "B1",
                        "product_model": "M1",
                        "stockpile_location": "B13/X11",
                    },
                ]
            )
        )
        self.assertEqual(len(result["cosmetic_mismatches"]), 0)
        self.assertEqual(len(result["substantive_mismatches"]), 1)

    def test_compare_segment_order_difference_is_substantive(self) -> None:
        """段顺序不同视为 substantive（用户决定：店面在前/仓库在后是契约，乱序就是数据错）。"""
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": "B1",
                        "product_model": "M1",
                        "stockpile_location": "A22/X11",
                    },
                ]
            )
        )
        result = stockpile_db.compare_with_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": "B1",
                        "product_model": "M1",
                        "stockpile_location": "X11/A22",
                    },
                ]
            )
        )
        self.assertEqual(len(result["substantive_mismatches"]), 1)
        self.assertEqual(len(result["cosmetic_mismatches"]), 0)

    def test_compare_alert_fires_at_threshold(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": f"B{i}",
                        "product_model": f"M{i}",
                        "stockpile_location": "A22",
                    }
                    for i in range(5)
                ]
            )
        )
        # 3 条 substantive
        result = stockpile_db.compare_with_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "B0", "product_model": "M0", "stockpile_location": "B13"},
                    {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "B13"},
                    {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "B13"},
                    {"product_barcode": "B3", "product_model": "M3", "stockpile_location": "A22"},
                    {"product_barcode": "B4", "product_model": "M4", "stockpile_location": "A22"},
                ]
            )
        )
        self.assertEqual(len(result["substantive_mismatches"]), 3)
        self.assertTrue(result["alert"])

    def test_compare_takes_snapshot(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22"},
                ]
            )
        )
        stockpile_db.compare_with_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "B13"},
                ]
            )
        )
        snaps = stockpile_db.list_snapshots()
        # 至少有 1 个 import 快照 + 1 个 compare 快照
        triggers = [s["trigger"] for s in snaps]
        self.assertIn("import", triggers)
        self.assertIn("compare", triggers)
        compare_snap = next(s for s in snaps if s["trigger"] == "compare")
        self.assertEqual(compare_snap["substantive_count"], 1)
        self.assertEqual(compare_snap["cosmetic_count"], 0)

    def test_extra_excludes_nan_strings(self) -> None:
        # A3: NaN 输入应清洗为 ""，不应在 extra JSON 中保留 "nan" 字面串
        df = pd.DataFrame(
            [
                {
                    "product_barcode": "E1",
                    "product_model": "M",
                    "stockpile_location": "L",
                    "price": float("nan"),
                    "stock": "5",
                }
            ]
        )
        stockpile_db.import_from_dataframe(df)
        record = stockpile_db.query_by_barcode("E1")
        extra = json.loads(record["extra"])
        self.assertEqual(extra["price"], "")
        self.assertEqual(extra["stock"], "5")

    def test_initial_import_logs_inserts(self) -> None:
        # A2: 初次 import 也走 _upsert，应记录 insert 审计
        df = pd.DataFrame(
            [{"product_barcode": "I1", "product_model": "M", "stockpile_location": "L"}]
        )
        stockpile_db.import_from_dataframe(df)
        with stockpile_db._connect() as conn:
            cur = conn.execute(
                "SELECT change_type FROM stockpile_changes WHERE product_barcode = ?", ("I1",)
            )
            types = [row["change_type"] for row in cur]
        self.assertIn("insert", types)

    def test_reimport_logs_field_updates(self) -> None:
        # A2: 二次 import 修改了字段，应记录 update
        df1 = pd.DataFrame(
            [{"product_barcode": "R1", "product_model": "Old", "stockpile_location": "L"}]
        )
        stockpile_db.import_from_dataframe(df1)
        df2 = pd.DataFrame(
            [{"product_barcode": "R1", "product_model": "New", "stockpile_location": "L"}]
        )
        stockpile_db.import_from_dataframe(df2)
        with stockpile_db._connect() as conn:
            cur = conn.execute(
                "SELECT field_name, old_value, new_value FROM stockpile_changes "
                "WHERE product_barcode = ? AND change_type = 'update'",
                ("R1",),
            )
            updates = list(cur)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["field_name"], "product_model")
        self.assertEqual(updates[0]["old_value"], "Old")
        self.assertEqual(updates[0]["new_value"], "New")

    def test_compare_with_empty_local_db(self) -> None:
        df_export = pd.DataFrame(
            [
                {"product_barcode": "X1", "product_model": "M", "stockpile_location": "L"},
            ]
        )
        result = stockpile_db.compare_with_dataframe(df_export)
        self.assertEqual(result["total_local"], 0)
        self.assertEqual(result["total_export"], 1)
        self.assertEqual(result["only_in_export"], ["X1"])
        self.assertEqual(result["only_in_local"], [])
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["cosmetic_mismatches"], [])
        self.assertEqual(result["substantive_mismatches"], [])
        self.assertEqual(result["consistent"], 0)

    def test_apply_export_logs_inserts_for_new_records(self) -> None:
        df = pd.DataFrame(
            [
                {"product_barcode": "AE1", "product_model": "M", "stockpile_location": "L"},
            ]
        )
        stockpile_db.apply_export_updates(df)
        with stockpile_db._connect() as conn:
            cur = conn.execute(
                "SELECT change_type FROM stockpile_changes WHERE product_barcode = ?", ("AE1",)
            )
            types = [r["change_type"] for r in cur]
        self.assertIn("insert", types)

    def test_apply_export_persists_extra_cols(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "product_barcode": "AE2",
                    "product_model": "M",
                    "stockpile_location": "L",
                    "price": "99",
                    "stock": "12",
                }
            ]
        )
        stockpile_db.apply_export_updates(df)
        record = stockpile_db.query_by_barcode("AE2")
        extra = json.loads(record["extra"])
        self.assertEqual(extra["price"], "99")
        self.assertEqual(extra["stock"], "12")

    def test_apply_export_updates_overwrites_local(self) -> None:
        df_local = pd.DataFrame(
            [
                {"product_barcode": "X1", "product_model": "Old", "stockpile_location": "OldLoc"},
            ]
        )
        stockpile_db.import_from_dataframe(df_local)

        df_export = pd.DataFrame(
            [
                {"product_barcode": "X1", "product_model": "New", "stockpile_location": "NewLoc"},
                {"product_barcode": "X2", "product_model": "Fresh", "stockpile_location": "F/Loc"},
            ]
        )
        updated = stockpile_db.apply_export_updates(df_export)
        self.assertEqual(updated, 2)

        r1 = stockpile_db.query_by_barcode("X1")
        self.assertEqual(r1["product_model"], "New")
        self.assertEqual(r1["source"], "system_export")

        r2 = stockpile_db.query_by_barcode("X2")
        self.assertIsNotNone(r2)

    def test_import_from_dataframe_deactivates_missing_records(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                    {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
                ]
            )
        )

        imported = stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )

        self.assertEqual(imported, 1)
        self.assertEqual(stockpile_db.count_records(), 1)
        self.assertEqual(stockpile_db.query_all_barcodes_set(), {"A1"})
        removed = stockpile_db.query_by_barcode("A2")
        self.assertIsNotNone(removed)
        self.assertEqual(removed["is_active"], 0)

    def test_apply_export_updates_deactivates_missing_records(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                    {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
                ]
            )
        )

        updated = stockpile_db.apply_export_updates(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )

        self.assertEqual(updated, 1)
        self.assertEqual(stockpile_db.count_records(), 1)
        self.assertEqual(stockpile_db.query_all_barcodes_set(), {"A1"})
        inactive = stockpile_db.query_by_barcode("A2")
        self.assertIsNotNone(inactive)
        self.assertEqual(inactive["is_active"], 0)

    def test_insert_or_update_reactivates_inactive_record(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )
        stockpile_db.apply_export_updates(pd.DataFrame([]))

        stockpile_db.insert_or_update("A1", "M1-new", "L1-new")

        record = stockpile_db.query_by_barcode("A1")
        self.assertIsNotNone(record)
        self.assertEqual(record["is_active"], 1)
        self.assertEqual(record["product_model"], "M1-new")

    def test_compare_ignores_inactive_records(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                    {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
                ]
            )
        )
        stockpile_db.apply_export_updates(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )

        result = stockpile_db.compare_with_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )

        self.assertEqual(result["total_local"], 1)
        self.assertEqual(result["only_in_local"], [])

    def test_deactivation_is_logged(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                    {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
                ]
            )
        )

        stockpile_db.apply_export_updates(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )

        with stockpile_db._connect() as conn:
            cur = conn.execute(
                "SELECT field_name, old_value, new_value, change_type "
                "FROM stockpile_changes WHERE product_barcode = ? ORDER BY id DESC",
                ("A2",),
            )
            changes = list(cur)

        self.assertTrue(
            any(
                row["field_name"] == "is_active"
                and row["old_value"] == "1"
                and row["new_value"] == "0"
                and row["change_type"] == "deactivate"
                for row in changes
            )
        )

    def test_list_inactive_records_returns_inactive_only(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                    {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
                ]
            )
        )
        stockpile_db.apply_export_updates(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )

        records = stockpile_db.list_inactive_records()

        self.assertEqual([record["product_barcode"] for record in records], ["A2"])
        self.assertEqual(records[0]["is_active"], 0)

    def test_list_changes_returns_latest_first(self) -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )
        stockpile_db.insert_or_update("A1", "M1-new", "L1-new")

        changes = stockpile_db.list_changes(limit=2)

        self.assertEqual(len(changes), 2)
        self.assertGreater(changes[0]["id"], changes[1]["id"])


if __name__ == "__main__":
    unittest.main()
