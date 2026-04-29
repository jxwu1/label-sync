"""数据质量 service 单元测试。"""
import shutil
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import data_quality_service
import stockpile_db

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_data_quality"


class DataQualityTests(unittest.TestCase):
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

    def _import(self, rows):
        stockpile_db.import_from_dataframe(pd.DataFrame(rows))

    def test_multi_same_kind_detects_two_stores(self) -> None:
        self._import([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A14-12-01/A14-13-01"},
            {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "A22-04-04"},  # ok
        ])
        report = data_quality_service.build_report()
        self.assertEqual(report["multi_same_kind"]["count"], 1)
        sample = report["multi_same_kind"]["samples"][0]
        self.assertEqual(sample["barcode"], "B1")
        self.assertEqual(sample["duplicated_kind"], "store")
        self.assertEqual(sample["count"], 2)

    def test_multi_same_kind_detects_two_warehouses(self) -> None:
        self._import([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22/X11/X12"},
        ])
        report = data_quality_service.build_report()
        self.assertEqual(report["multi_same_kind"]["count"], 1)
        sample = report["multi_same_kind"]["samples"][0]
        self.assertEqual(sample["duplicated_kind"], "warehouse")

    def test_unknown_prefix_lists_anomalous_segment(self) -> None:
        self._import([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22/Q99/X11"},
        ])
        report = data_quality_service.build_report()
        self.assertEqual(report["unknown_prefix"]["count"], 1)
        sample = report["unknown_prefix"]["samples"][0]
        self.assertEqual(sample["anomalous_segment"], "Q99")

    def test_whitespace_anomalies_detect_trailing_space(self) -> None:
        self._import([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "B04-22-04 /Z202-01"},
            {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "A22/X11"},  # ok
        ])
        report = data_quality_service.build_report()
        self.assertEqual(report["whitespace_anomalies"]["count"], 1)
        sample = report["whitespace_anomalies"]["samples"][0]
        self.assertEqual(sample["barcode"], "B1")
        self.assertEqual(sample["raw_location"], "B04-22-04 /Z202-01")
        self.assertEqual(sample["normalized"], "B04-22-04/Z202-01")

    def test_flippers_detect_4_or_more_changes(self) -> None:
        # 在同一 barcode 上反复改 location 4 次（含初始 insert，共 4 条 location 变更）
        self._import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22"}])
        self._import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A23"}])
        self._import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22"}])
        self._import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A23"}])
        self._import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22"}])
        report = data_quality_service.build_report()
        # 4 次 location 字段变化（首次 insert 不算 location 变化）
        self.assertGreaterEqual(report["flippers"]["count"], 1)
        sample = report["flippers"]["samples"][0]
        self.assertEqual(sample["barcode"], "B1")
        self.assertGreaterEqual(sample["change_count"], 4)

    def test_clean_data_no_anomalies(self) -> None:
        self._import([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22-04-04/X11-02"},
            {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "A23"},
        ])
        report = data_quality_service.build_report()
        self.assertEqual(report["multi_same_kind"]["count"], 0)
        self.assertEqual(report["unknown_prefix"]["count"], 0)
        self.assertEqual(report["whitespace_anomalies"]["count"], 0)
        self.assertEqual(report["flippers"]["count"], 0)
        self.assertEqual(report["duplicate_segments"]["count"], 0)

    def test_duplicate_segments_detects_repeated_location(self) -> None:
        self._import([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "B06-20-02/XB07-12/XB07-12"},
            {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "XA09-04/XA09-04"},
            {"product_barcode": "B3", "product_model": "M3", "stockpile_location": "A22-04-04/X11-02"},  # ok
        ])
        report = data_quality_service.build_report()
        self.assertEqual(report["duplicate_segments"]["count"], 2)
        by_barcode = {s["barcode"]: s for s in report["duplicate_segments"]["samples"]}
        self.assertEqual(by_barcode["B1"]["duplicates"], ["XB07-12"])
        self.assertEqual(by_barcode["B1"]["raw_location"], "B06-20-02/XB07-12/XB07-12")
        self.assertEqual(by_barcode["B2"]["duplicates"], ["XA09-04"])


if __name__ == "__main__":
    unittest.main()
