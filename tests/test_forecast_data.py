"""forecast_data.weekly_demand_series 单测（plan §1.0.1 + §1.1）。

覆盖:
- 空数据 / window 边界
- 同 doc 同周净抵 (10 + -3 = 7)
- 同 doc 跨周净抵 (净量挂到 doc 内最早事件那一周)
- 仅退货在窗口内 (原单在窗口外) → 丢弃, 不落负
- 跨 doc 同周累加
- 空周补 0
- 无 document_no 的事件按单条处理 (fallback 不能让多条独立事件被错误合并)
"""

from __future__ import annotations

import shutil
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import insert

import stockpile_db
from models import InventoryEvent

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_forecast_data"


def _monday(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


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
        event_at: str,
        qty: int,
        document_no: str | None = None,
        event_type: str = "sale",
    ) -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type=event_type,
                    product_barcode=barcode,
                    qty=qty,
                    document_no=document_no,
                )
            )
            s.commit()


class WeeklyDemandSeriesTests(_Base):
    def test_no_sales_returns_all_zero_weeks(self) -> None:
        from forecast_data import weekly_demand_series

        s = weekly_demand_series("NOPE", end_date=date(2026, 5, 11), weeks=4)
        assert list(s.values()) == [0, 0, 0, 0]
        assert all(isinstance(k, date) for k in s.keys())

    def test_single_sale_lands_in_its_week(self) -> None:
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=10, document_no="D1")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert s[_monday(date(2026, 5, 6))] == 10
        assert sum(s.values()) == 10

    def test_returns_within_same_doc_same_week_net(self) -> None:
        """plan §1.0.1: 同 doc 同周原单 + 退货 → 净量."""
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=10, document_no="D1")
        self._add_event(event_at="2026-05-08", qty=-3, document_no="D1")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert s[_monday(date(2026, 5, 6))] == 7

    def test_returns_within_same_doc_cross_week_lands_on_earliest(self) -> None:
        """plan §1.0.1: 同 doc 跨周, 净量挂到原单 (最早事件) 那一周, 退货周不落负."""
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=10, document_no="D1")
        self._add_event(event_at="2026-05-13", qty=-3, document_no="D1")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 17), weeks=4)
        assert s[_monday(date(2026, 5, 6))] == 7
        assert s[_monday(date(2026, 5, 13))] == 0

    def test_orphan_return_in_window_is_dropped(self) -> None:
        """plan §1.0.1: 原单在窗口外, 仅退货负数 → 丢弃, 周需求 = 0."""
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-13", qty=-3, document_no="D_ORPHAN")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 31), weeks=4)
        assert sum(s.values()) == 0

    def test_multiple_docs_same_week_sum(self) -> None:
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=5, document_no="D1")
        self._add_event(event_at="2026-05-07", qty=2, document_no="D2")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert s[_monday(date(2026, 5, 6))] == 7

    def test_empty_weeks_filled_with_zero(self) -> None:
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=5, document_no="D1")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 25), weeks=4)
        assert len(s) == 4
        assert s[_monday(date(2026, 5, 6))] == 5
        assert s[_monday(date(2026, 5, 11))] == 0
        assert s[_monday(date(2026, 5, 18))] == 0
        assert s[_monday(date(2026, 5, 25))] == 0

    def test_null_document_no_each_event_is_own_unit(self) -> None:
        """无 document_no 的多条事件不能错误合并 (各自当独立 1 doc)."""
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=5, document_no=None)
        self._add_event(event_at="2026-05-07", qty=3, document_no=None)
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert s[_monday(date(2026, 5, 6))] == 8

    def test_null_document_no_negative_event_dropped(self) -> None:
        """无 doc_no 的负数事件没法 net (没原单可挂) → 单独丢弃."""
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=-3, document_no=None)
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert sum(s.values()) == 0

    def test_purchase_events_excluded(self) -> None:
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=100, event_type="purchase")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert sum(s.values()) == 0

    def test_other_barcodes_excluded(self) -> None:
        from forecast_data import weekly_demand_series

        self._add_event(barcode="B1", event_at="2026-05-06", qty=5, document_no="D1")
        self._add_event(barcode="B2", event_at="2026-05-06", qty=99, document_no="D2")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert sum(s.values()) == 5

    def test_doc_fully_cancelled_drops(self) -> None:
        """同 doc 完全冲销 (sum=0) → 周为 0."""
        from forecast_data import weekly_demand_series

        self._add_event(event_at="2026-05-06", qty=5, document_no="D1")
        self._add_event(event_at="2026-05-07", qty=-5, document_no="D1")
        s = weekly_demand_series("B1", end_date=date(2026, 5, 11), weeks=4)
        assert sum(s.values()) == 0


