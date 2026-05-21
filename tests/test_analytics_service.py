"""analytics_service 单测（PR 5.1）。

覆盖：
- 销售面 5 指标（含零数据 / 单笔 / 多笔 / 12 周斜率）
- 采购面 4 指标（含库存推算正负 / 毛利率 / 频率窗口边界）
- 客户端拆分（chinese / foreign / mixed 不计入）
"""

from __future__ import annotations

import shutil
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import insert

from app.repositories import stockpile_db
from app.models import Customer, InventoryEvent

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_analytics"


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

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _add_event(
        self,
        *,
        barcode: str = "B1",
        event_type: str = "sale",
        event_at: str,
        qty: int,
        unit_price: float | None = None,
        discount_pct: float | None = None,
        customer_id: str | None = None,
        supplier_id: str | None = None,
        document_no: str | None = None,
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

    def _add_customer(self, customer_id: str, customer_type: str, name: str = "C") -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(Customer).values(
                    customer_id=customer_id,
                    customer_name=name,
                    customer_type=customer_type,
                )
            )
            s.commit()


class SalesMetricsTests(_Base):
    def test_no_sales_returns_zeros(self) -> None:
        from app.services.analytics import compute_sales_metrics

        m = compute_sales_metrics("NOPE", as_of=date(2026, 5, 1))
        assert m["total_qty"] == 0
        assert m["total_revenue"] == 0.0
        assert m["unique_customers"] == 0
        assert m["lifespan_days"] == 0
        assert m["trend_slope_pct_per_week"] is None

    def test_single_sale(self) -> None:
        from app.services.analytics import compute_sales_metrics

        self._add_event(event_at="2026-04-15", qty=10, unit_price=2.5, customer_id="C1")
        m = compute_sales_metrics("B1", as_of=date(2026, 5, 1))
        assert m["total_qty"] == 10
        assert m["total_revenue"] == 25.0
        assert m["unique_customers"] == 1
        assert m["lifespan_days"] == 0

    def test_revenue_applies_discount(self) -> None:
        from app.services.analytics import compute_sales_metrics

        # 10 × 2.5 × (1 - 20%) = 20.0
        self._add_event(event_at="2026-04-15", qty=10, unit_price=2.5, discount_pct=20.0)
        m = compute_sales_metrics("B1", as_of=date(2026, 5, 1))
        assert m["total_revenue"] == 20.0

    def test_lifespan_days(self) -> None:
        from app.services.analytics import compute_sales_metrics

        self._add_event(event_at="2026-01-01", qty=1)
        self._add_event(event_at="2026-04-15", qty=2, document_no="D2")
        m = compute_sales_metrics("B1", as_of=date(2026, 5, 1))
        assert m["lifespan_days"] == 104  # 2026-01-01 → 2026-04-15

    def test_unique_customers_counts_distinct(self) -> None:
        from app.services.analytics import compute_sales_metrics

        self._add_event(event_at="2026-04-01", qty=1, customer_id="C1", document_no="D1")
        self._add_event(event_at="2026-04-02", qty=1, customer_id="C1", document_no="D2")
        self._add_event(event_at="2026-04-03", qty=1, customer_id="C2", document_no="D3")
        # null customer 不计
        self._add_event(event_at="2026-04-04", qty=1, document_no="D4")
        m = compute_sales_metrics("B1", as_of=date(2026, 5, 1))
        assert m["unique_customers"] == 2

    def test_trend_slope_increasing(self) -> None:
        """每周销量递增 → 斜率 > 0。"""
        from app.services.analytics import compute_sales_metrics

        as_of = date(2026, 5, 1)
        # 12 周，每周一笔，销量 1, 2, ..., 12
        for i in range(12):
            week_start = as_of - timedelta(days=(11 - i) * 7 + 1)
            self._add_event(
                event_at=week_start.isoformat(),
                qty=i + 1,
                document_no=f"D{i}",
            )
        m = compute_sales_metrics("B1", as_of=as_of)
        assert m["trend_slope_pct_per_week"] is not None
        assert m["trend_slope_pct_per_week"] > 0

    def test_trend_slope_none_when_all_outside_window(self) -> None:
        """所有销售都在 12 周外 → 趋势 None。"""
        from app.services.analytics import compute_sales_metrics

        # 1 年前的销售
        self._add_event(event_at="2025-04-01", qty=100)
        m = compute_sales_metrics("B1", as_of=date(2026, 5, 1))
        assert m["trend_slope_pct_per_week"] is None
        assert m["total_qty"] == 100  # total_qty 不受窗口限制


