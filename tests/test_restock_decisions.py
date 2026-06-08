"""restock_decisions service 测试."""

from __future__ import annotations

import unittest

from sqlalchemy import select

from app.models import InventoryEvent, RestockDecision
from app.repositories import stockpile_db
from app.services import restock_decisions as svc


def _item(barcode="B1", urgency=80, **kw):
    base = {
        "barcode": barcode,
        "urgency_score": urgency,
        "weekly_revenue": 50.0,
        "weekly_velocity": 4.0,
        "margin_pct": 45.0,
        "weeks_of_cover": 3.0,
        "margin_source": "purchase",
        "origin": "FOREIGN",
        "supplier_id": "GR0001",
        "urgency_breakdown": {
            "velocity": 24,
            "cover": 22.5,
            "recency": 6,
            "margin": 27,
            "velocity_pctile": 0.8,
            "margin_pctile": 0.9,
            "margin_missing": False,
            "margin_source": "purchase",
        },
    }
    base.update(kw)
    return base


class _Base(unittest.TestCase):
    # DB 隔离由 conftest autouse _isolate_db 负责（unified engine 指向 tmp db_path）
    pass


class RecordDecisionTests(_Base):
    def test_ordered_high_urgency_stays_ordered(self):
        with stockpile_db._session() as s:
            d = svc.classify_ordered(_item(urgency=80))
            svc.record_decision(s, "B1", d, _item(urgency=80))
            s.commit()
        with stockpile_db._session() as s:
            row = s.execute(select(RestockDecision)).scalar_one()
            assert row.decision == "ordered"
            assert row.urgency_score == 80
            assert row.breakdown_velocity == 24

    def test_ordered_low_urgency_becomes_overridden(self):
        with stockpile_db._session() as s:
            d = svc.classify_ordered(_item(urgency=30))
            svc.record_decision(s, "B2", d, _item(urgency=30))
            s.commit()
        with stockpile_db._session() as s:
            row = s.execute(select(RestockDecision)).scalar_one()
            assert row.decision == "overridden"

    def test_skipped_with_reason(self):
        with stockpile_db._session() as s:
            svc.record_decision(s, "B3", "skipped", _item(urgency=75), reason="供应商断货")
            s.commit()
        with stockpile_db._session() as s:
            row = s.execute(select(RestockDecision)).scalar_one()
            assert row.decision == "skipped"
            assert row.reason == "供应商断货"
            assert row.urgency_score == 75

    def test_snapshot_handles_null_breakdown(self):
        item = _item(urgency=None, urgency_breakdown=None)
        with stockpile_db._session() as s:
            svc.record_decision(s, "B4", "skipped", item, reason="新品观察")
            s.commit()
        with stockpile_db._session() as s:
            row = s.execute(select(RestockDecision)).scalar_one()
            assert row.urgency_score is None
            assert row.breakdown_velocity is None


class ListAndStatsTests(_Base):
    def _seed(self):
        with stockpile_db._session() as s:
            svc.record_decision(s, "B1", "ordered", _item(urgency=80, supplier_id="GR0001"))
            svc.record_decision(s, "B2", "ordered", _item(urgency=75, supplier_id="GR0001"))
            svc.record_decision(
                s,
                "B3",
                "skipped",
                _item(urgency=70, supplier_id="CN0001", origin="CN"),
                reason="r1",
            )
            svc.record_decision(s, "B4", "overridden", _item(urgency=30, supplier_id="GR0002"))
            s.commit()

    def test_list_recent_returns_all(self):
        self._seed()
        with stockpile_db._session() as s:
            rows = svc.list_recent(s)
            assert len(rows) == 4

    def test_list_recent_filters_by_decision(self):
        self._seed()
        with stockpile_db._session() as s:
            rows = svc.list_recent(s, decision="skipped")
            assert len(rows) == 1
            assert rows[0]["barcode"] == "B3"

    def test_aggregate_stats(self):
        self._seed()
        with stockpile_db._session() as s:
            stats = svc.aggregate_stats(s, days=30)
            assert stats["total"] == 4
            assert stats["by_decision"]["ordered"] == 2
            assert stats["by_decision"]["skipped"] == 1
            assert stats["by_decision"]["overridden"] == 1
            assert stats["by_origin_skipped"].get("CN") == 1
            assert stats["by_origin_ordered"].get("FOREIGN") == 2

    def test_stale_high_score_filters_recently_ordered(self):
        self._seed()  # B1, B2 都被 ordered
        items = [
            _item(barcode="B1", urgency=80),  # 已 ordered, 不算 stale
            _item(barcode="B5", urgency=85),  # 未处理, 算 stale
            _item(barcode="B6", urgency=40),  # 低分, 不算 stale
        ]
        with stockpile_db._session() as s:
            stale = svc.list_stale_high_score(s, items)
            barcodes = [it["barcode"] for it in stale]
            assert "B5" in barcodes
            assert "B1" not in barcodes
            assert "B6" not in barcodes


class SuppressedTests(_Base):
    """list_suppressed: 最近一条是 skipped 且 14 天内且无后续新进货 → 抑制."""

    @staticmethod
    def _days_ago(n: int) -> str:
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _date_ago(n: int) -> str:
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")

    def _add_decision(self, s, barcode, decision, days_ago, reason=None):
        s.add(
            RestockDecision(
                barcode=barcode,
                decision=decision,
                decided_at=self._days_ago(days_ago),
                reason=reason,
                urgency_score=80,
            )
        )

    def _add_purchase(self, s, barcode, days_ago):
        s.add(
            InventoryEvent(
                event_at=self._date_ago(days_ago),
                event_type="purchase",
                product_barcode=barcode,
                qty=10,
            )
        )

    def test_recent_skip_within_window_no_purchase_is_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B1", "skipped", days_ago=5, reason="供应商断货")
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B1" in sup
        assert sup["B1"]["reason"] == "供应商断货"
        assert sup["B1"]["days_left"] == svc.SKIP_SUPPRESS_DAYS - 5

    def test_skip_older_than_window_not_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B2", "skipped", days_ago=15)
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B2" not in sup

    def test_latest_decision_ordered_not_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B3", "skipped", days_ago=6)
            self._add_decision(s, "B3", "ordered", days_ago=2)  # 更近的是 ordered
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B3" not in sup

    def test_purchase_after_skip_releases(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B4", "skipped", days_ago=6)
            self._add_purchase(s, "B4", days_ago=2)  # 进货晚于跳过日
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B4" not in sup

    def test_same_day_purchase_still_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B5", "skipped", days_ago=6)
            self._add_purchase(s, "B5", days_ago=6)  # 同日进货, 不算晚于
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B5" in sup

    def test_multiple_skips_uses_latest(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B6", "skipped", days_ago=10, reason="旧原因")
            self._add_decision(s, "B6", "skipped", days_ago=3, reason="新原因")
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert sup["B6"]["reason"] == "新原因"
        assert sup["B6"]["days_left"] == svc.SKIP_SUPPRESS_DAYS - 3


if __name__ == "__main__":
    unittest.main()
