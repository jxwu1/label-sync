"""单页取数去重重构测试。

目标：/sku/<barcode> 单次开页对同一货号的 _fetch_all_rows_with_doc_no
原本被 extras/holding/heatmap 各调一次(共 3 次)，改为路由取一次、传入复用(1 次)。

- TestA 行为对拍：4 个函数带 rows= 与不带 rows 结果逐字段相等(证明 rows 参数行为中性)。
- TestB 路由去重：GET /analytics/sku/<bc> 时 _fetch_all_rows_with_doc_no 只被调 1 次。
"""

from __future__ import annotations

import shutil
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from flask import Flask
from sqlalchemy import insert

from app.models import InventoryEvent, Stockpile
from app.repositories import stockpile_db
from app.services import analytics as ans

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_fetch_rows_dedup"
AS_OF = date(2026, 5, 1)


class _Base(unittest.TestCase):
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
        ans.clear_list_sku_summary_cache()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _add_event(
        self,
        *,
        barcode="B1",
        event_type="sale",
        event_at,
        qty,
        unit_price=None,
        discount_pct=None,
        customer_id=None,
        supplier_id=None,
        document_no=None,
    ) -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type=event_type,
                    product_barcode=barcode,
                    qty=qty,
                    unit_price=unit_price,
                    discount_pct=discount_pct,
                    customer_id=customer_id,
                    supplier_id=supplier_id,
                    document_no=document_no,
                )
            )
            s.commit()

    def _seed_sku(self, barcode="B1") -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(Stockpile).values(
                    product_barcode=barcode,
                    product_model=barcode,
                    stockpile_location="",
                    is_active=1,
                )
            )
            s.commit()

    def _seed_history(self, barcode="B1") -> None:
        # 一点采购 + 零售 + 批发 + 退货，覆盖 4 个函数都有料可算
        self._add_event(
            barcode=barcode,
            event_type="purchase",
            event_at="2026-01-10",
            qty=100,
            unit_price=1.0,
            supplier_id="S1",
            document_no="P-1",
        )
        self._add_event(
            barcode=barcode,
            event_type="sale",
            event_at="2026-02-15",
            qty=5,
            unit_price=2.5,
            document_no="MB001",
        )  # 零售
        self._add_event(
            barcode=barcode,
            event_type="sale",
            event_at="2026-03-20",
            qty=8,
            unit_price=2.0,
            customer_id="C1",
            document_no="W-9",
        )  # 批发
        self._add_event(
            barcode=barcode,
            event_type="sale",
            event_at="2026-04-01",
            qty=-2,
            unit_price=2.0,
            customer_id="C1",
            document_no="W-9",
        )  # 退货


# ── TestA: rows 参数行为中性 ──────────────────────────────────────────────
class BehaviorPreservedTests(_Base):
    def _assert_same(self, fn, **kw):
        rows = ans._fetch_all_rows_with_doc_no("B1", None)
        without = fn("B1", **kw)
        with_rows = fn("B1", rows=rows, **kw)
        self.assertEqual(without, with_rows)

    def test_sku_extras_rows_neutral(self):
        self._seed_history()
        self._assert_same(ans.compute_sku_extras, as_of=AS_OF)
        # 非平凡断言: 防 tautology(两边都空相等). 验证确实从种子数据算出了东西。
        extras = ans.compute_sku_extras("B1", as_of=AS_OF)
        self.assertEqual(extras["return_qty"], 2)  # 一笔 -2 退货
        self.assertEqual(extras["total_sale_qty_gross"], 13)  # 5 零售 + 8 批发

    def test_avg_holding_days_rows_neutral(self):
        self._seed_history()
        self._assert_same(ans.compute_avg_holding_days)

    def test_monthly_heatmap_rows_neutral(self):
        self._seed_history()
        self._assert_same(ans.compute_monthly_heatmap)


# ── TestB: /sku 路由只取一次 ──────────────────────────────────────────────
class RouteDedupTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        from app.routes.analytics import bp

        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def test_sku_page_fetches_rows_once(self):
        self._seed_sku()
        self._seed_history()
        with mock.patch.object(
            ans,
            "_fetch_all_rows_with_doc_no",
            wraps=ans._fetch_all_rows_with_doc_no,
        ) as spy:
            resp = self.client.get("/analytics/sku/B1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(spy.call_count, 1, f"应只取一次, 实际 {spy.call_count} 次")