class PurchaseMetricsTests(_Base):
    def test_no_events(self) -> None:
        from app.services.analytics import compute_purchase_metrics

        m = compute_purchase_metrics("NOPE", as_of=date(2026, 5, 1))
        assert m["stock_balance"] == 0
        assert m["avg_margin_pct"] is None
        assert m["purchase_freq_365d"] == 0
        assert m["last_purchase_days_ago"] is None

    def test_stock_balance_positive(self) -> None:
        from app.services.analytics import compute_purchase_metrics

        self._add_event(event_type="purchase", event_at="2026-01-01", qty=100)
        self._add_event(event_type="sale", event_at="2026-02-01", qty=30, document_no="S1")
        m = compute_purchase_metrics("B1", as_of=date(2026, 5, 1))
        assert m["stock_balance"] == 70

    def test_stock_balance_negative(self) -> None:
        """卖得比进得多（早期没数据补全） → 负数。"""
        from app.services.analytics import compute_purchase_metrics

        self._add_event(event_type="sale", event_at="2026-02-01", qty=50)
        m = compute_purchase_metrics("B1", as_of=date(2026, 5, 1))
        assert m["stock_balance"] == -50

    def test_avg_margin_pct(self) -> None:
        """进 6 / 售 10 不打折 → margin (10-6)/10 = 40%."""
        from app.services.analytics import compute_purchase_metrics

        self._add_event(event_type="purchase", event_at="2026-01-01", qty=10, unit_price=6.0)
        self._add_event(event_type="sale", event_at="2026-02-01", qty=5, unit_price=10.0)
        m = compute_purchase_metrics("B1", as_of=date(2026, 5, 1))
        assert m["avg_margin_pct"] == 40.0

    def test_avg_margin_none_when_no_purchases_with_price(self) -> None:
        from app.services.analytics import compute_purchase_metrics

        self._add_event(event_type="sale", event_at="2026-02-01", qty=5, unit_price=10.0)
        m = compute_purchase_metrics("B1", as_of=date(2026, 5, 1))
        assert m["avg_margin_pct"] is None

    def test_purchase_freq_365d_window(self) -> None:
        from app.services.analytics import compute_purchase_metrics

        as_of = date(2026, 5, 1)
        # 在窗口内
        self._add_event(event_type="purchase", event_at="2025-12-01", qty=10)
        self._add_event(event_type="purchase", event_at="2026-04-01", qty=10, document_no="P2")
        # 366 天前 → 在窗口外
        self._add_event(event_type="purchase", event_at="2025-04-30", qty=10, document_no="P3")
        m = compute_purchase_metrics("B1", as_of=as_of)
        assert m["purchase_freq_365d"] == 2

    def test_last_purchase_days_ago(self) -> None:
        from app.services.analytics import compute_purchase_metrics

        self._add_event(event_type="purchase", event_at="2026-04-21", qty=10)
        m = compute_purchase_metrics("B1", as_of=date(2026, 5, 1))
        assert m["last_purchase_days_ago"] == 10


