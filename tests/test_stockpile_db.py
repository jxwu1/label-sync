import json
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import stockpile_db

TEST_TMP_DIR = Path(__file__).resolve().parent / "_tmp"
TEST_DB = TEST_TMP_DIR / "test_stockpile.db"


def _clean_tables() -> None:
    stockpile_db.ensure_db()
    conn = stockpile_db._connect()
    conn.execute("DELETE FROM stockpile")
    conn.execute("DELETE FROM stockpile_changes")
    conn.commit()
    conn.close()


class StockpileDbTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_DIR.mkdir(exist_ok=True)
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", TEST_DB)
        self.patch.start()
        _clean_tables()

    def tearDown(self) -> None:
        self.patch.stop()

    def test_ensure_db_creates_tables(self) -> None:
        stockpile_db.ensure_db()
        self.assertTrue(TEST_DB.exists())

    def test_is_initialized_returns_false_for_empty_db(self) -> None:
        stockpile_db.ensure_db()
        self.assertFalse(stockpile_db.is_initialized())

    def test_is_initialized_returns_true_after_import(self) -> None:
        df = pd.DataFrame([{"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"}])
        stockpile_db.import_from_dataframe(df)
        self.assertTrue(stockpile_db.is_initialized())

    def test_import_from_dataframe_inserts_records(self) -> None:
        df = pd.DataFrame([
            {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
            {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
        ])
        count = stockpile_db.import_from_dataframe(df)
        self.assertEqual(count, 2)
        self.assertEqual(stockpile_db.count_records(), 2)

    def test_import_handles_extra_columns_in_json(self) -> None:
        df = pd.DataFrame([{
            "product_barcode": "A1", "product_model": "M1",
            "stockpile_location": "L1", "price": "100", "stock": "50"
        }])
        stockpile_db.import_from_dataframe(df)
        record = stockpile_db.query_by_barcode("A1")
        self.assertIsNotNone(record)
        extra = json.loads(record["extra"])
        self.assertEqual(extra["price"], "100")
        self.assertEqual(extra["stock"], "50")

    def test_import_skip_nan_barcode(self) -> None:
        df = pd.DataFrame([{"product_barcode": float("nan"), "product_model": "M1", "stockpile_location": "L1"}])
        count = stockpile_db.import_from_dataframe(df)
        self.assertEqual(count, 0)

    def test_query_by_barcode_returns_none_for_missing(self) -> None:
        self.assertIsNone(stockpile_db.query_by_barcode("NOPE"))

    def test_query_by_barcode_returns_record(self) -> None:
        df = pd.DataFrame([{"product_barcode": "X99", "product_model": "MX", "stockpile_location": "LX"}])
        stockpile_db.import_from_dataframe(df)
        record = stockpile_db.query_by_barcode("X99")
        self.assertIsNotNone(record)
        self.assertEqual(record["product_model"], "MX")

    def test_query_all_as_system_records_returns_maps(self) -> None:
        df = pd.DataFrame([
            {"product_barcode": "111", "product_model": "M-111", "stockpile_location": "A-01-01/X-01-01"},
            {"product_barcode": "222", "product_model": "M-222", "stockpile_location": "B-02-02"},
        ])
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
        df = pd.DataFrame([{"product_barcode": "U1", "product_model": "Old", "stockpile_location": "OldLoc"}])
        stockpile_db.import_from_dataframe(df)
        stockpile_db.insert_or_update("U1", "New", "NewLoc", source="user_correction")
        record = stockpile_db.query_by_barcode("U1")
        self.assertEqual(record["product_model"], "New")
        self.assertEqual(record["source"], "user_correction")

    def test_changes_logged_on_update(self) -> None:
        df = pd.DataFrame([{"product_barcode": "C1", "product_model": "Old", "stockpile_location": "OldLoc"}])
        stockpile_db.import_from_dataframe(df)
        stockpile_db.insert_or_update("C1", "New", "NewLoc")

        conn = stockpile_db._connect()
        cur = conn.execute("SELECT * FROM stockpile_changes WHERE product_barcode = ?", ("C1",))
        changes = cur.fetchall()
        conn.close()
        self.assertGreaterEqual(len(changes), 1)

    def test_update_location_changes_location(self) -> None:
        df = pd.DataFrame([{"product_barcode": "L1", "product_model": "M1", "stockpile_location": "OldLoc"}])
        stockpile_db.import_from_dataframe(df)
        stockpile_db.update_location("L1", "NewLoc")
        record = stockpile_db.query_by_barcode("L1")
        self.assertEqual(record["stockpile_location"], "NewLoc")

    def test_update_location_noop_for_unknown_barcode(self) -> None:
        stockpile_db.update_location("NOBODY", "Loc")
        self.assertTrue(True)

    def test_query_all_barcodes_set(self) -> None:
        df = pd.DataFrame([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "L1"},
            {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "L2"},
        ])
        stockpile_db.import_from_dataframe(df)
        result = stockpile_db.query_all_barcodes_set()
        self.assertEqual(result, {"B1", "B2"})

    def test_compare_with_dataframe_finds_matches_and_mismatches(self) -> None:
        df_local = pd.DataFrame([
            {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "A/X"},
            {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "B/Y"},
        ])
        stockpile_db.import_from_dataframe(df_local)

        df_export = pd.DataFrame([
            {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "A/X"},
            {"product_barcode": "A2", "product_model": "M2_CHANGED", "stockpile_location": "B/Y"},
            {"product_barcode": "A3", "product_model": "M3", "stockpile_location": "C/Z"},
        ])
        result = stockpile_db.compare_with_dataframe(df_export)
        self.assertEqual(result["total_local"], 2)
        self.assertEqual(result["total_export"], 3)
        self.assertEqual(result["only_in_local"], [])
        self.assertEqual(result["only_in_export"], ["A3"])
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertEqual(result["mismatches"][0]["barcode"], "A2")
        self.assertEqual(result["consistent"], 1)

    def test_apply_export_updates_overwrites_local(self) -> None:
        df_local = pd.DataFrame([
            {"product_barcode": "X1", "product_model": "Old", "stockpile_location": "OldLoc"},
        ])
        stockpile_db.import_from_dataframe(df_local)

        df_export = pd.DataFrame([
            {"product_barcode": "X1", "product_model": "New", "stockpile_location": "NewLoc"},
            {"product_barcode": "X2", "product_model": "Fresh", "stockpile_location": "F/Loc"},
        ])
        updated = stockpile_db.apply_export_updates(df_export)
        self.assertEqual(updated, 2)

        r1 = stockpile_db.query_by_barcode("X1")
        self.assertEqual(r1["product_model"], "New")
        self.assertEqual(r1["source"], "system_export")

        r2 = stockpile_db.query_by_barcode("X2")
        self.assertIsNotNone(r2)


if __name__ == "__main__":
    unittest.main()
