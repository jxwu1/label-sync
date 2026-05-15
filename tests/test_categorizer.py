"""categorizer 单测（PR 5.1）。

每个 case 用合成数据触发对应分类，验证优先级与边界。
"""

from __future__ import annotations

import shutil
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np
from sqlalchemy import insert

import stockpile_db
from models import InventoryEvent

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_categorizer"


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

    def _add_sale(
        self,
        event_at: str,
        qty: int = 1,
        barcode: str = "B1",
        document_no: str | None = None,
    ) -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type="sale",
                    product_barcode=barcode,
                    qty=qty,
                    document_no=document_no or f"D-{event_at}-{qty}",
                )
            )
            s.commit()


class ClassifySkuTests(_Base):
    def test_no_data_unclassified(self) -> None:
        from categorizer import classify_sku

        assert classify_sku("NOPE", as_of=date(2026, 5, 1)) == "unclassified"

    def test_new_under_4_weeks(self) -> None:
        from categorizer import classify_sku

        # 第一笔 14 天前 → 新品
        self._add_sale("2026-04-17", qty=5)
        assert classify_sku("B1", as_of=date(2026, 5, 1)) == "new"

    def test_new_window_boundary(self) -> None:
        """27 天前还是 new，28 天前不是。"""
        from categorizer import classify_sku

        as_of = date(2026, 5, 1)
        # 27 天前
        self._add_sale((as_of - timedelta(days=27)).isoformat(), qty=1)
        assert classify_sku("B1", as_of=as_of) == "new"

    def test_stable_steady_sales(self) -> None:
        """半年稳定每周 10 件 → stable。"""
        from categorizer import classify_sku

        as_of = date(2026, 5, 1)
        # 26 周稳定
        for w in range(30):
            d = as_of - timedelta(days=(w + 1) * 7)
            self._add_sale(d.isoformat(), qty=10, document_no=f"S{w}")
        assert classify_sku("B1", as_of=as_of) == "stable"

    def test_declining_quarter_over_quarter(self) -> None:
        """上季度比再上季度跌 ≥ 30% + 最近 4 周斜率负 → declining。"""
        from categorizer import classify_sku

        as_of = date(2026, 5, 1)
        # 再上一季度（180-90 天前）：每周 20 件
        for w in range(13):
            d = as_of - timedelta(days=90 + w * 7)
            if (as_of - d).days < 180:
                self._add_sale(d.isoformat(), qty=20, document_no=f"PP{w}")
        # 上一季度（90-0 天前）：每周 5 件，且最近 4 周递减
        recent_weeks = [10, 8, 5, 2]  # 最新在最后
        for i, q in enumerate(recent_weeks):
            d = as_of - timedelta(days=(4 - i) * 7)
            self._add_sale(d.isoformat(), qty=q, document_no=f"R{i}")
        # 中间过渡（5-13 周前）少量
        for w in range(5, 13):
            d = as_of - timedelta(days=w * 7)
            self._add_sale(d.isoformat(), qty=2, document_no=f"M{w}")

        result = classify_sku("B1", as_of=as_of)
        assert result == "declining", f"expected declining, got {result}"

    def test_seasonal_passes_when_long_history(self) -> None:
        """合成 70 周数据，年周期波形 → seasonal 触发。"""
        from categorizer import classify_sku

        as_of = date(2026, 5, 1)
        # 70 周（>= 52），波形：sin(2π × week/52)，振幅 5，offset 6 保正数
        for w in range(70):
            d = as_of - timedelta(days=(70 - w) * 7)
            qty = max(1, int(round(6 + 5 * float(np.sin(2 * np.pi * w / 52)))))
            self._add_sale(d.isoformat(), qty=qty, document_no=f"S{w}")
        result = classify_sku("B1", as_of=as_of)
        assert result == "seasonal", f"expected seasonal, got {result}"

    def test_priority_new_beats_others(self) -> None:
        """所有数据都在 4 周内 → 必须是 new，即使其它规则可能命中。"""
        from categorizer import classify_sku

        as_of = date(2026, 5, 1)
        self._add_sale((as_of - timedelta(days=10)).isoformat(), qty=10)
        assert classify_sku("B1", as_of=as_of) == "new"

    def test_unclassified_when_sparse(self) -> None:
        """寿命 ≥ 4 周但数据稀疏不满足 stable/declining/seasonal → unclassified。"""
        from categorizer import classify_sku

        as_of = date(2026, 5, 1)
        self._add_sale("2025-01-01", qty=1)
        self._add_sale("2025-06-01", qty=1)
        self._add_sale("2026-01-01", qty=1)
        result = classify_sku("B1", as_of=as_of)
        assert result == "unclassified"