class WinsorizeTests(unittest.TestCase):
    """plan §1.3: 顶部 q 分位以上压到 q 分位本身."""

    def test_empty(self) -> None:
        from forecast_data import winsorize

        assert winsorize([]) == []

    def test_constant_series_unchanged(self) -> None:
        from forecast_data import winsorize

        assert winsorize([5, 5, 5, 5]) == [5.0, 5.0, 5.0, 5.0]

    def test_q_1_0_unchanged(self) -> None:
        from forecast_data import winsorize

        assert winsorize([1, 2, 3, 100], q=1.0) == [1.0, 2.0, 3.0, 100.0]

    def test_q_0_95_caps_top(self) -> None:
        """[1..100] q=0.95 → 顶部 6 个值压到 q95 分位 (~95.05)."""
        from forecast_data import winsorize

        out = winsorize(list(range(1, 101)), q=0.95)
        threshold = max(out)
        # 大于 threshold 的应该没有
        assert all(v <= threshold for v in out)
        # 至少有几个值被压低 (大于 95)
        n_capped = sum(1 for v in out if v == threshold)
        assert n_capped >= 5

    def test_q_0_5_caps_above_median(self) -> None:
        from forecast_data import winsorize

        out = winsorize([1, 2, 3, 4, 5], q=0.5)
        # median=3, > 3 的 (4, 5) 都应压到 3
        assert out == [1.0, 2.0, 3.0, 3.0, 3.0]

    def test_zeros_preserved(self) -> None:
        from forecast_data import winsorize

        out = winsorize([0, 0, 0, 100], q=0.95)
        assert out[0] == 0.0
        assert out[3] < 100.0  # 顶部被压

    def test_does_not_mutate_input(self) -> None:
        from forecast_data import winsorize

        src = [1, 2, 100]
        winsorize(src, q=0.5)
        assert src == [1, 2, 100]


class ComputeDocQtyStatsTests(unittest.TestCase):
    def test_empty_returns_none(self) -> None:
        from forecast_data import compute_doc_qty_stats

        assert compute_doc_qty_stats([]) is None

    def test_too_few_samples_returns_none(self) -> None:
        """< 4 个样本 → None (IQR 无意义)."""
        from forecast_data import compute_doc_qty_stats

        assert compute_doc_qty_stats([1]) is None
        assert compute_doc_qty_stats([1, 2]) is None
        assert compute_doc_qty_stats([1, 2, 3]) is None

    def test_four_samples_returns_dict(self) -> None:
        from forecast_data import compute_doc_qty_stats

        s = compute_doc_qty_stats([1, 2, 3, 4])
        assert s is not None
        assert set(s.keys()) == {"median", "q1", "q3", "iqr"}
        assert s["median"] == 2.5
        assert s["iqr"] == s["q3"] - s["q1"]

    def test_constant_iqr_zero(self) -> None:
        from forecast_data import compute_doc_qty_stats

        s = compute_doc_qty_stats([5, 5, 5, 5, 5])
        assert s is not None
        assert s["median"] == 5
        assert s["iqr"] == 0

    def test_wide_spread(self) -> None:
        from forecast_data import compute_doc_qty_stats

        s = compute_doc_qty_stats([1, 2, 3, 4, 100])
        assert s is not None
        assert s["iqr"] > 0