class CustomerSplitTests(_Base):
    def test_split_separates_cn_fo(self) -> None:
        from app.services.analytics import compute_customer_split

        self._add_customer("CN1", "chinese", "张三")
        self._add_customer("FO1", "foreign", "GIANNIS")
        self._add_customer("MX1", "mixed", "张三 GIANNIS")
        self._add_event(event_at="2026-04-01", qty=100, customer_id="CN1", document_no="D1")
        self._add_event(event_at="2026-04-02", qty=5, customer_id="FO1", document_no="D2")
        self._add_event(event_at="2026-04-03", qty=99, customer_id="MX1", document_no="D3")

        split = compute_customer_split("B1", as_of=date(2026, 5, 1))
        # mixed 不计入 cn 也不计入 fo
        assert split["cn"]["qty"] == 100
        assert split["cn"]["unique_customers"] == 1
        assert split["fo"]["qty"] == 5
        assert split["fo"]["unique_customers"] == 1

    def test_split_max_single_qty(self) -> None:
        from app.services.analytics import compute_customer_split

        self._add_customer("FO1", "foreign", "GIANNIS")
        self._add_event(event_at="2026-04-01", qty=3, customer_id="FO1", document_no="D1")
        self._add_event(event_at="2026-04-02", qty=12, customer_id="FO1", document_no="D2")
        self._add_event(event_at="2026-04-03", qty=7, customer_id="FO1", document_no="D3")

        split = compute_customer_split("B1", as_of=date(2026, 5, 1))
        assert split["fo"]["max_single_qty"] == 12
        assert split["fo"]["last_at"] == "2026-04-03"

    def test_split_empty_when_no_sales(self) -> None:
        from app.services.analytics import compute_customer_split

        split = compute_customer_split("NOPE", as_of=date(2026, 5, 1))
        assert split["cn"]["qty"] == 0
        assert split["fo"]["qty"] == 0
        assert split["cn"]["last_at"] is None
        assert split["fo"]["last_at"] is None


class RecomputeCategoriesTests(_Base):
    def _add_stockpile(self, barcode: str, is_active: int = 1) -> None:
        from app.models import Stockpile

        with stockpile_db._session() as s:
            s.execute(
                insert(Stockpile).values(
                    product_barcode=barcode,
                    product_model=barcode,
                    stockpile_location="",
                    is_active=is_active,
                )
            )
            s.commit()

    def test_recompute_writes_auto_category(self) -> None:
        from app.services.analytics import recompute_categories
        from app.models import Stockpile

        # SKU 1: 新品（最近一笔）
        self._add_stockpile("NEW1")
        self._add_event(barcode="NEW1", event_at="2026-04-25", qty=5)
        # SKU 2: 无销售 → unclassified
        self._add_stockpile("EMPTY1")
        # SKU 3: inactive 不应被处理
        self._add_stockpile("INACT1", is_active=0)
        self._add_event(barcode="INACT1", event_at="2026-04-25", qty=5, document_no="X1")

        result = recompute_categories(as_of=date(2026, 5, 1))
        assert result["computed"] == 2  # 跳过 INACT1
        assert result["by_category"]["new"] == 1
        assert result["by_category"]["unclassified"] == 1

        with stockpile_db._session() as s:
            new1 = s.execute(
                stockpile_db.select(Stockpile).where(Stockpile.product_barcode == "NEW1")
            ).scalar_one()
            assert new1.auto_category == "new"
            assert new1.auto_category_computed_at is not None

            inact1 = s.execute(
                stockpile_db.select(Stockpile).where(Stockpile.product_barcode == "INACT1")
            ).scalar_one()
            assert inact1.auto_category is None  # 没动


