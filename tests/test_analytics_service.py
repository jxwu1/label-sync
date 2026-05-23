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

        out = _compute_urgency_score(0.9, 2.0, 30, margin_pctile=0.5, is_new_item=True)
        assert out == {
            "total": None, "velocity": None, "cover": None,
            "recency": None, "margin": None, "demand_validity": None,
        }

    def test_sold_out_top_seller_long_no_purchase_maxes_out(self) -> None:
        """P2 公式 E: v*30 + c*30 + r*10 + m*30 = 100 (需要 dv=1.0)."""
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=1.0, weeks_of_cover=0.0, last_purchase_days=200,
            margin_pctile=1.0, n_active_weeks=4,
        )
        assert out["velocity"] == 30.0
        assert out["cover"] == 30.0
        assert out["recency"] == 10.0
        assert out["margin"] == 30.0
        assert out["total"] == 100.0
        assert out["demand_validity"] == 1.0

    def test_just_restocked_low_recency(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=0.5, weeks_of_cover=10.0, last_purchase_days=0, n_active_weeks=4,
        )
        assert out["velocity"] == 15.0  # 0.5 * 30
        assert out["cover"] == 0.0
        assert out["recency"] == 0.0
        assert out["margin"] == 0.0
        assert out["total"] == 15.0

    def test_no_history_zero_score(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=0.0, weeks_of_cover=None, last_purchase_days=None, n_active_weeks=0,
        )
        assert out == {
            "total": 0.0, "velocity": 0.0, "cover": 0.0,
            "recency": 0.0, "margin": 0.0, "demand_validity": 0.0,
        }

    def test_negative_weeks_of_cover_caps_at_max_not_overflow(self) -> None:
        """ERP 超卖待到货 → qty_total<0 → weeks_of_cover<0 → cover 项应 cap 30, 总分 ≤100."""
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=0.5, weeks_of_cover=-62.1, last_purchase_days=0, n_active_weeks=4,
        )
        assert out["cover"] == 30.0
        assert out["total"] <= 100.0
        assert out["total"] == 15.0 + 30.0 + 0.0 + 0.0

    def test_cover_clamped_at_zero_when_overstocked(self) -> None:
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=0.8, weeks_of_cover=50.0, last_purchase_days=10, n_active_weeks=4,
        )
        assert out["cover"] == 0.0

    def test_margin_pctile_contributes_30_max(self) -> None:
        """P2: 高 margin_pctile 在低 velocity 情况下仍可显著推升分数."""
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=0.0, weeks_of_cover=None, last_purchase_days=None,
            margin_pctile=1.0, n_active_weeks=4,
        )
        assert out["margin"] == 30.0
        assert out["total"] == 30.0

    def test_margin_none_treated_as_zero(self) -> None:
        """缺 margin (没有 last_purchase_unit_price) → margin 项=0, 不扣分."""
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=0.8, weeks_of_cover=2.0, last_purchase_days=100,
            margin_pctile=None, n_active_weeks=4,
        )
        # v 24 + c (1-2/8)*30=22.5 + r (100/180)*10≈5.56 + m 0
        assert out["margin"] == 0.0
        assert out["total"] == round(24.0 + 22.5 + 100/180*10, 1)

    def test_demand_validity_long_tail_suppresses_cover_and_recency(self) -> None:
        """长尾死货 (n_active_weeks=1, dv=0.25) → cover/recency 砍到 1/4.
        5206753040071 case 回归: 3 年只卖 7 次, 不该靠 cover 满分霸榜."""
        from app.services.analytics import _compute_urgency_score

        out = _compute_urgency_score(
            velocity_pctile=0.3, weeks_of_cover=0.0, last_purchase_days=180,
            margin_pctile=0.2, n_active_weeks=1,
        )
        # dv = 1/4 = 0.25; cover 30*0.25=7.5, recency 10*0.25=2.5
        assert out["demand_validity"] == 0.25
        assert out["cover"] == 7.5
        assert out["recency"] == 2.5
        # velocity 9.0 + margin 6.0 不受 dv 影响
        assert out["velocity"] == 9.0
        assert out["margin"] == 6.0

    def test_demand_validity_threshold_at_4_weeks_full(self) -> None:
        """n_active_weeks >= 4 → dv=1.0 满分卫星分."""
        from app.services.analytics import _compute_urgency_score

        a = _compute_urgency_score(
            velocity_pctile=0.5, weeks_of_cover=0.0, last_purchase_days=180,
            margin_pctile=0.5, n_active_weeks=4,
        )
        b = _compute_urgency_score(
            velocity_pctile=0.5, weeks_of_cover=0.0, last_purchase_days=180,
            margin_pctile=0.5, n_active_weeks=20,
        )
        # >=4 周后 dv=1.0 封顶
        assert a["demand_validity"] == 1.0
        assert b["demand_validity"] == 1.0
        assert a["total"] == b["total"]


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

    def test_supplier_id_prefers_stockpile_over_last_purchase(self) -> None:
        """stockpile.supplier_id 优先 (来自 ERP 产品总档), 即使最近 purchase 是别家."""
        from app.services.analytics import list_sku_summary

        self._add_sku("SKU_M", model="SKU_M", supplier_id="GR0099")
        self._add_event(
            barcode="SKU_M", event_type="purchase",
            event_at="2026-03-01", qty=10, supplier_id="ES0001", document_no="P1",
        )

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "SKU_M")
        assert it["supplier_id"] == "GR0099"

    def test_supplier_id_falls_back_to_last_purchase_when_stockpile_null(self) -> None:
        """stockpile.supplier_id 没填 → fallback 到最近 purchase event 的 supplier_id."""
        from app.services.analytics import list_sku_summary

        self._add_sku("SKU_N", model="SKU_N")  # supplier_id 默认 None
        self._add_event(
            barcode="SKU_N", event_type="purchase",
            event_at="2026-03-01", qty=10, supplier_id="CN0036", document_no="P2",
        )

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "SKU_N")
        assert it["supplier_id"] == "CN0036"

    def test_snapshot_join_rule_b_barcode_13_digit(self) -> None:
        from app.services.analytics import list_sku_summary

        self._add_sku("8435286885768", model="8435286885768")
        self._add_snapshot("2026-05-19", "88576", 42)

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "8435286885768")
        assert it["qty_total"] == 42

    def test_weekly_revenue_present_and_uses_net_price(self) -> None:
        """P1: weekly_revenue = sum(qty * net_unit) / n_active_weeks (€/周)."""
        from app.services.analytics import list_sku_summary

        self._add_sku("REV1", model="REV1")
        # 同一 ISO 周, 2 笔: 10件×2.5×(1-0%) + 4件×3×(1-50%) = 25 + 6 = 31, n_active_weeks=1
        self._add_event(barcode="REV1", event_at="2026-05-04", qty=10,
                        unit_price=2.5, discount_pct=0.0, document_no="S1")
        self._add_event(barcode="REV1", event_at="2026-05-05", qty=4,
                        unit_price=3.0, discount_pct=50.0, document_no="S2")

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "REV1")
        assert it["weekly_revenue"] == 31.0
        assert it["weekly_velocity"] == 14.0

    def test_weekly_revenue_zero_when_no_sales(self) -> None:
        from app.services.analytics import list_sku_summary

        self._add_sku("REV2", model="REV2")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "REV2")
        assert it["weekly_revenue"] == 0.0
        assert it["weekly_velocity"] == 0.0

    def test_margin_pct_computed_from_sale_net_and_last_purchase(self) -> None:
        """margin_pct = (sale_net_avg - last_purchase_unit_price) / sale_net_avg * 100."""
        from app.services.analytics import list_sku_summary

        self._add_sku("M1", model="M1", last_purchase_unit_price=2.0)
        # 销售净加权均价 = (10*5.0 + 5*5.0) / 15 = 5.0
        # margin = (5.0 - 2.0) / 5.0 * 100 = 60.0
        self._add_event(barcode="M1", event_at="2026-05-04", qty=10,
                        unit_price=5.0, discount_pct=0.0, document_no="S1")
        self._add_event(barcode="M1", event_at="2026-05-11", qty=5,
                        unit_price=5.0, discount_pct=0.0, document_no="S2")

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "M1")
        assert it["last_purchase_unit_price"] == 2.0
        assert it["sale_net_avg"] == 5.0
        assert it["margin_pct"] == 60.0

    def test_margin_pct_none_when_no_purchase_price(self) -> None:
        from app.services.analytics import list_sku_summary

        self._add_sku("M2", model="M2")
        self._add_event(barcode="M2", event_at="2026-05-04", qty=10,
                        unit_price=5.0, document_no="S1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "M2")
        assert it["margin_pct"] is None
        assert it["margin_source"] is None
        if it["urgency_breakdown"]:
            assert it["urgency_breakdown"].get("margin_missing") is True

    def test_margin_falls_back_to_master_stock_price_eur(self) -> None:
        """缺 last_purchase 但 master_stock_price_eur 有值 → margin 用 master 兜底, source='master'."""
        from app.services.analytics import list_sku_summary

        self._add_sku("MFB", model="MFB", supplier_id="GR0001",
                      last_purchase_unit_price=None, master_stock_price_eur=2.0)
        self._add_event(barcode="MFB", event_at="2026-05-04", qty=10,
                        unit_price=5.0, document_no="S1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "MFB")
        # margin = (5.0 - 2.0) / 5.0 * 100 = 60
        assert it["margin_pct"] == 60.0
        assert it["margin_source"] == "master"

    def test_margin_prefers_last_purchase_over_master(self) -> None:
        """两路都有 → last_purchase 优先 (更准, source='purchase')."""
        from app.services.analytics import list_sku_summary

        self._add_sku("MPR", model="MPR", supplier_id="GR0001",
                      last_purchase_unit_price=2.5, master_stock_price_eur=10.0)
        self._add_event(barcode="MPR", event_at="2026-05-04", qty=10,
                        unit_price=5.0, document_no="S1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "MPR")
        # margin 用 last_purchase 2.5: (5-2.5)/5*100 = 50
        assert it["margin_pct"] == 50.0
        assert it["margin_source"] == "purchase"

    def test_high_margin_beats_high_revenue_when_other_factors_equal(self) -> None:
        """P2 痛点核心: 销额前列但低毛利的"伪好卖"被高毛利货压下去."""
        from app.services.analytics import list_sku_summary

        # 同 origin (FOREIGN GR), 同 cover (无 snapshot 都是 None),
        # 同 recency (无 purchase event 都是 None),
        # 只差 margin: HIGH_MARGIN margin=80%, LOW_MARGIN margin=10%
        # 但 LOW_MARGIN revenue 大 (件数*单价更大)
        self._add_sku("LOW_MARGIN", model="LOW_MARGIN",
                      supplier_id="GR0001", last_purchase_unit_price=4.5)
        self._add_sku("HIGH_MARGIN", model="HIGH_MARGIN",
                      supplier_id="GR0001", last_purchase_unit_price=1.0)
        # LOW_MARGIN: 100件×5€ = 500€/周, margin=(5-4.5)/5=10%
        for i, dt in enumerate(["2026-04-13", "2026-04-20", "2026-04-27", "2026-05-04", "2026-05-11"]):
            self._add_event(barcode="LOW_MARGIN", event_at=dt, qty=100,
                            unit_price=5.0, document_no=f"SL{i}")
        # HIGH_MARGIN: 10件×5€ = 50€/周, margin=(5-1)/5=80%
        for i, dt in enumerate(["2026-04-13", "2026-04-20", "2026-04-27", "2026-05-04", "2026-05-11"]):
            self._add_event(barcode="HIGH_MARGIN", event_at=dt, qty=10,
                            unit_price=5.0, document_no=f"SH{i}")

        items = list_sku_summary(as_of=date(2026, 5, 21))
        low = next(x for x in items if x["barcode"] == "LOW_MARGIN")
        high = next(x for x in items if x["barcode"] == "HIGH_MARGIN")
        # revenue 上 LOW 占优, margin 上 HIGH 占优
        assert low["weekly_revenue"] > high["weekly_revenue"]
        assert high["margin_pct"] > low["margin_pct"]
        # margin 权重 30 + velocity 权重 30, 双高 margin pctile=1 + 低 velocity pctile=0 (单 pair)
        # 实际 origin 子集只有 2 个 → bisect_left 给 0/1
        # LOW: v_pctile=1 (revenue 大), m_pctile=0 (margin 小)
        # HIGH: v_pctile=0 (revenue 小), m_pctile=1 (margin 大)
        # 两者其他维度 (cover/recency) 相同 → 平局
        # 验证 margin 至少跟 velocity 同权: HIGH urgency >= LOW urgency
        assert high["urgency_score"] >= low["urgency_score"]
        assert high["urgency_breakdown"]["margin"] > low["urgency_breakdown"]["margin"]

    def test_urgency_pctile_ranks_by_revenue_not_qty(self) -> None:
        """高单价低销量 SKU 在 revenue 维度上能压过低单价高销量 SKU.
        50€×2件/周 = €100/周  vs  0.5€×100件/周 = €50/周 → 前者紧迫分应更高."""
        from app.services.analytics import list_sku_summary

        self._add_sku("EXPENSIVE", model="EXPENSIVE", supplier_id="GR0001")
        self._add_sku("CHEAP", model="CHEAP", supplier_id="GR0001")
        for i, dt in enumerate(["2026-04-13", "2026-04-20", "2026-04-27", "2026-05-04", "2026-05-11"]):
            self._add_event(barcode="EXPENSIVE", event_at=dt, qty=2,
                            unit_price=50.0, document_no=f"SE{i}")
        for i, dt in enumerate(["2026-04-13", "2026-04-20", "2026-04-27", "2026-05-04", "2026-05-11"]):
            self._add_event(barcode="CHEAP", event_at=dt, qty=100,
                            unit_price=0.5, document_no=f"SC{i}")

        items = list_sku_summary(as_of=date(2026, 5, 21))
        expensive = next(x for x in items if x["barcode"] == "EXPENSIVE")
        cheap = next(x for x in items if x["barcode"] == "CHEAP")
        assert cheap["weekly_velocity"] > expensive["weekly_velocity"]
        assert expensive["weekly_revenue"] > cheap["weekly_revenue"]
        assert expensive["urgency_breakdown"]["velocity_pctile"] > cheap["urgency_breakdown"]["velocity_pctile"]


class RetailPriceAndInventoryValueTests(_Base):
    """零售价派生 + 库存可销售金额 / 库存成本 测试 (2026-05-23 drawer 财务快照用)."""

    def _add_sku(self, barcode: str, **fields) -> None:
        from app.models import Stockpile
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

    def _add_snapshot(self, snapshot_date: str, model: str, qty: int) -> None:
        from app.models import StockpileInventorySnapshot
        with stockpile_db._session() as s:
            s.execute(insert(StockpileInventorySnapshot).values(
                snapshot_date=snapshot_date, product_model=model, qty_total=qty,
            ))
            s.commit()

    def test_retail_price_uses_x2_estimate_when_no_retail_history(self) -> None:
        """无零售销售 → retail_price = sale_price × 2, source='estimate'."""
        from app.services.analytics import list_sku_summary

        self._add_sku("RP1", supplier_id="GR0001", sale_price=0.50,
                      last_purchase_unit_price=0.20)
        # 仅批发销售
        self._add_event(barcode="RP1", event_at="2026-05-01", qty=10,
                        unit_price=0.50, document_no="W1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "RP1")
        assert it["retail_price_estimate"] == 1.0
        assert it["retail_price_observed"] is None
        assert it["retail_price_eur"] == 1.0
        assert it["retail_price_source"] == "estimate"

    def test_retail_price_uses_observed_when_3_plus_retail_events(self) -> None:
        """26 周内 ≥3 笔零售 → 用 retail_revenue/retail_qty 实际均价."""
        from app.services.analytics import list_sku_summary

        self._add_sku("RP2", supplier_id="GR0001", sale_price=0.50,
                      last_purchase_unit_price=0.20)
        # 5 笔零售 (MB 前缀) 均价 €0.95
        for i, dt in enumerate(["2026-04-01","2026-04-10","2026-04-20","2026-05-01","2026-05-10"]):
            self._add_event(barcode="RP2", event_at=dt, qty=2,
                            unit_price=0.95, document_no=f"MB{i}")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "RP2")
        assert it["retail_price_observed"] == 0.95
        assert it["retail_price_estimate"] == 1.0
        assert it["retail_price_eur"] == 0.95  # observed 覆盖 estimate
        assert it["retail_price_source"] == "observed"

    def test_retail_price_single_outlier_falls_back_to_estimate(self) -> None:
        """5206753040071 case 回归: 1 笔零售 €8.4677 不够门槛, 不污染零售价.
        retail_price 应继续用 ×2 估算, observed=None."""
        from app.services.analytics import list_sku_summary

        self._add_sku("RP3", supplier_id="GR0001", sale_price=0.50,
                      last_purchase_unit_price=0.20)
        self._add_event(barcode="RP3", event_at="2026-05-01", qty=1,
                        unit_price=8.4677, document_no="0")  # 单笔零售异常
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "RP3")
        assert it["retail_price_observed"] is None
        assert it["retail_price_eur"] == 1.0  # 仍走 ×2
        assert it["retail_price_source"] == "estimate"

    def test_inventory_sale_value_split_by_history_share(self) -> None:
        """库存可销售金额: 历史 retail_share 加权 × 各自价格.
        20 库存 + 历史 30% 零售 + 批发 0.50 + 零售 1.00 → 6×1.0 + 14×0.5 = 13.0."""
        from app.services.analytics import list_sku_summary

        self._add_sku("INV1", supplier_id="GR0001", sale_price=0.50,
                      last_purchase_unit_price=0.20)
        # 7 件批发 (event 一次 7 件), 3 件零售 (3 笔 × 1 件 = 满足 ≥3 门槛)
        self._add_event(barcode="INV1", event_at="2026-05-01", qty=7,
                        unit_price=0.50, document_no="W1")
        for i, dt in enumerate(["2026-05-02","2026-05-03","2026-05-04"]):
            self._add_event(barcode="INV1", event_at=dt, qty=1,
                            unit_price=1.0, document_no=f"MB{i}")
        self._add_snapshot("2026-05-19", "INV1", 20)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "INV1")
        # retail_share = 3/(7+3) = 0.3
        assert it["retail_share_26w"] == 0.3
        # 20 × 0.3 × 1.0 + 20 × 0.7 × 0.5 = 6 + 7 = 13.0
        assert it["inventory_sale_value_eur"] == 13.0

    def test_inventory_cost_value_uses_master_or_purchase(self) -> None:
        """库存成本 = qty_total × cost (优先 last_purchase, fallback master)."""
        from app.services.analytics import list_sku_summary

        self._add_sku("INV2", supplier_id="GR0001", sale_price=1.0,
                      last_purchase_unit_price=0.40)
        self._add_snapshot("2026-05-19", "INV2", 50)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "INV2")
        assert it["inventory_cost_value_eur"] == 20.0  # 50 × 0.40

    def test_inventory_values_none_when_no_stock(self) -> None:
        """qty_total 缺失 (无 snapshot) → inventory_* 全 None."""
        from app.services.analytics import list_sku_summary

        self._add_sku("INV3", supplier_id="GR0001", sale_price=1.0,
                      last_purchase_unit_price=0.40)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "INV3")
        assert it["inventory_sale_value_eur"] is None
        assert it["inventory_cost_value_eur"] is None