class _BaseDemandViewBase(_Base):
    """base_demand_view 集成测试基类: 提供 customers 表辅助."""

    def _add_customer(self, customer_id: str, customer_type: str = "foreign") -> None:
        from models import Customer

        with stockpile_db._session() as s:
            s.execute(
                insert(Customer).values(
                    customer_id=customer_id,
                    customer_name=f"C-{customer_id}",
                    customer_type=customer_type,
                )
            )
            s.commit()

    def _add_sale(
        self,
        *,
        barcode: str = "B1",
        event_at: str,
        qty: int,
        document_no: str | None,
        customer_id: str | None = None,
    ) -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type="sale",
                    product_barcode=barcode,
                    qty=qty,
                    document_no=document_no,
                    customer_id=customer_id,
                )
            )
            s.commit()


class BaseDemandViewTests(_BaseDemandViewBase):
    """plan §1.2: 按 SKU 类型分流过滤异常单 + 客户类型."""

    def test_wholesale_only_returns_none_series(self) -> None:
        from forecast_data import base_demand_view

        for i in range(5):
            self._add_sale(event_at="2026-05-01", qty=720, document_no=f"D{i}")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["sku_type"] == "wholesale_only"
        assert out["series"] is None
        assert out["exclusion_count"] == 0
        assert out["exclusion_qty"] == 0

    def test_unclassified_when_no_data(self) -> None:
        from forecast_data import base_demand_view

        out = base_demand_view("NOPE", end_date=date(2026, 5, 11), weeks=4)
        assert out["sku_type"] == "unclassified"
        assert out["series"] is None or sum(out["series"].values()) == 0

    def test_retail_dominant_no_bulk_no_exclusion(self) -> None:
        from forecast_data import base_demand_view

        for i in range(8):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"D{i}")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["sku_type"] == "retail_dominant"
        assert out["series"][_monday(date(2026, 5, 6))] == 80
        assert out["exclusion_count"] == 0

    def test_retail_dominant_excludes_bulk_doc(self) -> None:
        from forecast_data import base_demand_view

        for i in range(8):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"D{i}")
        self._add_sale(event_at="2026-05-07", qty=1000, document_no="BULK")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["sku_type"] == "retail_dominant"
        assert out["series"][_monday(date(2026, 5, 6))] == 80
        assert out["exclusion_count"] == 1
        assert out["exclusion_qty"] == 1000

    def test_retail_dominant_ignores_customer_type(self) -> None:
        from forecast_data import base_demand_view

        self._add_customer("C_UNK", "unknown")
        for i in range(8):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"D{i}", customer_id="C_UNK")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["sku_type"] == "retail_dominant"
        assert out["series"][_monday(date(2026, 5, 6))] == 80
        assert out["exclusion_count"] == 0

    def test_mixed_filters_unknown_customer(self) -> None:
        from forecast_data import base_demand_view

        self._add_customer("CF", "foreign")
        self._add_customer("CU", "unknown")
        for i in range(10):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"R{i}", customer_id="CF")
        for i in range(5):
            self._add_sale(event_at="2026-05-06", qty=200, document_no=f"W{i}", customer_id="CU")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["sku_type"] == "mixed"
        assert out["exclusion_count"] == 5
        assert out["series"][_monday(date(2026, 5, 6))] == 100

    def test_mixed_keeps_chinese_customer(self) -> None:
        """mixed: chinese 客户即使是中等大单, 只要不 bulk 也保留 (是零售路径之一)."""
        from forecast_data import base_demand_view

        self._add_customer("CF", "foreign")
        self._add_customer("CC", "chinese")
        # 7 foreign 零售 (qty=10) + 3 chinese 中单 (qty=100)
        # ratio 7/10=70% → mixed; doc qtys: [10]*7 + [100]*3
        # median=10, IQR~67.5, threshold~212.5 → 100 不算 bulk
        # chinese ∈ (foreign, chinese) → 客户过滤通过 → 全保留
        for i in range(7):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"R{i}", customer_id="CF")
        for i in range(3):
            self._add_sale(event_at="2026-05-06", qty=100, document_no=f"M{i}", customer_id="CC")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["sku_type"] == "mixed"
        assert out["exclusion_count"] == 0
        assert out["series"][_monday(date(2026, 5, 6))] == 7 * 10 + 3 * 100

    def test_exclusion_qty_accumulates(self) -> None:
        from forecast_data import base_demand_view

        for i in range(8):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"D{i}")
        self._add_sale(event_at="2026-05-07", qty=500, document_no="B1_DOC")
        self._add_sale(event_at="2026-05-07", qty=700, document_no="B2_DOC")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["exclusion_count"] == 2
        assert out["exclusion_qty"] == 1200

    def test_window_boundary_excludes_outside(self) -> None:
        from forecast_data import base_demand_view

        for i in range(8):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"IN{i}")
        self._add_sale(event_at="2026-04-01", qty=10, document_no="OUT")
        out = base_demand_view("B1", end_date=date(2026, 5, 31), weeks=4)
        assert sum(out["series"].values()) == 80

    def test_returns_netted_within_doc(self) -> None:
        from forecast_data import base_demand_view

        for i in range(5):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"D{i}")
        self._add_sale(event_at="2026-05-06", qty=10, document_no="NET")
        self._add_sale(event_at="2026-05-07", qty=-3, document_no="NET")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["series"][_monday(date(2026, 5, 6))] == 57

    def test_orphan_return_not_in_series_and_not_excluded(self) -> None:
        from forecast_data import base_demand_view

        for i in range(5):
            self._add_sale(event_at="2026-05-06", qty=10, document_no=f"D{i}")
        self._add_sale(event_at="2026-05-06", qty=-3, document_no="ORPHAN")
        out = base_demand_view("B1", end_date=date(2026, 5, 11), weeks=4)
        assert out["series"][_monday(date(2026, 5, 6))] == 50
        assert out["exclusion_count"] == 0


