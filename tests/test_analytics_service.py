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
        """origin-aware margin (2026-05-23 重写): cost 走 last_pp (FOREIGN), sale 走 主档 sale_price.
        进 6 / 售 主档 10 → margin (10-6)/10 = 40%."""
        from app.models import Stockpile
        from app.services.analytics import compute_purchase_metrics

        # 给 B1 加 stockpile master 数据 (新口径需要)
        with stockpile_db._session() as s:
            s.execute(insert(Stockpile).values(
                product_barcode="B1", product_model="B1",
                stockpile_location="", is_active=1,
                supplier_id="GR0001",       # FOREIGN
                sale_price=10.0,            # 主档售价
                last_purchase_unit_price=6.0,  # 主档进价
            ))
            s.commit()
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
        # 5 笔零售 (customer_id=0) 均价 €0.95
        for i, dt in enumerate(["2026-04-01","2026-04-10","2026-04-20","2026-05-01","2026-05-10"]):
            self._add_event(barcode="RP2", event_at=dt, qty=2,
                            unit_price=0.95, customer_id="0", document_no=f"MB700{i}")
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
                            unit_price=1.0, customer_id="0", document_no=f"MB700{i}")
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

    def _add_snapshot(self, snapshot_date: str, model: str, qty: int) -> None:
        from app.models import StockpileInventorySnapshot
        with stockpile_db._session() as s:
            s.execute(insert(StockpileInventorySnapshot).values(
                snapshot_date=snapshot_date, product_model=model, qty_total=qty,
            ))
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
                        unit_price=4.0, customer_id="0", document_no="MB7001")
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

    def test_cn_origin_ignores_last_purchase_uses_master_only(self) -> None:
        """CN 货 last_purchase_unit_price 是 RMB 原始价, 不能当 EUR.
        analytics 应优先 master_stock_price_eur (落地 EUR), 跳过 last_pp.
        修复 2026-05-23 发现的 CN 全部账面巨亏 bug."""
        from app.services.analytics import list_sku_summary

        # CN 货: last_pp=1.85 (RMB), master=0.30 (EUR 落地价)
        self._add_sku("CN1", supplier_id="CN0001", sale_price=0.5,
                      last_purchase_unit_price=1.85,
                      master_stock_price_eur=0.30)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "CN1")
        # cost 应取 master (0.30), 不是 last_pp (1.85)
        assert it["margin_source"] == "master"
        # margin = (0.5 - 0.30) / 0.5 = 40%, 不是 -270%
        assert it["margin_pct"] == 40.0

    def test_cn_origin_no_master_returns_none_margin(self) -> None:
        """CN 货 master 缺失 (新货未跑 product_master) → margin=None.
        不会再用 last_pp RMB 当 EUR 算出假亏损."""
        from app.services.analytics import list_sku_summary

        self._add_sku("CN2", supplier_id="CN0001", sale_price=0.5,
                      last_purchase_unit_price=1.85,
                      master_stock_price_eur=None)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "CN2")
        assert it["margin_pct"] is None
        assert it["margin_source"] is None

    def test_foreign_origin_still_prefers_last_purchase(self) -> None:
        """FOREIGN 货逻辑保持: purchase event 就是 EUR, 优先 last_pp."""
        from app.services.analytics import list_sku_summary

        self._add_sku("FR1", supplier_id="GR0001", sale_price=10.0,
                      last_purchase_unit_price=4.0,
                      master_stock_price_eur=5.0)
        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "FR1")
        # FOREIGN 优先 last_pp 4.0
        assert it["margin_source"] == "purchase"
        assert it["margin_pct"] == 60.0  # (10-4)/10

    def test_realized_profit_switches_to_cashflow_when_qty_total_zero(self) -> None:
        """库存清零 → realized_profit 用净现金流 (销售 - 总投入), 不用 FIFO.
        5828079293643 case 回归: purchase=12000, sale=8419, qty=0
        → FIFO 给 5107 (假设 3581 件还在某处), 净现金流给 3852 (更真实)."""
        from app.services.analytics import list_sku_summary

        self._add_sku("CF1", supplier_id="GR0001", sale_price=1.0,
                      last_purchase_unit_price=0.35)
        self._add_event(barcode="CF1", event_type="purchase",
                        event_at="2024-01-01", qty=12000,
                        unit_price=0.35, supplier_id="GR0001", document_no="P1")
        self._add_event(barcode="CF1", event_at="2025-01-01", qty=8419,
                        unit_price=0.957, document_no="W1")
        self._add_snapshot("2026-05-19", "CF1", 0)

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "CF1")
        assert it["qty_total"] == 0
        # 净现金流 = revenue - invested = 8419*0.957 - 12000*0.35 = 3856.98
        assert it["realized_profit_eur"] == 3856.98
        # 不应该是 FIFO 的 (8056.98 - 8419*0.35) = 5110.33
        assert it["realized_profit_eur"] != 5110.33

    def test_realized_profit_uses_fifo_when_inventory_positive(self) -> None:
        """qty_total > 0 → FIFO. 库存按 cost 算回资产, realized = sale - sold_qty*cost."""
        from app.services.analytics import list_sku_summary

        self._add_sku("FIFO1", supplier_id="GR0001", sale_price=10.0,
                      last_purchase_unit_price=5.0)
        self._add_event(barcode="FIFO1", event_type="purchase",
                        event_at="2024-01-01", qty=100, unit_price=5.0,
                        supplier_id="GR0001", document_no="P1")
        self._add_event(barcode="FIFO1", event_at="2025-01-01", qty=30,
                        unit_price=10.0, document_no="W1")
        self._add_snapshot("2026-05-19", "FIFO1", 70)

        items = list_sku_summary(as_of=date(2026, 5, 21))
        it = next(x for x in items if x["barcode"] == "FIFO1")
        # FIFO: revenue - sold_qty × cost = 300 - 30*5 = 150
        assert it["realized_profit_eur"] == 150.0
        # 不该是现金流的 (300 - 500) = -200
        assert it["realized_profit_eur"] != -200.0

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


