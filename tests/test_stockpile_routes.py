"""stockpile HTTP 路由集成测试。"""

import io
import shutil
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from flask import Flask

from app.repositories import stockpile_db
from app.routes.stockpile import bp as stockpile_bp

_TEST_DIR = Path(__file__).resolve().parent / "_test_stockpile_routes"


def _make_csv_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    return df.to_csv(index=False).encode("utf-8")


class StockpileRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = _TEST_DIR / f"_test_stockpile_routes_{self._testMethodName}"
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        # DB 隔离由 conftest autouse _isolate_db 负责（unified engine 指向 tmp db_path）
        self._patches = [
            mock.patch("app.routes.stockpile.INPUT_DIR", self.test_dir),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        # 清空 DB
        with stockpile_db._connect() as conn:
            conn.execute("DELETE FROM stockpile")
            conn.execute("DELETE FROM stockpile_changes")
            conn.execute("DELETE FROM schema_meta")

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(stockpile_bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_status_uninitialized(self):
        res = self.client.get("/stockpile/status")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.get_json(),
            {
                "ok": True,
                "initialized": False,
                "count": 0,
                "active_count": 0,
                "inactive_count": 0,
                "last_import_at": None,
            },
        )

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
        self.assertEqual(list(self.test_dir.glob("junk.txt")), [])

    def test_init_imports_csv_and_status_reflects(self):
        csv_bytes = _make_csv_bytes(
            [
                {"product_barcode": "R1", "product_model": "M1", "stockpile_location": "L1"},
                {"product_barcode": "R2", "product_model": "M2", "stockpile_location": "L2"},
            ]
        )
        res = self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(csv_bytes), "init.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["count"], 2)
        # 临时文件被清理
        self.assertEqual(list(self.test_dir.glob("init.csv")), [])

        status = self.client.get("/stockpile/status").get_json()
        self.assertTrue(status["initialized"])
        self.assertEqual(status["count"], 2)
        self.assertEqual(status["active_count"], 2)
        self.assertEqual(status["inactive_count"], 0)
        # init 完成 → snapshot 写入 → last_import_at 应该是 "YYYY-MM-DD HH:MM:SS" 格式
        self.assertIsNotNone(status["last_import_at"])
        self.assertRegex(status["last_import_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_compare_returns_diff(self):
        # 先初始化
        local_csv = _make_csv_bytes(
            [
                {"product_barcode": "C1", "product_model": "M1", "stockpile_location": "L1"},
            ]
        )
        self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(local_csv), "local.csv")},
            content_type="multipart/form-data",
        )
        # 再比对
        export_csv = _make_csv_bytes(
            [
                {"product_barcode": "C1", "product_model": "M1_NEW", "stockpile_location": "L1"},
                {"product_barcode": "C2", "product_model": "M2", "stockpile_location": "L2"},
            ]
        )
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
        local_csv = _make_csv_bytes(
            [
                {"product_barcode": "A1", "product_model": "Old", "stockpile_location": "OldLoc"},
            ]
        )
        self.client.post(
            "/stockpile/init",
            data={"files": (io.BytesIO(local_csv), "local.csv")},
            content_type="multipart/form-data",
        )
        export_csv = _make_csv_bytes(
            [
                {"product_barcode": "A1", "product_model": "New", "stockpile_location": "NewLoc"},
            ]
        )
        res = self.client.post(
            "/stockpile/apply-export",
            data={"files": (io.BytesIO(export_csv), "export.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["updated"], 1)
        rec = stockpile_db.query_by_barcode("A1")
        self.assertEqual(rec["product_model"], "New")

    def test_inactive_endpoint_returns_inactive_records(self):
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                    {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
                ]
            )
        )
        stockpile_db.apply_export_updates(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )

        res = self.client.get("/stockpile/inactive")

        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["records"][0]["product_barcode"], "A2")

    def test_changes_endpoint_returns_recent_change_log(self):
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
                ]
            )
        )
        stockpile_db.insert_or_update("A1", "M1-new", "L1-new")

        res = self.client.get("/stockpile/changes?limit=2")

        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertGreaterEqual(payload["count"], 1)
        self.assertEqual(payload["changes"][0]["product_barcode"], "A1")

    def test_schema_endpoint_returns_current_version(self):
        res = self.client.get("/stockpile/schema")

        self.assertEqual(res.status_code, 200)
        from app import db

        self.assertEqual(res.get_json()["version"], db.SCHEMA_VERSION)

    def test_temp_file_cleaned_when_handler_raises(self):
        # 注入异常确认 finally 清理生效
        bad_csv = _make_csv_bytes(
            [
                {"product_barcode": "X1", "product_model": "M", "stockpile_location": "L"},
            ]
        )
        with mock.patch(
            "app.repositories.stockpile_db.import_from_dataframe", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/stockpile/init",
                    data={"files": (io.BytesIO(bad_csv), "boom.csv")},
                    content_type="multipart/form-data",
                )
        self.assertEqual(list(self.test_dir.glob("boom.csv")), [])

    # ---------- /stockpile/update-location（Pydantic 校验） ----------

    def _seed_one(self, barcode: str = "U1") -> None:
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [{"product_barcode": barcode, "product_model": "M1", "stockpile_location": "L1"}]
            )
        )

    def test_update_location_ok(self):
        self._seed_one("U1")
        res = self.client.post(
            "/stockpile/update-location", json={"barcode": "  U1  ", "location": "  NEW  "}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])
        self.assertEqual(stockpile_db.query_by_barcode("U1")["stockpile_location"], "NEW")

    def test_update_location_empty_location_clears(self):
        self._seed_one("U2")
        res = self.client.post("/stockpile/update-location", json={"barcode": "U2", "location": ""})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(stockpile_db.query_by_barcode("U2")["stockpile_location"], "")

    def test_update_location_missing_barcode_400(self):
        res = self.client.post("/stockpile/update-location", json={"location": "X"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("barcode", res.get_json()["msg"])

    def test_update_location_unknown_barcode_404(self):
        res = self.client.post(
            "/stockpile/update-location", json={"barcode": "DOES_NOT_EXIST", "location": "L"}
        )
        self.assertEqual(res.status_code, 404)

    # ---------- /stockpile/overwrite-locations（Pydantic 校验） ----------

    def test_overwrite_locations_ok(self):
        self._seed_one("O1")
        res = self.client.post(
            "/stockpile/overwrite-locations",
            json={"entries": [{"barcode": "O1", "location": "NEW"}]},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["updated"], 1)

    def test_overwrite_locations_empty_entries_400(self):
        res = self.client.post("/stockpile/overwrite-locations", json={"entries": []})
        self.assertEqual(res.status_code, 400)
        self.assertIn("entries", res.get_json()["msg"])

    def test_overwrite_locations_missing_entries_400(self):
        res = self.client.post("/stockpile/overwrite-locations", json={})
        self.assertEqual(res.status_code, 400)

    def test_overwrite_locations_silently_skips_bad_entries(self):
        # 兼容前端：单个 entry 内 barcode 缺失 → 跳过该条，不整请求 400
        self._seed_one("O2")
        res = self.client.post(
            "/stockpile/overwrite-locations",
            json={
                "entries": [
                    {"barcode": "", "location": "X"},
                    {"barcode": "O2", "location": "NEW"},
                    {"barcode": "UNKNOWN", "location": "Z"},
                ]
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["updated"], 1)


if __name__ == "__main__":
    unittest.main()
