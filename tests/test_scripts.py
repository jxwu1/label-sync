import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import update_location_phase2
from check_duplicates import check_duplicates
from location_parser import categorize_locations, compose_location, parse_locations
from update_location_phase1 import (
    analyze_phase_one,
    detect_barcode_outliers,
    detect_invalid_locations,
)
import update_location
from update_location_phase2 import (
    build_phase_two_results,
    write_phase2_results,
)

TEST_TMP_DIR = Path(__file__).resolve().parent / "_tmp_scripts"


def _write_text_with_retry(path: Path, text: str) -> None:
    last_error = None
    for _ in range(5):
        try:
            path.write_text(text, encoding="utf-8")
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.02)
    raise last_error


def _to_csv_with_retry(dataframe: pd.DataFrame, path: Path) -> None:
    last_error = None
    for _ in range(5):
        try:
            dataframe.to_csv(path, index=False, encoding="utf-8-sig")
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.02)
    raise last_error


class CheckDuplicatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_check_duplicates_reports_duplicate_rows_from_csv(self) -> None:
        csv_path = self.test_dir / "duplicates.csv"
        dataframe = pd.DataFrame({"barcode": ["A1", "B2", "A1", "", "B2"]})
        _to_csv_with_retry(dataframe, csv_path)

        result = check_duplicates(csv_path)

        self.assertTrue(result["ok"])
        self.assertEqual(result["column"], "barcode")
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["dup_count"], 2)
        self.assertEqual(
            result["duplicates"],
            [
                {"value": "A1", "rows": [2, 4], "count": 2},
                {"value": "B2", "rows": [3, 6], "count": 2},
            ],
        )

    def test_check_duplicates_rejects_unsupported_suffix(self) -> None:
        result = check_duplicates("sample.txt")

        self.assertEqual(result, {"ok": False, "msg": "不支持的文件格式：.txt"})


class PhaseOneTests(unittest.TestCase):
    def test_analyze_phase_one_prioritizes_invalid_locations(self) -> None:
        analysis = analyze_phase_one(
            {
                "12345678": ["A-01-01", "X-01-01"],
                "1234": ["BAD"],
            }
        )

        self.assertEqual(
            analysis,
            {
                "duplicate_barcodes": {"12345678": ["A-01-01", "X-01-01"]},
                "invalid_locations": ["BAD"],
                "barcode_warnings": [("1234", 4, 8)],
                "median": 8,
                "exit_code": 3,
            },
        )

    def test_detect_invalid_locations_returns_only_invalid_entries(self) -> None:
        location_map = {
            "1001": ["A-01-01"],
            "1002": ["BAD"],
            "1003": ["Z-02-03", "INVALID"],
        }

        invalid_locations = detect_invalid_locations(location_map)

        self.assertEqual(invalid_locations, ["BAD", "INVALID"])

    def test_detect_barcode_outliers_flags_abnormal_lengths(self) -> None:
        warnings, median = detect_barcode_outliers(
            ["12345678", "12345679", "12345670", "12345671", "1234"]
        )

        self.assertEqual(median, 8)
        self.assertEqual(warnings, [("1234", 4, 8)])


class PhaseTwoTests(unittest.TestCase):
    def test_build_phase_two_results_handles_existing_new_and_exception_cases(self) -> None:
        location_map = {
            "111": ["B-02-02"],
            "222": ["X-03-03"],
            "333": ["A-05-05"],
        }
        system_records = {
            "111": {"model": "M-111", "stockpile_location": "A-01-01/X-01-01"},
            "333": {"model": "M-333", "stockpile_location": "A-01-01/"},
            "444": {"model": "M-444", "stockpile_location": "Z-09-09"},
        }

        results, new_barcodes, exceptions, unmatched_barcodes = build_phase_two_results(
            location_map, system_records
        )

        self.assertEqual(
            results,
            [
                {"barcode": "111", "model": "M-111", "location": "B-02-02/X-01-01"},
                {"barcode": "222", "model": "222", "location": "X-03-03"},
            ],
        )
        self.assertEqual(new_barcodes, ["222"])
        self.assertEqual(
            exceptions, [("333", "system issue: invalid system location: A-01-01/")]
        )
        self.assertEqual(unmatched_barcodes, ["444"])

    def test_build_phase_two_results_emits_multi_location_payload(self) -> None:
        location_map = {"111": ["A-02-02", "B-03-03", "X-04-04"]}
        system_records = {
            "111": {"model": "M-111", "stockpile_location": "A-01-01/X-01-01"},
        }

        results, new_barcodes, exceptions, _ = build_phase_two_results(
            location_map, system_records
        )

        self.assertEqual(results, [])
        self.assertEqual(new_barcodes, [])
        self.assertEqual(len(exceptions), 1)
        barcode, reason, payload = exceptions[0]
        self.assertEqual(barcode, "111")
        self.assertEqual(reason, "multi_location")
        self.assertEqual(payload["stockpile_stores"], ["A-01-01"])
        self.assertEqual(payload["stockpile_warehouses"], ["X-01-01"])
        self.assertEqual(payload["scan_stores"], ["A-02-02", "B-03-03"])
        self.assertEqual(payload["scan_warehouses"], ["X-04-04"])

    def test_build_phase_two_results_flags_stockpile_multi_even_when_scan_single(self) -> None:
        location_map = {"111": ["B-02-02"]}
        system_records = {
            "111": {"model": "M-111", "stockpile_location": "A-01-01/A-02-02/X-01-01"},
        }

        _, _, exceptions, _ = build_phase_two_results(location_map, system_records)

        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0][1], "multi_location")
        self.assertEqual(exceptions[0][2]["stockpile_stores"], ["A-01-01", "A-02-02"])

    def test_parse_locations_splits_store_and_warehouse(self) -> None:
        store, warehouse, issue = parse_locations(["A-01-01", "X-02-03"])

        self.assertEqual((store, warehouse, issue), ("A-01-01", "X-02-03", None))

    def test_parse_locations_reports_duplicate_store_locations(self) -> None:
        store, warehouse, issue = parse_locations(["A-01-01", "B-01-01"])

        self.assertEqual((store, warehouse), (None, None))
        self.assertEqual(issue, "duplicate_locations store=[A-01-01,B-01-01]")

    def test_categorize_locations_collects_multi_sides_and_dedupes(self) -> None:
        stores, warehouses, error = categorize_locations(
            ["A-01-01", "B-02-02", "A-01-01", "X-03-03"]
        )

        self.assertIsNone(error)
        self.assertEqual(stores, ["A-01-01", "B-02-02"])
        self.assertEqual(warehouses, ["X-03-03"])

    def test_categorize_locations_rejects_unknown_prefix(self) -> None:
        stores, warehouses, error = categorize_locations(["A-01-01", "Q-02"])

        self.assertEqual((stores, warehouses), ([], []))
        self.assertEqual(error, "unknown location prefix: Q-02")

    def test_compose_location_prefers_new_values_and_keeps_existing_warehouse(self) -> None:
        final_location = compose_location(
            old_store="A-01-01",
            old_warehouse="X-01-01",
            new_store="B-02-02",
            new_warehouse=None,
        )

        self.assertEqual(final_location, "B-02-02/X-01-01")


