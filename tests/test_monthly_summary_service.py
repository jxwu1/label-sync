import json
import shutil
import time
import unittest
from datetime import date
from pathlib import Path

import monthly_summary_service as svc

_TEST_ROOT = Path(__file__).resolve().parent


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


class TestSaveRecord(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_monthly_summary_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_creates_file_and_appends_record(self):
        record = svc.save_record(
            supplier_name="ABC贸易",
            total_price=12000.0,
            tax=1560.0,
            invoice_date="2026-04-15",
            month="2026-04",
        )
        self.assertEqual(record["supplier_name"], "ABC贸易")
        self.assertAlmostEqual(record["total_price"], 12000.0)
        self.assertAlmostEqual(record["tax"], 1560.0)
        self.assertAlmostEqual(record["total_with_tax"], 13560.0)
        self.assertEqual(record["invoice_date"], "2026-04-15")

        records = svc.load_records("2026-04")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["supplier_name"], "ABC贸易")

    def test_save_appends_multiple_records(self):
        svc.save_record("A", 100.0, 10.0, "2026-04-01", "2026-04")
        svc.save_record("B", 200.0, 20.0, "2026-04-02", "2026-04")
        records = svc.load_records("2026-04")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["supplier_name"], "A")
        self.assertEqual(records[1]["supplier_name"], "B")

    def test_load_returns_empty_for_nonexistent_month(self):
        records = svc.load_records("2099-01")
        self.assertEqual(records, [])

    def test_save_with_special_tax_includes_in_total(self):
        record = svc.save_record(
            supplier_name="EcoCorp",
            total_price=100.0,
            tax=13.0,
            invoice_date="2026-04-15",
            month="2026-04",
            special_tax=5.5,
        )
        self.assertAlmostEqual(record["special_tax"], 5.5)
        self.assertAlmostEqual(record["total_with_tax"], 118.5)

    def test_save_without_special_tax_defaults_to_zero(self):
        record = svc.save_record("A", 100.0, 10.0, "2026-04-01", "2026-04")
        self.assertEqual(record["special_tax"], 0.0)
        self.assertAlmostEqual(record["total_with_tax"], 110.0)

    def test_load_old_record_without_special_tax_field_fills_zero(self):
        """向后兼容：旧 JSON 记录无 special_tax 字段，load 时填 0。"""
        path = svc._month_file("2026-04")
        legacy = [{
            "supplier_name": "Old",
            "total_price": 100.0,
            "tax": 10.0,
            "total_with_tax": 110.0,
            "invoice_date": "2026-04-01",
            "created_at": "2026-04-01T00:00:00",
        }]
        path.write_text(json.dumps(legacy), encoding="utf-8")
        records = svc.load_records("2026-04")
        self.assertEqual(records[0]["special_tax"], 0.0)


class TestListMonths(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_monthly_summary_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_lists_months_sorted_descending(self):
        svc.save_record("A", 100.0, 10.0, "2026-02-01", "2026-02")
        svc.save_record("B", 200.0, 20.0, "2026-04-01", "2026-04")
        svc.save_record("C", 300.0, 30.0, "2026-03-01", "2026-03")
        months = svc.list_months()
        self.assertEqual(months, ["2026-04", "2026-03", "2026-02"])


class TestCleanupExpired(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_monthly_summary_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_removes_files_older_than_six_months(self):
        old_file = self.test_dir / "2025-08.json"
        _write_text_with_retry(old_file, "[]")
        recent_file = self.test_dir / "2026-04.json"
        _write_text_with_retry(recent_file, "[]")
        svc.cleanup_expired(reference_date=date(2026, 4, 1))
        self.assertFalse(old_file.exists())
        self.assertTrue(recent_file.exists())

    def test_keeps_current_month_and_previous_five_months(self):
        for month in [
            "2025-09", "2025-10", "2025-11", "2025-12",
            "2026-01", "2026-02", "2026-03", "2026-04",
        ]:
            _write_text_with_retry(self.test_dir / f"{month}.json", "[]")

        svc.cleanup_expired(reference_date=date(2026, 4, 1))

        remaining = sorted(path.stem for path in self.test_dir.glob("*.json"))
        self.assertEqual(
            remaining,
            ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"],
        )

    def test_keeps_six_month_window_across_year_boundary(self):
        for month in [
            "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01",
        ]:
            _write_text_with_retry(self.test_dir / f"{month}.json", "[]")

        svc.cleanup_expired(reference_date=date(2026, 1, 15))

        remaining = sorted(path.stem for path in self.test_dir.glob("*.json"))
        self.assertEqual(
            remaining,
            ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01"],
        )


class TestBuildPdf(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_monthly_summary_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_builds_pdf_bytes(self):
        svc.save_record("ABC贸易", 12000.0, 1560.0, "2026-04-15", "2026-04")
        svc.save_record("XYZ国际", 8500.0, 1105.0, "2026-04-18", "2026-04")
        pdf_bytes = svc.build_pdf("2026-04")
        self.assertGreater(len(pdf_bytes), 100)
        self.assertTrue(pdf_bytes[:5] == b"%PDF-")

    def test_empty_month_returns_pdf_with_no_records_note(self):
        pdf_bytes = svc.build_pdf("2099-01")
        self.assertTrue(pdf_bytes[:5] == b"%PDF-")
