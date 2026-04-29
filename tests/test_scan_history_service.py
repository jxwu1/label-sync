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

    def test_list_batches_includes_csv_metadata(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=10)

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 1)
        b = result[0]
        self.assertEqual(b["csv_filename"], "1产品信息导入模板.csv")
        self.assertEqual(b["csv_rows"], 10)
        self.assertGreater(b["csv_size_bytes"], 0)

    def test_list_batches_includes_xlsx_files(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=2,
            xlsx_files=["ALI.xlsx", "ALI_2.xlsx"],
        )

        result = scan_history_service.list_batches()

        b = result[0]
        names = sorted(f["name"] for f in b["xlsx_files"])
        self.assertEqual(names, ["ALI.xlsx", "ALI_2.xlsx"])
        self.assertGreater(b["xlsx_files"][0]["size_bytes"], 0)

    def test_list_batches_handles_missing_csv(self):
        batch = self.test_dir / "ALI价格标20260420100000"
        batch.mkdir()

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["csv_filename"])
        self.assertIsNone(result[0]["csv_rows"])

    def test_list_batches_handles_unreadable_csv(self):
        batch = self.test_dir / "ALI价格标20260420100000"
        batch.mkdir()
        (batch / "1产品信息导入模板.csv").write_bytes(b"")

        result = scan_history_service.list_batches()

        b = result[0]
        self.assertEqual(b["csv_rows"], 0)
        self.assertEqual(b["csv_size_bytes"], 0)

    def test_list_employees_returns_unique_sorted(self):
        self._make_batch("ALI价格标20260420100000")
        self._make_batch("ALI价格标20260425100000")
        self._make_batch("ABDUL价格标20260423100000")
        self._make_batch("ZHANG价格标20260424100000")

        result = scan_history_service.list_employees()

        self.assertEqual(result, ["ABDUL", "ALI", "ZHANG"])

    def test_list_employees_returns_empty_when_no_batches(self):
        result = scan_history_service.list_employees()
        self.assertEqual(result, [])

    def test_get_batch_csv_path_returns_path_for_existing_batch(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=3)

        result = scan_history_service.get_batch_csv_path("ALI价格标20260420100000")

        self.assertIsNotNone(result)
        self.assertTrue(result.exists())
        self.assertEqual(result.name, "1产品信息导入模板.csv")

    def test_get_batch_csv_path_returns_none_for_missing_batch(self):
        result = scan_history_service.get_batch_csv_path("NOPE价格标20260420100000")
        self.assertIsNone(result)

    def test_get_batch_csv_path_returns_none_when_csv_missing(self):
        batch = self.test_dir / "ALI价格标20260420100000"
        batch.mkdir()
        result = scan_history_service.get_batch_csv_path("ALI价格标20260420100000")
        self.assertIsNone(result)

    def test_get_batch_csv_path_rejects_path_traversal(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1)

        self.assertIsNone(scan_history_service.get_batch_csv_path("../etc/passwd"))
        self.assertIsNone(scan_history_service.get_batch_csv_path("ALI价格标20260420100000/../"))
        self.assertIsNone(scan_history_service.get_batch_csv_path("/absolute/path"))

    def test_get_batch_csv_path_rejects_unrecognized_pattern(self):
        (self.test_dir / "random_folder").mkdir()
        result = scan_history_service.get_batch_csv_path("random_folder")
        self.assertIsNone(result)

    def test_get_batch_xlsx_path_returns_path_for_existing_file(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=1,
            xlsx_files=["ALI.xlsx"],
        )

        result = scan_history_service.get_batch_xlsx_path("ALI价格标20260420100000", "ALI.xlsx")

        self.assertIsNotNone(result)
        self.assertTrue(result.exists())

    def test_get_batch_xlsx_path_returns_none_for_missing_file(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1, xlsx_files=["ALI.xlsx"])

        result = scan_history_service.get_batch_xlsx_path("ALI价格标20260420100000", "NOPE.xlsx")
        self.assertIsNone(result)

    def test_get_batch_xlsx_path_rejects_path_traversal_in_filename(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1, xlsx_files=["ALI.xlsx"])

        for bad_name in ["../other.xlsx", "..\\other.xlsx", "/etc/passwd", "subdir/foo.xlsx"]:
            self.assertIsNone(
                scan_history_service.get_batch_xlsx_path("ALI价格标20260420100000", bad_name),
                f"should reject {bad_name!r}",
            )

    def test_get_batch_xlsx_path_only_serves_xlsx_extension(self):
        batch = self._make_batch("ALI价格标20260420100000", csv_rows=1)
        (batch / "secret.txt").write_text("nope")

        result = scan_history_service.get_batch_xlsx_path("ALI价格标20260420100000", "secret.txt")
        self.assertIsNone(result)