class IsBulkOrderTests(unittest.TestCase):
    """plan §1.5: qty > median + k·IQR → True; 不再用均值."""

    def test_none_stats_returns_false(self) -> None:
        from forecast_data import is_bulk_order

        assert is_bulk_order(1000, None) is False

    def test_below_threshold(self) -> None:
        from forecast_data import is_bulk_order

        stats = {"median": 10, "q1": 8, "q3": 12, "iqr": 4}
        # threshold = 10 + 3*4 = 22; qty=20 < 22
        assert is_bulk_order(20, stats) is False

    def test_at_threshold_not_bulk(self) -> None:
        from forecast_data import is_bulk_order

        stats = {"median": 10, "q1": 8, "q3": 12, "iqr": 4}
        # threshold = 22; qty=22 → not strict greater → False
        assert is_bulk_order(22, stats) is False

    def test_above_threshold(self) -> None:
        from forecast_data import is_bulk_order

        stats = {"median": 10, "q1": 8, "q3": 12, "iqr": 4}
        assert is_bulk_order(23, stats) is True

    def test_custom_k(self) -> None:
        from forecast_data import is_bulk_order

        stats = {"median": 10, "q1": 8, "q3": 12, "iqr": 4}
        # k=1 → threshold = 14; qty=15 > 14 → True
        assert is_bulk_order(15, stats, k=1.0) is True
        # k=5 → threshold = 30; qty=15 < 30 → False
        assert is_bulk_order(15, stats, k=5.0) is False

    def test_iqr_zero_only_median_matters(self) -> None:
        from forecast_data import is_bulk_order

        stats = {"median": 10, "q1": 10, "q3": 10, "iqr": 0}
        assert is_bulk_order(10, stats) is False
        assert is_bulk_order(11, stats) is True

    def test_negative_qty_never_bulk(self) -> None:
        from forecast_data import is_bulk_order

        stats = {"median": 10, "q1": 8, "q3": 12, "iqr": 4}
        assert is_bulk_order(-5, stats) is False


if __name__ == "__main__":
    unittest.main()