class UrgencyScoreTests(unittest.TestCase):
    """_compute_urgency_score 单测（纯函数，无 DB）。"""

    def test_new_item_returns_all_none(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(0.9, 2.0, 30, is_new_item=True)
        assert out == {"total": None, "velocity": None, "cover": None, "recency": None}

    def test_sold_out_top_seller_long_no_purchase_maxes_out(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(velocity_pctile=1.0, weeks_of_cover=0.0, last_purchase_days=200)
        assert out["velocity"] == 50.0
        assert out["cover"] == 30.0
        assert out["recency"] == 20.0
        assert out["total"] == 100.0

    def test_just_restocked_low_recency(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(velocity_pctile=0.5, weeks_of_cover=10.0, last_purchase_days=0)
        assert out["velocity"] == 25.0
        assert out["cover"] == 0.0
        assert out["recency"] == 0.0
        assert out["total"] == 25.0

    def test_no_history_zero_score(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(velocity_pctile=0.0, weeks_of_cover=None, last_purchase_days=None)
        assert out == {"total": 0.0, "velocity": 0.0, "cover": 0.0, "recency": 0.0}

    def test_negative_weeks_of_cover_caps_at_max_not_overflow(self) -> None:
        """ERP 超卖待到货 → qty_total<0 → weeks_of_cover<0 → cover 项应 cap 30, 总分 ≤100."""
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(velocity_pctile=0.5, weeks_of_cover=-62.1, last_purchase_days=0)
        assert out["cover"] == 30.0  # 负库存按 0 库存满分, 不溢出
        assert out["total"] <= 100.0
        assert out["total"] == 25.0 + 30.0 + 0.0

    def test_cover_clamped_at_zero_when_overstocked(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(velocity_pctile=0.8, weeks_of_cover=50.0, last_purchase_days=10)
        assert out["cover"] == 0.0


class ListSkuSummaryRestockFieldsTests(_Base):
    """list_sku_summary 新增字段（补货决策面板用）端到端测试。"""

    def _add_sku(self, barcode: str, model: str | None = None, **fields) -> None:
        from app.models import Stockpile

        values = {
            "product_barcode": barcode,
            "product_model": model or barcode,
            "stockpile_location": "",
            "is_active": 1,
        }
        values.update(fields)
        with stockpile_db._session() as s:
            s.execute(insert(Stockpile).values(**values))
            s.commit()

    def _add_snapshot(self, snapshot_date: str, model: str, qty: int) -> None:
        from app.models import StockpileInventorySnapshot

        with stockpile_db._session() as s:
            s.execute(
                insert(StockpileInventorySnapshot).values(
                    snapshot_date=snapshot_date,
                    product_model=model,
                    qty_total=qty,
                )
            )
            s.commit()

    def test_new_fields_present_and_typed(self) -> None:
        from app.services.analytics import list_sku_summary

        self._add_sku("12345", model="12345")
        self._add_event(barcode="12345", event_at="2026-04-20", qty=10, document_no="S1")
        self._add_event(
            barcode="12345", event_type="purchase",
            event_at="2026-03-01", qty=50, supplier_id="GR01", document_no="P1",
        )
        self._add_snapshot("2026-05-19", "12345", 8)

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "12345")
        assert it["qty_total"] == 8
        assert it["origin"] == "FOREIGN"
        assert it["last_purchase_at"] == "2026-03-01"
        assert it["last_purchase_days_ago"] == 81
        assert it["weekly_velocity"] > 0
        assert it["weeks_of_cover"] is not None
        assert "urgency_score" in it
        assert "urgency_breakdown" in it
        assert "is_truly_discontinued" in it

    def test_inactive_but_not_discontinued_sku_included(self) -> None:
        """is_active=0 (网店下架) 但 v3 算法未标停用 → 应该出现在列表里
        (5206753044598 这类 '线下还在卖+ERP 等级 1+不上网店' 的 case)."""
        from app.services.analytics import list_sku_summary

        self._add_sku("OFFLINE", model="OFFLINE", is_active=0, is_truly_discontinued=False)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        barcodes = [it["barcode"] for it in items]
        assert "OFFLINE" in barcodes

    def test_truly_discontinued_excluded_regardless_of_is_active(self) -> None:
        """is_truly_discontinued=true 永远不出现, 不管 is_active 是 1 还是 0."""
        from app.services.analytics import list_sku_summary

        self._add_sku("DEAD_A", model="DEAD_A", is_active=1, is_truly_discontinued=True)
        self._add_sku("DEAD_B", model="DEAD_B", is_active=0, is_truly_discontinued=True)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        barcodes = [it["barcode"] for it in items]
        assert "DEAD_A" not in barcodes
        assert "DEAD_B" not in barcodes

    def test_snapshot_join_rule_b_barcode_13_digit(self) -> None:
        from app.services.analytics import list_sku_summary

        self._add_sku("8435286885768", model="8435286885768")
        self._add_snapshot("2026-05-19", "88576", 42)

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "8435286885768")
        assert it["qty_total"] == 42


if __name__ == "__main__":
    unittest.main()
