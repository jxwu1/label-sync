import json
import shutil
import unittest
from datetime import date
from pathlib import Path

import monthly_summary_service as svc

_TEST_DIR = Path(__file__).resolve().parent / "_test_monthly_summary"


class TestSaveRecord(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

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


class TestListMonths(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_lists_months_sorted_descending(self):
        svc.save_record("A", 100.0, 10.0, "2026-02-01", "2026-02")
        svc.save_record("B", 200.0, 20.0, "2026-04-01", "2026-04")
        svc.save_record("C", 300.0, 30.0, "2026-03-01", "2026-03")
        months = svc.list_months()
        self.assertEqual(months, ["2026-04", "2026-03", "2026-02"])


class TestCleanupExpired(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_removes_files_older_than_six_months(self):
        old_file = _TEST_DIR / "2025-08.json"
        old_file.write_text("[]", encoding="utf-8")
        recent_file = _TEST_DIR / "2026-04.json"
        recent_file.write_text("[]", encoding="utf-8")
        svc.cleanup_expired(reference_date=date(2026, 4, 1))
        self.assertFalse(old_file.exists())
        self.assertTrue(recent_file.exists())


class TestBuildPdf(unittest.TestCase):
    def setUp(self):
        _TEST_DIR.mkdir(exist_ok=True)
        svc._SUMMARY_DIR = _TEST_DIR

    def tearDown(self):
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_builds_pdf_bytes(self):
        svc.save_record("ABC贸易", 12000.0, 1560.0, "2026-04-15", "2026-04")
        svc.save_record("XYZ国际", 8500.0, 1105.0, "2026-04-18", "2026-04")
        pdf_bytes = svc.build_pdf("2026-04")
        self.assertGreater(len(pdf_bytes), 100)
        self.assertTrue(pdf_bytes[:5] == b"%PDF-")

    def test_empty_month_returns_pdf_with_no_records_note(self):
        pdf_bytes = svc.build_pdf("2099-01")
        self.assertTrue(pdf_bytes[:5] == b"%PDF-")
