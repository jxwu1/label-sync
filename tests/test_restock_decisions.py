"""restock_decisions service 测试."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import select

from app.models import RestockDecision
from app.repositories import stockpile_db
from app.services import restock_decisions as svc

_TEST_DIR = Path(__file__).resolve().parent / "_test_restock_decisions"


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
    def setUp(self):
        self.test_dir = _TEST_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()

    def tearDown(self):
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)


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


if __name__ == "__main__":
    unittest.main()
