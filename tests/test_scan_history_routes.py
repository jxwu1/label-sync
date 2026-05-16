"""routes_scan_history 单测。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

from app.services import scan_history as scan_history_service
from app.routes.scan_history import bp

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_scan_history_routes"


class ScanHistoryRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch = mock.patch.object(scan_history_service, "OUTPUT_DIR", self.test_dir)
        self.patch.start()
        self.addCleanup(self.patch.stop)

        app = Flask(__name__)
        app.register_blueprint(bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_batch(
        self, folder_name: str, csv_rows: int = 0, xlsx_files: list[str] | None = None
    ) -> Path:
        batch = self.test_dir / folder_name
        batch.mkdir()
        if csv_rows >= 0:
            csv = batch / "1产品信息导入模板.csv"
            lines = ["型号,唯一码"]
            lines.extend(f"M{i},B{i}" for i in range(csv_rows))
            csv.write_text("\n".join(lines), encoding="utf-8-sig")
        for x in xlsx_files or []:
            (batch / x).write_bytes(b"FAKE" * 100)
        return batch

    def test_batches_endpoint_returns_list_and_employees(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=3, xlsx_files=["ALI.xlsx"])
        self._make_batch("ABDUL价格标20260421100000", csv_rows=5)

        resp = self.client.get("/scan_history/batches")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(sorted(data["employees"]), ["ABDUL", "ALI"])
        self.assertEqual(len(data["batches"]), 2)
        self.assertEqual(data["batches"][0]["employee"], "ABDUL")

    def test_download_csv_returns_file(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=2)

        resp = self.client.get("/scan_history/batches/ALI价格标20260420100000/download/csv")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("型号,唯一码", resp.data.decode("utf-8-sig"))
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))

    def test_download_csv_returns_404_for_missing_batch(self):
        resp = self.client.get("/scan_history/batches/NOPE价格标20260420100000/download/csv")
        self.assertEqual(resp.status_code, 404)

    def test_download_csv_returns_404_for_unrecognized_batch_id(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1)
        resp = self.client.get("/scan_history/batches/random_unrelated/download/csv")
        self.assertEqual(resp.status_code, 404)

    def test_download_xlsx_returns_file(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=1,
            xlsx_files=["ALI.xlsx"],
        )

        resp = self.client.get("/scan_history/batches/ALI价格标20260420100000/files/ALI.xlsx")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))

    def test_download_xlsx_returns_404_for_path_traversal_filename(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=1,
            xlsx_files=["ALI.xlsx"],
        )

        resp = self.client.get("/scan_history/batches/ALI价格标20260420100000/files/..%2Fevil.xlsx")
        self.assertEqual(resp.status_code, 404)