class WeeklyTimelineOriginAwareTests(_Base):
    """compute_weekly_timeline: CN 货按 EUR 落地成本, FOREIGN 沿用 EUR 原价."""

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

    def test_cn_purchase_price_converted_to_eur_landed_cost(self) -> None:
        """CN 货 purchase event unit_price=1.85 RMB, 配 (240 件/箱, 0.115m³)
        → 应转 (1000×0.115/240 + 1.85)/7.8 = €0.2986 落地价."""
        import json
        from app.services.analytics import compute_weekly_timeline

        self._add_sku("WT1", supplier_id="CN0531",
                      extra=json.dumps({"unit_quantity": "240", "pack_volume": "0.115"}))
        self._add_event(barcode="WT1", event_type="purchase",
                        event_at="2026-05-10", qty=240, unit_price=1.85,
                        supplier_id="CN0531", document_no="P1")
        tl = compute_weekly_timeline("WT1", weeks=4, as_of=date(2026, 5, 21))
        priced = [w for w in tl if w["purchase_unit_price"] is not None]
        assert len(priced) == 1
        wk = priced[0]
        assert wk["purchase_unit_price"] == 0.2986  # EUR 落地价
        assert wk["raw_unit_price_local"] == 1.85    # RMB 原始
        assert wk["currency_local"] == "RMB"

    def test_foreign_purchase_price_passthrough_eur(self) -> None:
        """FOREIGN 货 purchase event unit_price=3.5 EUR 直接透传, 不套公式."""
        from app.services.analytics import compute_weekly_timeline

        self._add_sku("WT2", supplier_id="GR0001")
        self._add_event(barcode="WT2", event_type="purchase",
                        event_at="2026-05-10", qty=10, unit_price=3.5,
                        supplier_id="GR0001", document_no="P2")
        tl = compute_weekly_timeline("WT2", weeks=4, as_of=date(2026, 5, 21))
        priced = [w for w in tl if w["purchase_unit_price"] is not None]
        assert len(priced) == 1
        wk = priced[0]
        assert wk["purchase_unit_price"] == 3.5
        assert wk["currency_local"] == "EUR"

    def test_cn_no_pack_volume_falls_back_to_exchange_only(self) -> None:
        """CN 货缺 pack_volume → 海运分摊=0, 仅汇率换算 (与 ERP 体积=0 行为一致)."""
        from app.services.analytics import compute_weekly_timeline

        self._add_sku("WT3", supplier_id="CN0001")  # 无 extra → 无 unit_quantity/pack_volume
        self._add_event(barcode="WT3", event_type="purchase",
                        event_at="2026-05-10", qty=10, unit_price=7.8,
                        supplier_id="CN0001", document_no="P3")
        tl = compute_weekly_timeline("WT3", weeks=4, as_of=date(2026, 5, 21))
        priced = [w for w in tl if w["purchase_unit_price"] is not None]
        assert len(priced) == 1
        # 7.8 RMB / 7.8 = 1.0 EUR, 无海运
        assert priced[0]["purchase_unit_price"] == 1.0
        assert priced[0]["raw_unit_price_local"] == 7.8


