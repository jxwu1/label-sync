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


if __name__ == "__main__":
    unittest.main()
