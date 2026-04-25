import shutil
import unittest
from pathlib import Path
from unittest import mock

import attendance_service as svc
import attendance_report_service as rpt

_TEST_ROOT = Path(__file__).resolve().parent


class TestBuildPayrollPdf(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_attendance_rpt_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_returns_pdf_bytes(self):
        svc.create_employee("小王")
        data = rpt.build_payroll_pdf("2026-04")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 100)

    def test_empty_month_still_works(self):
        data = rpt.build_payroll_pdf("2099-01")
        self.assertTrue(data.startswith(b"%PDF"))


class TestBuildPdf(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_ROOT / f"_test_attendance_rpt_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch_dir = mock.patch.object(svc, "_ATTENDANCE_DIR", self.test_dir)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_pdf_returns_non_empty_bytes(self):
        svc.create_employee("小王")
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        data = rpt.build_pdf("2026-04")
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 100)
        self.assertTrue(data.startswith(b"%PDF"))

    def test_pdf_empty_month_still_works(self):
        data = rpt.build_pdf("2099-01")
        self.assertTrue(data.startswith(b"%PDF"))
