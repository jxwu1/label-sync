import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import barcode_service

TEST_TMP_DIR = Path(__file__).resolve().parent / "_tmp_barcode"


def _write_stockpile(path: Path, records: list[dict]) -> None:
    pd.DataFrame(records).to_csv(path, index=False, encoding="utf-8")


def _results_fixture(stockpile_path: Path) -> dict:
    return {
        "results": [
            {"model": "NEW_A", "location": "A1/X1"},
            {"model": "NEW_B", "location": "B2"},
            {"model": "MATCHED", "location": "A9/X9"},
        ],
        "new_barcodes": ["NEW_A", "NEW_B"],
        "exceptions": [],
        "unmatched_barcodes": [],
        "employee_name": "tester",
        "scan_files": [],
        "barcode_model_map": {"NEW_A": "NEW_A", "NEW_B": "NEW_B", "MATCHED": "MATCHED_MODEL"},
        "stockpile_path": str(stockpile_path),
    }


class NewBarcodeCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.temp_results = self.test_dir / "phase2_results.json"
        self.stockpile = self.test_dir / "stockpile.csv"
        _write_stockpile(self.stockpile, [
            {"product_barcode": "EXISTING", "product_model": "MODEL_X", "stockpile_location": "A5/X5"},
        ])
        self.temp_results.write_text(
            json.dumps(_results_fixture(self.stockpile)), encoding="utf-8"
        )
        self.patch_file = mock.patch.object(barcode_service, "TEMP_RESULTS_FILE", self.temp_results)
        self.patch_file.start()
        self.patch_state = mock.patch.object(barcode_service, "task_state", autospec=True)
        self.mock_state = self.patch_state.start()
        self.mock_state.is_waiting.return_value = True
        self.mock_state.waiting_stage.return_value = "phase2_review"
        self.patch_db = mock.patch.object(barcode_service, "stockpile_db")
        self.mock_db_stockpile = self.patch_db.start()
        self.mock_db_stockpile.query_all_as_system_records.return_value = (
            {"EXISTING": "MODEL_X"},
            {"EXISTING": {"model": "MODEL_X", "stockpile_location": "A5/X5"}},
        )

    def tearDown(self) -> None:
        self.patch_file.stop()
        self.patch_state.stop()
        self.patch_db.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_correct_to_stockpile_barcode_composes_location_and_drops_from_new(self) -> None:
        result = barcode_service.correct_barcode("NEW_A", "EXISTING")
        self.assertTrue(result.ok)
        data = json.loads(self.temp_results.read_text(encoding="utf-8"))
        self.assertNotIn("NEW_A", data["new_barcodes"])
        entry = next(r for r in data["results"] if r["model"] == "MODEL_X")
        # scan A1/X1 覆盖 stockpile A5/X5
        self.assertEqual(entry["location"], "A1/X1")
        self.assertEqual(data["barcode_model_map"]["EXISTING"], "MODEL_X")
        self.assertNotIn("NEW_A", data["barcode_model_map"])
        self.mock_state.remove_new_barcode.assert_called_once_with("NEW_A")

    def test_correct_to_non_stockpile_barcode_replaces_id_keeps_location(self) -> None:
        result = barcode_service.correct_barcode("NEW_A", "STILL_NEW")
        self.assertTrue(result.ok)
        data = json.loads(self.temp_results.read_text(encoding="utf-8"))
        self.assertIn("STILL_NEW", data["new_barcodes"])
        self.assertNotIn("NEW_A", data["new_barcodes"])
        entry = next(r for r in data["results"] if r["model"] == "STILL_NEW")
        self.assertEqual(entry["location"], "A1/X1")
        self.mock_state.replace_new_barcode.assert_called_once_with("NEW_A", "STILL_NEW")

    def test_correct_unknown_barcode_returns_404(self) -> None:
        result = barcode_service.correct_barcode("NOT_IN_LIST", "EXISTING")
        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 404)

    def test_delete_removes_entry_from_results_and_list(self) -> None:
        result = barcode_service.delete_barcode("NEW_A")
        self.assertTrue(result.ok)
        data = json.loads(self.temp_results.read_text(encoding="utf-8"))
        self.assertNotIn("NEW_A", data["new_barcodes"])
        self.assertFalse(any(r["model"] == "NEW_A" for r in data["results"]))
        self.assertNotIn("NEW_A", data["barcode_model_map"])
        self.mock_state.remove_new_barcode.assert_called_once_with("NEW_A")

    def test_delete_unknown_returns_404(self) -> None:
        result = barcode_service.delete_barcode("NOT_IN_LIST")
        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 404)

    def test_resolve_phase2_exception_removes_multi_location_payload(self) -> None:
        data = json.loads(self.temp_results.read_text(encoding="utf-8"))
        data["exceptions"] = [
            ["111", "multi_location", {"stockpile_stores": ["A-01"], "scan_warehouses": ["X-01"]}],
            ["222", "scan issue: unknown prefix"],
        ]
        self.temp_results.write_text(json.dumps(data), encoding="utf-8")
        result = barcode_service.resolve_phase2_exception("111", "A-01/X-01")
        self.assertTrue(result.ok)
        saved = json.loads(self.temp_results.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["exceptions"]), 1)
        self.assertEqual(saved["exceptions"][0][0], "222")
        resolved = next(r for r in saved["results"] if r["location"] == "A-01/X-01")
        self.assertEqual(resolved["model"], "111")


if __name__ == "__main__":
    unittest.main()