class SkuExtrasTests(_Base):
    """compute_sku_extras: 退货率 / 价格统计 / 客户 TOP / 首尾日期 (2026-05-23)."""

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

    def test_return_rate_qty_based(self) -> None:
        """卖 10 件 + 退 2 件 → return_rate = 2/(10+2) = 16.67%."""
        from app.services.analytics import compute_sku_extras

        self._add_sku("EX1")
        self._add_event(barcode="EX1", event_at="2026-04-01", qty=10,
                        unit_price=5.0, document_no="W1")
        self._add_event(barcode="EX1", event_at="2026-04-15", qty=-2,
                        unit_price=5.0, document_no="W2")
        e = compute_sku_extras("EX1", as_of=date(2026, 5, 1))
        assert e["total_sale_qty_gross"] == 10
        assert e["return_qty"] == 2
        assert e["return_rate_pct"] == 16.67

    def test_price_stats_excludes_retail_and_returns(self) -> None:
        """价格统计仅批发正销售: MB 零售 + 负 qty 退货均剔除."""
        from app.services.analytics import compute_sku_extras

        self._add_sku("EX2")
        # 3 笔批发: €5 / €6 / €7
        for i, p in enumerate([5.0, 6.0, 7.0]):
            self._add_event(barcode="EX2", event_at=f"2026-04-0{i+1}",
                            qty=10, unit_price=p, document_no=f"W{i}")
        # 1 笔零售 (customer_id=0) - 应被排除
        self._add_event(barcode="EX2", event_at="2026-04-10", qty=2,
                        unit_price=15.0, customer_id="0", document_no="MB7001")
        # 1 笔退货 - 应被排除
        self._add_event(barcode="EX2", event_at="2026-04-12", qty=-1,
                        unit_price=99.0, document_no="W9")
        e = compute_sku_extras("EX2", as_of=date(2026, 5, 1))
        assert e["price_stats"]["n"] == 3
        assert e["price_stats"]["mean"] == 6.0  # (5+6+7)/3
        assert e["price_stats"]["min"] == 5.0
        assert e["price_stats"]["max"] == 7.0

    def test_top_customers_split_cn_and_foreign(self) -> None:
        """TOP 客户拆 CN + 老外两栏, 按净 qty desc, 含退货抵销.
        名字含汉字一律 CN (覆盖 stored type)."""
        from app.services.analytics import compute_sku_extras

        self._add_sku("EX3")
        self._add_customer("C1", "chinese", "客户1")
        self._add_customer("C2", "foreign", "ANDREOU GR")
        # C1 买 20, 退 5 → 净 15. C2 买 10
        self._add_event(barcode="EX3", event_at="2026-04-01", qty=20,
                        customer_id="C1", document_no="W1")
        self._add_event(barcode="EX3", event_at="2026-04-15", qty=-5,
                        customer_id="C1", document_no="W2")
        self._add_event(barcode="EX3", event_at="2026-04-10", qty=10,
                        customer_id="C2", document_no="W3")
        e = compute_sku_extras("EX3", as_of=date(2026, 5, 1))
        assert len(e["top_customers_cn"]) == 1
        assert e["top_customers_cn"][0]["customer_id"] == "C1"
        assert e["top_customers_cn"][0]["qty"] == 15
        assert e["top_customers_cn"][0]["customer_type"] == "chinese"
        assert len(e["top_customers_foreign"]) == 1
        assert e["top_customers_foreign"][0]["customer_id"] == "C2"

    def test_top10_excludes_retail_customer_id_zero(self) -> None:
        """零售识别用 customer_id='0' (2026-05-23 改用客户口径, 弃 document_no 规则)."""
        from app.services.analytics import compute_sku_extras

        self._add_sku("EXR")
        self._add_customer("C100", "foreign", "REAL CUSTOMER")
        self._add_customer("0", "foreign", "零售")
        self._add_event(barcode="EXR", event_at="2026-04-01", qty=30,
                        customer_id="C100", document_no="W1")
        self._add_event(barcode="EXR", event_at="2026-04-10", qty=5,
                        customer_id="0", document_no="W2")
        e = compute_sku_extras("EXR", as_of=date(2026, 5, 1))
        assert len(e["top_customers_foreign"]) == 1
        assert e["top_customers_foreign"][0]["customer_id"] == "C100"
        assert e["top_customers_foreign"][0]["qty"] == 30
        assert e["retail_summary"]["qty"] == 5
        assert e["retail_summary"]["n_transactions"] == 1

    def test_top10_excludes_customer_name_contains_lingshou(self) -> None:
        """名字含"零售"的客户即使有 ID 也归零售, 不进 TOP10."""
        from app.services.analytics import compute_sku_extras

        self._add_sku("EXR2")
        self._add_customer("C200", "foreign", "REAL")
        self._add_customer("C999", "foreign", "零售客户")  # 名字含"零售"
        self._add_event(barcode="EXR2", event_at="2026-04-01", qty=50,
                        customer_id="C200", document_no="W1")
        self._add_event(barcode="EXR2", event_at="2026-04-10", qty=3,
                        customer_id="C999", document_no="W2")
        e = compute_sku_extras("EXR2", as_of=date(2026, 5, 1))
        assert len(e["top_customers_foreign"]) == 1
        assert e["top_customers_foreign"][0]["customer_id"] == "C200"
        assert e["retail_summary"]["qty"] == 3

    def test_top_customers_chinese_name_overrides_stored_type(self) -> None:
        """名字带中文 → 强制 CN, 即使 customers.customer_type='foreign' 也覆盖.
        用户决策: stored 类型有遗漏, 运行时按 name 重判."""
        from app.services.analytics import compute_sku_extras

        self._add_sku("EX3B")
        # 故意把"中国老板"标成 foreign (模拟 stored 误归类)
        self._add_customer("CB", "foreign", "中国老板希腊店面 ΟΕ")
        self._add_event(barcode="EX3B", event_at="2026-04-01", qty=50,
                        customer_id="CB", document_no="W1")
        e = compute_sku_extras("EX3B", as_of=date(2026, 5, 1))
        # 应该归 CN, 不依赖 stored 'foreign'
        assert len(e["top_customers_cn"]) == 1
        assert e["top_customers_cn"][0]["customer_id"] == "CB"
        assert e["top_customers_cn"][0]["customer_type"] == "chinese"
        assert len(e["top_customers_foreign"]) == 0

    def test_history_truncated_flag(self) -> None:
        """首笔事件 <= 2021-06-01 → is_history_truncated=True."""
        from app.services.analytics import compute_sku_extras

        self._add_sku("EX4")
        self._add_event(barcode="EX4", event_at="2021-01-01", qty=5,
                        unit_price=1.0, document_no="W1")
        e = compute_sku_extras("EX4", as_of=date(2026, 5, 1))
        assert e["first_event_at"] == "2021-01-01"
        assert e["is_history_truncated"] is True

    def test_no_events_returns_empty(self) -> None:
        from app.services.analytics import compute_sku_extras

        self._add_sku("EX5")
        e = compute_sku_extras("EX5", as_of=date(2026, 5, 1))
        assert e["return_qty"] == 0
        assert e["return_rate_pct"] is None
        assert e["price_stats"]["n"] == 0
        assert e["top_customers_cn"] == []
        assert e["top_customers_foreign"] == []
        assert e["first_event_at"] is None