class LifetimeProfitTests(_Base):
    """累计盈亏 (drawer 回本/压货状态) 测试 (2026-05-23)."""

    def _add_sku(self, barcode: str, **fields) -> None:
        from app.models import Stockpile
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

    def test_realized_profit_positive_when_revenue_beats_sold_cost(self) -> None:
        """卖了 10 件 €100 + cost €5/件 → 实现利润 €100 - 10×5 = €50."""
        from app.services.analytics import list_sku_summary

        self._add_sku("LP1", supplier_id="GR0001", sale_price=10.0,
                      last_purchase_unit_price=5.0)
        # 10 件 × €10 = €100 收入
        self._add_event(barcode="LP1", event_at="2025-01-01", qty=10,
                        unit_price=10.0, document_no="W1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "LP1")
        assert it["lifetime_sale_qty"] == 10
        assert it["lifetime_sale_revenue_eur"] == 100.0
        assert it["realized_profit_eur"] == 50.0  # 100 - 10×5
        assert it["first_event_at"] == "2025-01-01"
        assert it["is_history_truncated"] is False

    def test_realized_profit_negative_when_sold_cheap(self) -> None:
        """卖了 10 件 €30 (亏本甩卖) + cost €5/件 → 实现利润 -€20."""
        from app.services.analytics import list_sku_summary

        self._add_sku("LP2", supplier_id="GR0001", sale_price=10.0,
                      last_purchase_unit_price=5.0)
        self._add_event(barcode="LP2", event_at="2025-01-01", qty=10,
                        unit_price=3.0, document_no="W1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "LP2")
        assert it["lifetime_sale_revenue_eur"] == 30.0
        assert it["realized_profit_eur"] == -20.0  # 30 - 10×5

    def test_lifetime_includes_retail_and_wholesale(self) -> None:
        """累计销量+销售额 同时包括批发和零售事件."""
        from app.services.analytics import list_sku_summary

        self._add_sku("LP3", supplier_id="GR0001", sale_price=2.0,
                      last_purchase_unit_price=1.0)
        # 5 件批发 € 2 + 3 件零售 €4 = 8 件 + €22
        self._add_event(barcode="LP3", event_at="2025-01-01", qty=5,
                        unit_price=2.0, document_no="W1")
        self._add_event(barcode="LP3", event_at="2025-02-01", qty=3,
                        unit_price=4.0, document_no="MB1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "LP3")
        assert it["lifetime_sale_qty"] == 8  # 5+3
        assert it["lifetime_sale_revenue_eur"] == 22.0  # 5×2 + 3×4
        assert it["realized_profit_eur"] == 14.0  # 22 - 8×1

    def test_history_truncated_flag_when_first_event_old(self) -> None:
        """first_event_at <= 2021-06-01 → is_history_truncated=True (ETL 窗口边界)."""
        from app.services.analytics import list_sku_summary

        self._add_sku("LP4", supplier_id="GR0001", sale_price=2.0,
                      last_purchase_unit_price=1.0)
        self._add_event(barcode="LP4", event_at="2021-01-01", qty=5,
                        unit_price=2.0, document_no="W1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "LP4")
        assert it["first_event_at"] == "2021-01-01"
        assert it["is_history_truncated"] is True

    def test_lifetime_invested_uses_purchase_qty_times_cost(self) -> None:
        """累计投入 = 累计 purchase qty × cost (EUR 口径).
        进 30 件 + 进 20 件 = 50 件 × €5 = €250 投入."""
        from app.services.analytics import list_sku_summary

        self._add_sku("LP6", supplier_id="GR0001", sale_price=10.0,
                      last_purchase_unit_price=5.0)
        self._add_event(barcode="LP6", event_type="purchase",
                        event_at="2024-01-01", qty=30, supplier_id="GR0001",
                        document_no="P1")
        self._add_event(barcode="LP6", event_type="purchase",
                        event_at="2024-06-01", qty=20, supplier_id="GR0001",
                        document_no="P2")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "LP6")
        assert it["lifetime_purchase_qty"] == 50
        assert it["lifetime_invested_eur"] == 250.0

    def test_lifetime_invested_none_when_no_purchase_events(self) -> None:
        """无 purchase 事件 → lifetime_invested=None, lifetime_purchase_qty=0."""
        from app.services.analytics import list_sku_summary

        self._add_sku("LP7", supplier_id="GR0001", sale_price=2.0,
                      last_purchase_unit_price=1.0)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "LP7")
        assert it["lifetime_purchase_qty"] == 0
        assert it["lifetime_invested_eur"] is None

    def test_no_cost_yields_none_realized_profit(self) -> None:
        """无 cost (purchase/master 都缺) → realized_profit=None, 不显示."""
        from app.services.analytics import list_sku_summary

        self._add_sku("LP5", supplier_id="GR0001", sale_price=2.0)  # 无 last_purchase, 无 master
        self._add_event(barcode="LP5", event_at="2025-01-01", qty=5,
                        unit_price=2.0, document_no="W1")
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "LP5")
        assert it["lifetime_sale_qty"] == 5
        assert it["realized_profit_eur"] is None


if __name__ == "__main__":
    unittest.main()