class ACFInternalTests(unittest.TestCase):
    def test_acf_perfect_periodic(self) -> None:
        from categorizer import _acf_at_lag

        # 周期 4 的方波
        series = [10, 10, 1, 1, 10, 10, 1, 1, 10, 10, 1, 1]
        acf = _acf_at_lag(series, 4)
        assert acf is not None
        assert acf > 0.5

    def test_acf_lag_too_large(self) -> None:
        from categorizer import _acf_at_lag

        assert _acf_at_lag([1, 2, 3], 10) is None

    def test_acf_zero_variance(self) -> None:
        from categorizer import _acf_at_lag

        assert _acf_at_lag([5, 5, 5, 5, 5], 1) is None


class ClassifySkuTypeFromDocsTests(unittest.TestCase):
    """纯函数 classify_sku_type_from_docs 边界 — plan §1.0.2.

    输入: 每 doc 净量列表 (> 0). 输出:
      retail_dominant / mixed / wholesale_only / unclassified
    阈值: retail = qty <= 24; wholesale_only = retail < 5 OR ratio < 5%;
          retail_dominant = ratio >= 80%; 其余 mixed.
    """

    def test_empty_unclassified(self) -> None:
        from categorizer import classify_sku_type_from_docs

        assert classify_sku_type_from_docs([]) == "unclassified"

    def test_all_retail(self) -> None:
        from categorizer import classify_sku_type_from_docs

        assert classify_sku_type_from_docs([1, 5, 10, 20, 24] * 2) == "retail_dominant"

    def test_all_wholesale(self) -> None:
        from categorizer import classify_sku_type_from_docs

        assert classify_sku_type_from_docs([100, 200, 500, 1000, 720] * 2) == "wholesale_only"

    def test_50_50_is_mixed(self) -> None:
        from categorizer import classify_sku_type_from_docs

        docs = [10] * 5 + [100] * 5
        assert classify_sku_type_from_docs(docs) == "mixed"

    def test_retail_rows_lt_5_forces_wholesale_only(self) -> None:
        """4 笔零售 + 100 笔批发 → wholesale_only (retail < 5)."""
        from categorizer import classify_sku_type_from_docs

        docs = [10] * 4 + [500] * 100
        assert classify_sku_type_from_docs(docs) == "wholesale_only"

    def test_retail_rows_eq_5_pure_retail_dominant(self) -> None:
        from categorizer import classify_sku_type_from_docs

        assert classify_sku_type_from_docs([10] * 5) == "retail_dominant"

    def test_retail_ratio_under_5pct_wholesale(self) -> None:
        """5 笔零售 + 100 笔批发 → ratio 4.76% < 5% → wholesale_only."""
        from categorizer import classify_sku_type_from_docs

        docs = [10] * 5 + [500] * 100
        assert classify_sku_type_from_docs(docs) == "wholesale_only"

    def test_retail_ratio_eq_80pct_is_retail_dominant(self) -> None:
        """8 retail + 2 wholesale → 80% (含边界) → retail_dominant."""
        from categorizer import classify_sku_type_from_docs

        docs = [10] * 8 + [500] * 2
        assert classify_sku_type_from_docs(docs) == "retail_dominant"

    def test_retail_ratio_79pct_is_mixed(self) -> None:
        from categorizer import classify_sku_type_from_docs

        docs = [10] * 79 + [500] * 21
        assert classify_sku_type_from_docs(docs) == "mixed"

    def test_qty_24_is_retail_25_is_wholesale(self) -> None:
        from categorizer import classify_sku_type_from_docs

        assert classify_sku_type_from_docs([24] * 10) == "retail_dominant"
        assert classify_sku_type_from_docs([25] * 10) == "wholesale_only"


class _SkuTypeBase(unittest.TestCase):
    """DB 层入口 classify_sku_type 测试基类."""

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
        qty: int,
        document_no: str | None = None,
        event_at: str = "2026-05-01",
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


