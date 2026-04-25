"""stockpile HTTP 路由集成测试。"""
import io
import shutil
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from flask import Flask

import stockpile_db
from routes_stockpile import bp as stockpile_bp

_TEST_DIR = Path(__file__).resolve().parent / "_test_stockpile_routes"
_TEST_DB = _TEST_DIR / "test.db"


def _make_csv_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    return df.to_csv(index=False).encode("utf-8")


class StockpileRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        _TEST_DIR.mkdir(exist_ok=True)
        self._patches = [
            mock.patch.object(stockpile_db, "DB_PATH", _TEST_DB),
            mock.patch("routes_stockpile.INPUT_DIR", _TEST_DIR),
        ]
        for p in self._patches:
            p.start()
        # 清空 DB
        with stockpile_db._connect() as conn:
            conn.execute("DELETE FROM stockpile")
            conn.execute("DELETE FROM stockpile_changes")

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(stockpile_bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    def test_status_uninitialized(self):
        res = self.client.get("/stockpile/status")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"ok": True, "initialized": False, "count": 0})

    def test_init_rejects_no_files(self):
        res = self.client.post("/stockpile/init")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["ok"])

    def test_init_rejects_empty_filename(self):
        res = self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(b""), "")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)

    def test_init_rejects_unreadable_file(self):
        # .txt 不在 read_input_file 的支持列表
        res = self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(b"not a real spreadsheet"), "junk.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        # 临时文件应已清理
        self.assertEqual(list(_TEST_DIR.glob("junk.txt")), [])

    def test_init_imports_csv_and_status_reflects(self):
        csv_bytes = _make_csv_bytes([
            {"product_barcode": "R1", "product_model": "M1", "stockpile_location": "L1"},
            {"product_barcode": "R2", "product_model": "M2", "stockpile_location": "L2"},
        ])
        res = self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(csv_bytes), "init.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["count"], 2)
        # 临时文件被清理
        self.assertEqual(list(_TEST_DIR.glob("init.csv")), [])

        status = self.client.get("/stockpile/status").get_json()
        self.assertTrue(status["initialized"])
        self.assertEqual(status["count"], 2)

    def test_compare_returns_diff(self):
        # 先初始化
        local_csv = _make_csv_bytes([
            {"product_barcode": "C1", "product_model": "M1", "stockpile_location": "L1"},
        ])
        self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(local_csv), "local.csv")},
            content_type="multipart/form-data",
        )
        # 再比对
        export_csv = _make_csv_bytes([
            {"product_barcode": "C1", "product_model": "M1_NEW", "stockpile_location": "L1"},
            {"product_barcode": "C2", "product_model": "M2", "stockpile_location": "L2"},
        ])
        res = self.client.post(
            "/stockpile/compare",
            data={"files": (io.BytesIO(export_csv), "export.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        diff = res.get_json()["diff"]
        self.assertEqual(diff["only_in_export"], ["C2"])
        self.assertEqual(len(diff["mismatches"]), 1)
        self.assertEqual(diff["mismatches"][0]["barcode"], "C1")

    def test_apply_export_updates_db(self):
        local_csv = _make_csv_bytes([
            {"product_barcode": "A1", "product_model": "Old", "stockpile_location": "OldLoc"},
        ])
        self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(local_csv), "local.csv")},
            content_type="multipart/form-data",
        )
        export_csv = _make_csv_bytes([
            {"product_barcode": "A1", "product_model": "New", "stockpile_location": "NewLoc"},
        ])
        res = self.client.post(
            "/stockpile/apply-export",
            data={"files": (io.BytesIO(export_csv), "export.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["updated"], 1)
        rec = stockpile_db.query_by_barcode("A1")
        self.assertEqual(rec["product_model"], "New")

    def test_temp_file_cleaned_when_handler_raises(self):
        # 注入异常确认 finally 清理生效
        bad_csv = _make_csv_bytes([
            {"product_barcode": "X1", "product_model": "M", "stockpile_location": "L"},
        ])
        with mock.patch("stockpile_db.import_from_dataframe", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/stockpile/init",
                    data={"files": (io.BytesIO(bad_csv), "boom.csv")},
                    content_type="multipart/form-data",
                )
        self.assertEqual(list(_TEST_DIR.glob("boom.csv")), [])


if __name__ == "__main__":
    unittest.main()