class HoldingAndHeatmapTests(_Base):
    """持仓周期 + 月度热力图 (2026-05-23)."""

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

    def test_holding_days_fifo_pairing(self) -> None:
        """FIFO: 进 100 件 (2026-01-01), 卖 30 件 (2026-02-01) → 31 天持仓.
        队列剩 70 件最早是 2026-01-01."""
        from app.services.analytics import compute_avg_holding_days

        self._add_sku("HD1")
        self._add_event(barcode="HD1", event_type="purchase",
                        event_at="2026-01-01", qty=100, document_no="P1")
        self._add_event(barcode="HD1", event_at="2026-02-01", qty=30, document_no="W1")
        h = compute_avg_holding_days("HD1")
        assert h["avg_days"] == 31.0
        assert h["n_pairs"] == 30
        assert h["oldest_held_days"] is not None
        assert h["oldest_held_days"] > 0

    def test_holding_days_none_when_no_data(self) -> None:
        from app.services.analytics import compute_avg_holding_days

        self._add_sku("HD2")
        h = compute_avg_holding_days("HD2")
        assert h["avg_days"] is None
        assert h["n_pairs"] == 0

    def test_heatmap_year_month_grid(self) -> None:
        """4 年 × 12 月矩阵, 批发销量分桶, 零售不进."""
        from app.services.analytics import compute_monthly_heatmap

        self._add_sku("HM1")
        self._add_event(barcode="HM1", event_at="2026-03-15", qty=50,
                        unit_price=2.0, document_no="W1")
        self._add_event(barcode="HM1", event_at="2025-12-10", qty=30,
                        unit_price=2.0, document_no="W2")
        # 零售不进热力图 (customer_id=0)
        self._add_event(barcode="HM1", event_at="2026-03-20", qty=5,
                        unit_price=2.0, customer_id="0", document_no="MB7001")
        h = compute_monthly_heatmap("HM1", years=4, as_of=date(2026, 5, 21))
        assert len(h["years"]) == 4
        assert "2026" in h["years"]
        assert "2025" in h["years"]
        assert h["matrix"]["2026"][2] == 50   # March (index 2) 2026
        assert h["matrix"]["2025"][11] == 30  # December 2025
        assert h["matrix"]["2026"][3] == 0    # 没数据
        assert h["max_qty"] == 50


if __name__ == "__main__":
    unittest.main()