class ClassifySkuTypeDyingTests(_SkuTypeBase):
    """plan §1.0.2 加 dying: 最后销售距 as_of >= 13 周 (无 sale) → dying."""

    def test_recent_sales_not_dying(self) -> None:
        """最近 4 周内有销售 → retail_dominant 不是 dying."""
        from categorizer import classify_sku_type

        for w in range(4):
            d = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
            self._add_event(qty=10, document_no=f"D{w}", event_at=d)
        for i in range(5):
            self._add_event(qty=10, document_no=f"old{i}", event_at="2024-01-01")
        assert classify_sku_type("B1", as_of=date(2026, 5, 13)) == "retail_dominant"

    def test_no_sales_in_last_13_weeks_marks_dying(self) -> None:
        """最后一笔在 14 周前 → dying."""
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(qty=10, document_no=f"D{i}", event_at="2025-01-01")
        self._add_event(qty=10, document_no="last", event_at="2026-02-04")
        assert classify_sku_type("B1", as_of=date(2026, 5, 13)) == "dying"

    def test_boundary_13_weeks_exactly_is_dying(self) -> None:
        """边界: 最后销售距 as_of 恰好 13 周 → dying."""
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(qty=10, document_no=f"D{i}", event_at="2025-01-01")
        self._add_event(qty=10, document_no="last", event_at="2026-02-11")
        assert classify_sku_type("B1", as_of=date(2026, 5, 13)) == "dying"

    def test_12_weeks_ago_not_dying(self) -> None:
        """边界: 12 周前 → 仍算活, 不是 dying."""
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(qty=10, document_no=f"D{i}", event_at="2025-01-01")
        self._add_event(qty=10, document_no="last", event_at="2026-02-18")
        out = classify_sku_type("B1", as_of=date(2026, 5, 13))
        assert out != "dying"
        assert out == "retail_dominant"

    def test_dying_takes_precedence_over_wholesale(self) -> None:
        """dying 优先于 wholesale_only (停售比批发更紧急)."""
        from categorizer import classify_sku_type

        for i in range(5):
            self._add_event(qty=720, document_no=f"D{i}", event_at="2024-01-01")
        assert classify_sku_type("B1", as_of=date(2026, 5, 13)) == "dying"

    def test_as_of_none_uses_today(self) -> None:
        """as_of=None 用 datetime.now().date()."""
        from categorizer import classify_sku_type

        for i in range(5):
            self._add_event(qty=10, document_no=f"D{i}", event_at="2024-01-01")
        assert classify_sku_type("B1") == "dying"


class ClassifySkuTypeTests(_SkuTypeBase):
    def test_no_data_unclassified(self) -> None:
        from categorizer import classify_sku_type

        assert classify_sku_type("NOPE") == "unclassified"

    def test_pure_retail(self) -> None:
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(qty=10, document_no=f"D{i}")
        assert classify_sku_type("B1") == "retail_dominant"

    def test_pure_wholesale(self) -> None:
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(qty=720, document_no=f"D{i}")
        assert classify_sku_type("B1") == "wholesale_only"

    def test_doc_net_with_returns(self) -> None:
        """qty=25 + 同 doc qty=-3 → 净 22 → 算 retail."""
        from categorizer import classify_sku_type

        self._add_event(qty=25, document_no="D1", event_at="2026-05-01")
        self._add_event(qty=-3, document_no="D1", event_at="2026-05-02")
        for i in range(4):
            self._add_event(qty=10, document_no=f"D{i + 2}")
        assert classify_sku_type("B1") == "retail_dominant"

    def test_orphan_return_excluded(self) -> None:
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(qty=10, document_no=f"D{i}")
        self._add_event(qty=-3, document_no="ORPHAN")
        assert classify_sku_type("B1") == "retail_dominant"

    def test_fully_cancelled_doc_excluded(self) -> None:
        from categorizer import classify_sku_type

        self._add_event(qty=5, document_no="X1")
        self._add_event(qty=-5, document_no="X1")
        for i in range(5):
            self._add_event(qty=10, document_no=f"D{i}")
        assert classify_sku_type("B1") == "retail_dominant"

    def test_null_document_no_each_independent(self) -> None:
        from categorizer import classify_sku_type

        for _ in range(5):
            self._add_event(qty=10, document_no=None)
        assert classify_sku_type("B1") == "retail_dominant"

    def test_purchase_events_excluded(self) -> None:
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(qty=10, document_no=f"P{i}", event_type="purchase")
        assert classify_sku_type("B1") == "unclassified"

    def test_other_barcodes_excluded(self) -> None:
        from categorizer import classify_sku_type

        for i in range(10):
            self._add_event(barcode="B1", qty=500, document_no=f"D{i}")
        for i in range(10):
            self._add_event(barcode="B2", qty=10, document_no=f"E{i}")
        assert classify_sku_type("B1") == "wholesale_only"


if __name__ == "__main__":
    unittest.main()