class WritePhase2ResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.temp_results = self.test_dir / "phase2_results_test.json"
        self.patch_file = mock.patch.object(
            update_location_phase2, "TEMP_RESULTS_FILE", self.temp_results
        )
        self.patch_file.start()

    def tearDown(self) -> None:
        self.patch_file.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_write_preserves_multi_location_payload_in_exceptions(self) -> None:
        exceptions = [
            ("111", "multi_location", {
                "stockpile_stores": ["A-01-01"],
                "stockpile_warehouses": ["X-01-01"],
                "scan_stores": ["A-02-02", "B-03-03"],
                "scan_warehouses": ["X-04-04"],
            }),
            ("222", "scan issue: unknown location prefix: Q-02"),
        ]
        write_phase2_results(
            self.temp_results,
            results=[{"barcode": "M1", "model": "M1", "location": "A-01/X-01"}],
            new_barcodes=[],
            exceptions=exceptions,
            unmatched_barcodes=["333"],
            employee_name="tester",
            scan_files=[],
            barcode_model_map={},
            stockpile_path=Path("stockpile.csv"),
        )
        data = json.loads(self.temp_results.read_text(encoding="utf-8"))
        self.assertEqual(len(data["exceptions"]), 2)
        first = data["exceptions"][0]
        self.assertEqual(first[0], "111")
        self.assertEqual(first[1], "multi_location")
        self.assertEqual(first[2]["stockpile_stores"], ["A-01-01"])
        self.assertEqual(first[2]["scan_warehouses"], ["X-04-04"])
        second = data["exceptions"][1]
        self.assertEqual(len(second), 2)
        self.assertEqual(second[0], "222")

    def test_round_trip_multi_location_exception_survives_read_write(self) -> None:
        get_payload = (
            lambda entry: entry[2]
            if len(entry) > 2
            else {}
        )
        original_exceptions = [
            ("999", "multi_location", {
                "stockpile_stores": ["A5"],
                "stockpile_warehouses": ["X5"],
                "scan_stores": ["B6"],
                "scan_warehouses": ["Z7"],
            }),
        ]
        write_phase2_results(
            self.temp_results,
            results=[],
            new_barcodes=[],
            exceptions=original_exceptions,
            unmatched_barcodes=[],
            employee_name="tester",
            scan_files=[],
            barcode_model_map={},
            stockpile_path=Path("s.csv"),
        )
        data = json.loads(self.temp_results.read_text(encoding="utf-8"))
        loaded_exceptions = data["exceptions"]
        payload = get_payload(loaded_exceptions[0])
        self.assertEqual(payload["stockpile_stores"], ["A5"])
        self.assertEqual(payload["scan_warehouses"], ["Z7"])


class LoadPhase2ResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.temp_results = self.test_dir / "phase3_results_test.json"
        self.patch_file = mock.patch.object(
            update_location, "TEMP_RESULTS_FILE", self.temp_results
        )
        self.patch_file.start()

    def tearDown(self) -> None:
        self.patch_file.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_phase2_results_handles_3_element_exceptions(self) -> None:
        data = {
            "results": [{"barcode": "M1", "model": "M1", "location": "A-01/X-01"}],
            "new_barcodes": [],
            "exceptions": [
                ["555", "multi_location", {"stockpile_stores": ["A-01"], "scan_warehouses": ["X-02"]}],
                ["666", "scan issue"],
            ],
            "unmatched_barcodes": [],
            "employee_name": "tester",
            "scan_files": [],
            "barcode_model_map": {},
            "stockpile_path": "stockpile.csv",
        }
        _write_text_with_retry(self.temp_results, json.dumps(data))
        loaded = update_location.load_phase2_results()
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded["exceptions"]), 2)
        self.assertEqual(loaded["exceptions"][0][0], "555")
        self.assertEqual(loaded["exceptions"][0][1], "multi_location")
        self.assertEqual(loaded["exceptions"][1][0], "666")
        self.assertEqual(loaded["exceptions"][1][1], "scan issue")


if __name__ == "__main__":
    unittest.main()
