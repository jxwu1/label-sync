"""scan_history_service 单测。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

import scan_history_service

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_scan_history"


class ScanHistoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch = mock.patch.object(scan_history_service, "OUTPUT_DIR", self.test_dir)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_batch(
        self, folder_name: str, csv_rows: int = 0, xlsx_files: list[str] | None = None
    ) -> Path:
        """在 test_dir 下造一个 batch 目录。"""
        batch = self.test_dir / folder_name
        batch.mkdir()
        if csv_rows >= 0:
            csv = batch / "1产品信息导入模板.csv"
            lines = ["型号,唯一码"]
            lines.extend(f"M{i},B{i}" for i in range(csv_rows))
            csv.write_text("\n".join(lines), encoding="utf-8-sig")
        for xlsx_name in xlsx_files or []:
            (batch / xlsx_name).write_bytes(b"FAKE XLSX CONTENT" * 10)
        return batch

    def test_parse_folder_name_extracts_employee_and_timestamp(self):
        result = scan_history_service._parse_folder_name("ALI价格标20260423155137")
        self.assertEqual(result, {"employee": "ALI", "timestamp": "20260423155137"})

    def test_parse_folder_name_returns_none_for_unrecognized(self):
        self.assertIsNone(scan_history_service._parse_folder_name("random_folder"))
        self.assertIsNone(scan_history_service._parse_folder_name("ALI价格标"))
        self.assertIsNone(scan_history_service._parse_folder_name("价格标20260423155137"))

    def test_list_batches_returns_sorted_descending_by_timestamp(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=3)
        self._make_batch("ALI价格标20260425100000", csv_rows=5)
        self._make_batch("ABDUL价格标20260423100000", csv_rows=1)

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 3)
        self.assertEqual(
            [b["batch_id"] for b in result],
            [
                "ALI价格标20260425100000",
                "ABDUL价格标20260423100000",
                "ALI价格标20260420100000",
            ],
        )

    def test_list_batches_skips_unrecognized_folder_names(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1)
        (self.test_dir / "random_folder").mkdir()
        (self.test_dir / ".DS_Store").mkdir()

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["batch_id"], "ALI价格标20260420100000")

    def test_list_batches_truncates_to_limit(self):
        for i in range(5):
            self._make_batch(f"ALI价格标2026042010{i:04d}", csv_rows=1)

        result = scan_history_service.list_batches(limit=3)

        self.assertEqual(len(result), 3)

    def test_list_batches_returns_empty_when_output_dir_missing(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        result = scan_history_service.list_batches()
        self.assertEqual(result, [])
