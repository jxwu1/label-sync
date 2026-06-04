"""routes_analytics 单测。HTTP 层薄包装，重点覆盖参数与 404 路径。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask
from sqlalchemy import insert

from app.repositories import stockpile_db
from app.models import InventoryEvent, Stockpile
from app.routes.analytics import bp

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_routes_analytics"


class AnalyticsRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()
        from app.services import analytics as _ans

        _ans.clear_list_sku_summary_cache()

        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _seed_sku(self, barcode: str = "B1", **fields) -> None:
        values = {
            "product_barcode": barcode,
            "product_model": barcode,
            "stockpile_location": "",
            "is_active": 1,
        }
        values.update(fields)
        with stockpile_db._session() as s:
            s.execute(insert(Stockpile).values(**values))
            s.commit()

    def _seed_sale(self, barcode: str = "B1", event_at: str = "2026-04-15", qty: int = 10):
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type="sale",
                    product_barcode=barcode,
                    qty=qty,
                    unit_price=2.5,
                    document_no=f"D-{event_at}",
                )
            )
            s.commit()

    def test_unknown_barcode_returns_404(self) -> None:
        resp = self.client.get("/analytics/sku/NOPE")
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()["ok"])

    def test_existing_sku_returns_full_bundle(self) -> None:
        self._seed_sku(
            barcode="B1",
            auto_category="new",
            manual_category=None,
            manual_grade=5,
        )
        self._seed_sale(barcode="B1", event_at="2026-04-15", qty=10)
        resp = self.client.get("/analytics/sku/B1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["barcode"], "B1")
        self.assertIn("sales", data)
        self.assertIn("purchase", data)
        self.assertIn("customer_split", data)
        self.assertIn("qty_percentile", data)
        self.assertEqual(data["auto_category"], "new")
        self.assertEqual(data["manual_grade"], 5)
        # sales metrics 实际有内容
        self.assertEqual(data["sales"]["total_qty"], 10)

    def test_qty_percentile_lowest(self) -> None:
        """3 个 SKU 销量 1/5/10：销 1 的那个是底部 → 0%。"""
        self._seed_sku("LOW", manual_grade=8)  # 高等级低销 → 等级失真
        self._seed_sku("MID")
        self._seed_sku("HIGH")
        self._seed_sale("LOW", "2026-04-15", 1)
        self._seed_sale("MID", "2026-04-15", 5)
        self._seed_sale("HIGH", "2026-04-15", 10)

        resp = self.client.get("/analytics/sku/LOW")
        data = resp.get_json()
        self.assertEqual(data["qty_percentile"], 0.0)

        resp = self.client.get("/analytics/sku/HIGH")
        data = resp.get_json()
        # 比 1 + 5 都大 = 2/3 = 66.7%
        self.assertAlmostEqual(data["qty_percentile"], 66.7, places=1)


class ManualCategoryTests(AnalyticsRoutesTests):
    def test_set_valid_category(self) -> None:
        self._seed_sku("B1")
        resp = self.client.post(
            "/analytics/sku/B1/manual-category",
            json={"category": "网红昙花"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["manual_category"], "网红昙花")

        # 复查 GET
        resp = self.client.get("/analytics/sku/B1")
        self.assertEqual(resp.get_json()["manual_category"], "网红昙花")

    def test_clear_with_empty_string(self) -> None:
        self._seed_sku("B1", manual_category="滞销")
        resp = self.client.post(
            "/analytics/sku/B1/manual-category",
            json={"category": ""},
        )
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIsNone(data["manual_category"])

    def test_invalid_category_returns_400(self) -> None:
        self._seed_sku("B1")
        resp = self.client.post(
            "/analytics/sku/B1/manual-category",
            json={"category": "随便编一个"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_unknown_barcode_returns_404(self) -> None:
        resp = self.client.post(
            "/analytics/sku/NOPE/manual-category",
            json={"category": "滞销"},
        )
        self.assertEqual(resp.status_code, 404)


class TimelineTests(AnalyticsRoutesTests):
    def test_timeline_returns_156_weeks_and_36_months(self) -> None:
        """2026-05-23: timeline 扩 3 年 (156 周) + 月度销量聚合 (36 月) 给前端柱图."""
        self._seed_sku("B1")
        self._seed_sale("B1", "2026-04-15", 5)
        resp = self.client.get("/analytics/sku/B1/timeline")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["timeline"]), 156)
        wk = data["timeline"][0]
        self.assertIn("week_start", wk)
        self.assertIn("sale_qty", wk)
        self.assertIn("purchase_unit_price", wk)
        self.assertEqual(len(data["monthly_sales"]), 36)
        mo = data["monthly_sales"][0]
        self.assertIn("month_start", mo)
        self.assertIn("sale_qty", mo)
        self.assertIn("retail_qty", mo)

    def test_timeline_aggregates_purchase_price_average(self) -> None:
        from sqlalchemy import insert as sa_insert

        from app.models import InventoryEvent

        self._seed_sku("B1")
        # 同一周内两条采购，均价 = (5 + 7) / 2 = 6
        with stockpile_db._session() as s:
            for i, price in enumerate([5.0, 7.0]):
                s.execute(
                    sa_insert(InventoryEvent).values(
                        event_at="2026-04-01",
                        event_type="purchase",
                        product_barcode="B1",
                        qty=10,
                        unit_price=price,
                        document_no=f"P{i}",
                    )
                )
            s.commit()

        resp = self.client.get("/analytics/sku/B1/timeline")
        timeline = resp.get_json()["timeline"]
        # 找到 2026-04 那周
        wk = next(
            (
                t
                for t in timeline
                if t["week_start"].startswith("2026-03-30") or t["purchase_unit_price"] is not None
            ),
            None,
        )
        self.assertIsNotNone(wk)
        self.assertEqual(wk["purchase_unit_price"], 6.0)


class ListEndpointTests(AnalyticsRoutesTests):
    def test_list_returns_non_discontinued_skus_with_aggregates(self) -> None:
        # 新口径 (2026-05-21): 过滤 is_truly_discontinued, 不再用 is_active.
        # is_active=0 (网店下架) 但还在卖的货也要进列表.
        self._seed_sku("B1", auto_category="stable", manual_grade=5)
        self._seed_sku("B2", auto_category="new")
        self._seed_sku("B3_OFFLINE", is_active=0)  # 网店下架但保留
        self._seed_sku("B4_DEAD", is_truly_discontinued=True)  # 应被过滤
        self._seed_sale("B1", "2026-04-01", 10)
        self._seed_sale("B1", "2026-04-15", 5)
        self._seed_sale("B2", "2026-04-25", 100)

        resp = self.client.get("/analytics/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 3)
        bcs = {it["barcode"] for it in data["items"]}
        self.assertEqual(bcs, {"B1", "B2", "B3_OFFLINE"})
        b1 = next(it for it in data["items"] if it["barcode"] == "B1")
        self.assertEqual(b1["total_qty"], 15)
        self.assertEqual(b1["lifespan_days"], 14)

    def test_list_grade_inconsistent_flag(self) -> None:
        # 高等级低销 → warn
        self._seed_sku("HI_GRADE_LOW_SALES", manual_grade=9)
        self._seed_sku("MID_QTY")
        self._seed_sale("HI_GRADE_LOW_SALES", "2026-04-01", 1)
        self._seed_sale("MID_QTY", "2026-04-01", 100)

        resp = self.client.get("/analytics/list")
        items = resp.get_json()["items"]
        hi = next(it for it in items if it["barcode"] == "HI_GRADE_LOW_SALES")
        # 1 件 → 排在 0% 分位（mid_qty 100 件比它多）
        self.assertEqual(hi["qty_percentile"], 0.0)
        self.assertTrue(hi["is_grade_inconsistent"])


class BacktestRoutesTests(AnalyticsRoutesTests):
    """plan §2.7 回测 HTTP 层薄包装."""

    def _seed_weekly(self, barcode: str = "B1", weeks: int = 30, qty: int = 5) -> None:
        from datetime import date, timedelta

        with stockpile_db._session() as s:
            for w in range(weeks):
                d = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=d,
                        event_type="sale",
                        product_barcode=barcode,
                        qty=qty,
                        document_no=f"{barcode}-D{w}",
                    )
                )
            s.commit()

    def test_post_run_writes_run_returns_id(self) -> None:
        self._seed_sku("B1")
        self._seed_weekly("B1", weeks=30)
        resp = self.client.post(
            "/analytics/backtest/run",
            json={
                "model_name": "NaiveMean4W",
                "end_date": "2026-05-13",
                "weeks": 30,
                "barcodes": ["B1"],
                "notes": "smoke",
            },
        )
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIsInstance(body["run_id"], int)

    def test_post_run_bad_end_date(self) -> None:
        resp = self.client.post(
            "/analytics/backtest/run",
            json={"model_name": "NaiveMean4W", "end_date": "not-a-date"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_run_unknown_model(self) -> None:
        resp = self.client.post(
            "/analytics/backtest/run",
            json={"model_name": "Nope", "end_date": "2026-05-13", "barcodes": []},
        )
        self.assertEqual(resp.status_code, 400)

    def test_get_runs_lists_recent(self) -> None:
        self._seed_sku("B1")
        self._seed_weekly("B1", weeks=30)
        post = self.client.post(
            "/analytics/backtest/run",
            json={"model_name": "NaiveMean4W", "end_date": "2026-05-13", "barcodes": ["B1"]},
        )
        run_id = post.get_json()["run_id"]
        resp = self.client.get("/analytics/backtest/runs")
        body = resp.get_json()
        self.assertTrue(body["ok"])
        ids = [r["id"] for r in body["runs"]]
        self.assertIn(run_id, ids)

    def test_get_results_by_run_id(self) -> None:
        self._seed_sku("B1")
        self._seed_weekly("B1", weeks=30)
        post = self.client.post(
            "/analytics/backtest/run",
            json={"model_name": "NaiveMean4W", "end_date": "2026-05-13", "barcodes": ["B1"]},
        )
        run_id = post.get_json()["run_id"]
        resp = self.client.get(f"/analytics/backtest/results?run_id={run_id}")
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["product_barcode"], "B1")
        self.assertEqual(body["results"][0]["sku_type"], "retail_dominant")

    def test_get_results_missing_run_id(self) -> None:
        resp = self.client.get("/analytics/backtest/results")
        self.assertEqual(resp.status_code, 400)

    def test_compare_returns_summary(self) -> None:
        self._seed_sku("B1")
        self._seed_weekly("B1", weeks=30)
        post_a = self.client.post(
            "/analytics/backtest/run",
            json={
                "model_name": "NaiveMean4W",
                "end_date": "2026-05-13",
                "view": "all",
                "barcodes": ["B1"],
            },
        )
        post_b = self.client.post(
            "/analytics/backtest/run",
            json={
                "model_name": "NaiveMean4W",
                "end_date": "2026-05-13",
                "view": "base_demand",
                "barcodes": ["B1"],
            },
        )
        a = post_a.get_json()["run_id"]
        b = post_b.get_json()["run_id"]
        resp = self.client.get(f"/analytics/backtest/compare?run_a={a}&run_b={b}")
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["common_skus"], 1)

    def test_compare_missing_param(self) -> None:
        resp = self.client.get("/analytics/backtest/compare?run_a=1")
        self.assertEqual(resp.status_code, 400)

    def test_compare_unknown_run(self) -> None:
        resp = self.client.get("/analytics/backtest/compare?run_a=99999&run_b=99998")
        self.assertEqual(resp.status_code, 404)

    # /backtest/summary 仅覆盖 validation 路径 (SQL 用 PG-only percentile_cont
    # + DISTINCT ON, SQLite 测试 DB 跑不了). 端到端验证通过线上 curl 完成.

    def test_summary_missing_run_id(self) -> None:
        resp = self.client.get("/analytics/backtest/summary")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("run_id", body["msg"])

    def test_summary_bad_run_id_parse(self) -> None:
        resp = self.client.get("/analytics/backtest/summary?run_id=abc")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("整数", body["msg"])

    def test_summary_bad_origin(self) -> None:
        resp = self.client.get("/analytics/backtest/summary?run_id=1&origin=xyz")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("origin", body["msg"])

    def test_sales_top_bad_origin(self) -> None:
        resp = self.client.get("/analytics/sales/top?origin=xyz")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("origin", resp.get_json()["msg"])

    def test_sales_top_bad_weeks(self) -> None:
        resp = self.client.get("/analytics/sales/top?weeks=2")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("weeks", resp.get_json()["msg"])

    def test_sales_top_bad_format(self) -> None:
        resp = self.client.get("/analytics/sales/top?format=xml")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("format", resp.get_json()["msg"])

    def test_top_bad_origin(self) -> None:
        resp = self.client.get("/analytics/forecast/top?origin=xyz")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("origin", resp.get_json()["msg"])

    def test_top_bad_limit(self) -> None:
        resp = self.client.get("/analytics/forecast/top?limit=99999")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("limit", resp.get_json()["msg"])

    def test_top_bad_format(self) -> None:
        resp = self.client.get("/analytics/forecast/top?format=xml")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("format", resp.get_json()["msg"])

    def test_sales_top_bad_exclude_discontinued(self) -> None:
        resp = self.client.get("/analytics/sales/top?exclude_discontinued=maybe")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("exclude_discontinued", resp.get_json()["msg"])

    def test_forecast_top_bad_exclude_discontinued(self) -> None:
        resp = self.client.get("/analytics/forecast/top?exclude_discontinued=maybe")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("exclude_discontinued", resp.get_json()["msg"])

    def test_upload_missing_token_env_returns_500(self) -> None:
        import os

        os.environ.pop("UPLOAD_TOKEN", None)
        resp = self.client.post("/analytics/data/upload")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("UPLOAD_TOKEN", resp.get_json()["msg"])

    def test_upload_bad_token_returns_401(self) -> None:
        import os

        os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
        try:
            resp = self.client.post(
                "/analytics/data/upload",
                headers={"X-Upload-Token": "wrong"},
            )
            self.assertEqual(resp.status_code, 401)
        finally:
            os.environ.pop("UPLOAD_TOKEN", None)

    def test_upload_no_file_returns_400(self) -> None:
        import os

        os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
        try:
            resp = self.client.post(
                "/analytics/data/upload",
                headers={"X-Upload-Token": "secret_token_abc"},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("file", resp.get_json()["msg"])
        finally:
            os.environ.pop("UPLOAD_TOKEN", None)

    def test_upload_rejects_purchase_with_price(self) -> None:
        """2026-05-21 起策略变更: 带进价的 purchase parquet 接收 + 回填
        stockpile.last_purchase_unit_price (折后净价)."""
        import os
        import pathlib
        import tempfile

        import pandas as pd

        os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
        self._seed_sku("B1")  # seed stockpile, 让回填有目标
        df = pd.DataFrame(
            {
                "event_at": ["2026-04-01"],
                "event_type": ["purchase"],
                "product_barcode": ["B1"],
                "qty": [10],
                "unit_price": [1.23],
                "discount_pct": [10.0],  # 折后净 = 1.23 * 0.9 = 1.107
                "document_no": ["DOC1"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            df.to_parquet(tmp.name, engine="pyarrow")
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as fp:
                resp = self.client.post(
                    "/analytics/data/upload",
                    headers={"X-Upload-Token": "secret_token_abc"},
                    data={"file": (fp, "events_purchase_2026-04.parquet")},
                    content_type="multipart/form-data",
                )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.get_json()["ok"])

            from app.models import Stockpile

            with stockpile_db._session() as s:
                row = s.execute(
                    stockpile_db.select(Stockpile).where(Stockpile.product_barcode == "B1")
                ).scalar_one()
                self.assertIsNotNone(row.last_purchase_unit_price)
                self.assertAlmostEqual(row.last_purchase_unit_price, 1.107, places=4)
        finally:
            os.environ.pop("UPLOAD_TOKEN", None)
            pathlib.Path(tmp_path).unlink(missing_ok=True)

    def test_upload_rejects_non_events_filename(self) -> None:
        import io
        import os

        os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
        try:
            resp = self.client.post(
                "/analytics/data/upload",
                headers={"X-Upload-Token": "secret_token_abc"},
                data={
                    "file": (io.BytesIO(b"fake"), "inventory_snapshot.parquet"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("events_", resp.get_json()["msg"])
        finally:
            os.environ.pop("UPLOAD_TOKEN", None)

    def test_upload_inventory_success(self) -> None:
        """合法 inventory_snapshot parquet 应成功 import."""
        import os
        import tempfile

        import pandas as pd

        os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
        df = pd.DataFrame(
            {
                "snapshot_date": ["2026-05-20"] * 2,
                "product_model": ["10110", "10111"],
                "product_name_zh": ["渔具工具 弹弓", "渔具 钓鱼 报警器"],
                "erp_category_code": ["A001-0904", "A001-0101"],
                "erp_category_raw": ["渔具-工具 弹弓", "渔具-渔具 配件"],
                "last_purchase_at": ["2026-01-19", "2023-03-11"],
                "last_arrival_at": ["2026-04-11", "2023-04-24"],
                "qty_store": [294, 195],
                "qty_total": [294, 195],
                "reorder_min": [180, 640],
                "reorder_max": [540, 1920],
                "is_discontinued_in_erp": [False, False],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            df.to_parquet(tmp.name, engine="pyarrow")
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as fp:
                resp = self.client.post(
                    "/analytics/data/upload",
                    headers={"X-Upload-Token": "secret_token_abc"},
                    data={"file": (fp, "inventory_snapshot_2026-05-20.parquet")},
                    content_type="multipart/form-data",
                )
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["kind"], "inventory_snapshot")
            self.assertEqual(body["snapshot_date"], "2026-05-20")
            self.assertEqual(body["rows_imported"], 2)
            self.assertEqual(body["rows_replaced"], 0)
        finally:
            os.environ.pop("UPLOAD_TOKEN", None)
            import pathlib

            pathlib.Path(tmp_path).unlink(missing_ok=True)

    def test_upload_inventory_replaces_existing(self) -> None:
        """重复上传同 snapshot_date 应替换 (rows_replaced > 0)."""
        import os
        import tempfile

        import pandas as pd

        os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
        df = pd.DataFrame(
            {
                "snapshot_date": ["2026-05-20"],
                "product_model": ["10110"],
                "product_name_zh": ["test"],
                "erp_category_code": [None],
                "erp_category_raw": [None],
                "last_purchase_at": [None],
                "last_arrival_at": [None],
                "qty_store": [10],
                "qty_total": [10],
                "reorder_min": [None],
                "reorder_max": [None],
                "is_discontinued_in_erp": [False],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            df.to_parquet(tmp.name, engine="pyarrow")
            tmp_path = tmp.name

        try:
            for i in range(2):
                with open(tmp_path, "rb") as fp:
                    resp = self.client.post(
                        "/analytics/data/upload",
                        headers={"X-Upload-Token": "secret_token_abc"},
                        data={"file": (fp, "inventory_snapshot_2026-05-20.parquet")},
                        content_type="multipart/form-data",
                    )
                body = resp.get_json()
                if i == 0:
                    self.assertEqual(body["rows_replaced"], 0)
                    self.assertEqual(body["rows_imported"], 1)
                else:
                    self.assertEqual(body["rows_replaced"], 1)
                    self.assertEqual(body["rows_imported"], 1)
        finally:
            os.environ.pop("UPLOAD_TOKEN", None)
            import pathlib

            pathlib.Path(tmp_path).unlink(missing_ok=True)

    def test_upload_inventory_missing_snapshot_date_column(self) -> None:
        """inventory parquet 缺 snapshot_date 列应被拒收."""
        import os
        import tempfile

        import pandas as pd

        os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
        # 故意不放 snapshot_date 列
        df = pd.DataFrame(
            {
                "product_model": ["10110"],
                "qty_total": [10],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            df.to_parquet(tmp.name, engine="pyarrow")
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as fp:
                resp = self.client.post(
                    "/analytics/data/upload",
                    headers={"X-Upload-Token": "secret_token_abc"},
                    data={"file": (fp, "inventory_snapshot_2026-05-20.parquet")},
                    content_type="multipart/form-data",
                )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("snapshot_date", resp.get_json()["msg"])
        finally:
            os.environ.pop("UPLOAD_TOKEN", None)
            import pathlib

            pathlib.Path(tmp_path).unlink(missing_ok=True)

    def test_forecast_refresh_returns_stats(self) -> None:
        """§3.7 POST /forecast/refresh: 空库返回 n_total=0."""
        resp = self.client.post("/analytics/forecast/refresh")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["n_total"], 0)
        self.assertEqual(body["n_written"], 0)

    def test_categories_recompute_returns_stats(self) -> None:
        """POST /categories/recompute: 空库返回 computed=0."""
        resp = self.client.post("/analytics/categories/recompute")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["computed"], 0)
        self.assertIn("by_category", body)

    def test_categories_recompute_counts_seeded_sku(self) -> None:
        """有 active SKU 时 computed 计入该 SKU。"""
        self._seed_sku("B1")
        resp = self.client.post("/analytics/categories/recompute")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["computed"], 1)

    def _count_sku_summary(self) -> int:
        from sqlalchemy import func, select

        from app.models import SkuSummary

        with stockpile_db._session() as s:
            return s.execute(select(func.count()).select_from(SkuSummary)).scalar_one()

    def test_forecast_refresh_rebuilds_sku_summary(self) -> None:
        """POST /forecast/refresh 后物化表被同步重建（forecast 数据进 payload）。"""
        self._seed_sku("B1")
        self.assertEqual(self._count_sku_summary(), 0)
        resp = self.client.post("/analytics/forecast/refresh")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._count_sku_summary(), 1)

    def test_categories_recompute_rebuilds_sku_summary(self) -> None:
        """POST /categories/recompute 后物化表被同步重建（auto_category 进 payload）。"""
        self._seed_sku("B1")
        self.assertEqual(self._count_sku_summary(), 0)
        resp = self.client.post("/analytics/categories/recompute")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._count_sku_summary(), 1)


if __name__ == "__main__":
    unittest.main()
