"""backtest_service 单测 (plan §2.1-2.7)."""

from __future__ import annotations

import shutil
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from sqlalchemy import insert, select

from app.repositories import stockpile_db
from app.models import BacktestResult, BacktestRun, InventoryEvent, Stockpile

_TMP = Path(__file__).resolve().parent / "_test_backtest_service"


class ForecastDistTests(unittest.TestCase):
    def test_dataclass_fields(self) -> None:
        from app.services.backtest import ForecastDist

        d = ForecastDist(mu=1.5, sigma=0.3, p50=1.5, p98=2.1)
        assert d.mu == 1.5
        assert d.p98 == 2.1


class MetricsTests(unittest.TestCase):
    def test_mape_simple(self) -> None:
        from app.services.backtest import mape

        assert abs(mape([10, 20], [12, 18]) - 0.15) < 1e-9

    def test_mape_zero_actuals_excluded(self) -> None:
        from app.services.backtest import mape

        assert abs(mape([0, 10], [5, 11]) - 0.1) < 1e-9

    def test_mape_all_zero_actuals_returns_none(self) -> None:
        from app.services.backtest import mape

        assert mape([0, 0, 0], [1, 2, 3]) is None

    def test_mape_empty_returns_none(self) -> None:
        from app.services.backtest import mape

        assert mape([], []) is None

    def test_bias_signed(self) -> None:
        from app.services.backtest import bias

        assert abs(bias([10, 20], [12, 17]) - (-0.5)) < 1e-9

    def test_mase(self) -> None:
        from app.services.backtest import mase

        assert abs(mase([10, 20, 30, 40], [15, 25, 35, 45]) - 0.5) < 1e-9

    def test_mase_constant_actuals_none(self) -> None:
        from app.services.backtest import mase

        assert mase([5, 5, 5], [4, 6, 5]) is None

    def test_coverage_p98_in_bound(self) -> None:
        from app.services.backtest import coverage_p98

        assert abs(coverage_p98([5, 15, 25], [10, 20, 20]) - 2 / 3) < 1e-9

    def test_coverage_p98_all_in(self) -> None:
        from app.services.backtest import coverage_p98

        assert coverage_p98([1, 2, 3], [10, 10, 10]) == 1.0


class NaiveMean4WTests(unittest.TestCase):
    def test_predicts_mean_of_last_4(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([1, 2, 3, 4, 5, 6, 7, 8])
        p = m.predict()
        assert p.mu == 6.5
        assert p.p50 == 6.5

    def test_short_history_uses_all(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([10, 20])
        assert m.predict().mu == 15.0

    def test_empty_history(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([])
        p = m.predict()
        assert p.mu == 0.0
        assert p.sigma == 0.0
        assert p.p98 == 0.0

    def test_p98_never_negative(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([0, 0, 0, 0])
        assert m.predict().p98 >= 0


class NaiveSeasonal52WTests(unittest.TestCase):
    def test_predicts_lag_52(self) -> None:
        from app.services.backtest import NaiveSeasonal52W

        history = [0] + [42] + [0] * 51
        m = NaiveSeasonal52W()
        m.fit(history)
        assert m.predict().mu == 42.0

    def test_short_history_falls_back_to_mean(self) -> None:
        from app.services.backtest import NaiveSeasonal52W

        m = NaiveSeasonal52W()
        m.fit([1, 2, 3])
        assert m.predict().mu == 2.0


class LinearTrend12WTests(unittest.TestCase):
    def test_increasing_trend(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        assert abs(m.predict().mu - 13.0) < 1e-6

    def test_constant_trend_predicts_constant(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([5] * 12)
        assert abs(m.predict().mu - 5.0) < 1e-6

    def test_short_history_falls_back_to_mean(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([5, 10])
        assert m.predict().mu == 7.5

    def test_p98_never_negative(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([10, 8, 6, 4, 2, 1, 0, 0, 0, 0, 0, 0])
        assert m.predict().p98 >= 0


class CrostonSBATests(unittest.TestCase):
    """plan §2.2 间歇需求 baseline."""

    def test_basic_intermittent(self) -> None:
        from app.services.backtest import CrostonSBA

        history = [0, 0, 6, 0, 0, 6, 0, 0, 6]
        m = CrostonSBA()
        m.fit(history)
        p = m.predict()
        assert 1.5 < p.mu < 2.0

    def test_no_demand(self) -> None:
        from app.services.backtest import CrostonSBA

        m = CrostonSBA()
        m.fit([0, 0, 0, 0, 0])
        assert m.predict().mu == 0.0

    def test_single_demand_at_start(self) -> None:
        from app.services.backtest import CrostonSBA

        m = CrostonSBA()
        m.fit([10, 0, 0, 0, 0])
        p = m.predict()
        assert 9.0 <= p.mu <= 10.0

    def test_empty_history(self) -> None:
        from app.services.backtest import CrostonSBA

        m = CrostonSBA()
        m.fit([])
        assert m.predict().mu == 0.0


class WalkForwardTests(unittest.TestCase):
    def test_record_count(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert len(records) == 30

    def test_record_keys(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert set(records[0].keys()) == {
            "step_idx",
            "horizon",
            "predicted",
            "p50",
            "p98",
            "actual",
        }

    def test_horizon_cycles(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert [r["horizon"] for r in records[:4]] == [1, 2, 1, 2]

    def test_actual_matches_test_window(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert records[0]["actual"] == 5
        assert records[1]["actual"] == 6

    def test_step_idx_global_position(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert records[0]["step_idx"] == 4
        assert records[1]["step_idx"] == 5

    def test_too_short_returns_empty(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        records = walk_forward_backtest([1, 2, 3], NaiveMean4W, window_train=4, window_test=2)
        assert records == []


class _DBBase(unittest.TestCase):
    """DB 集成测试基类: 在临时 SQLite 上 seed 一个高频零售 SKU."""

    def setUp(self) -> None:
        self.test_dir = _TMP / self._testMethodName
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

    def _seed_stockpile(self, barcode: str) -> None:
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

    def _seed_retail_weekly(self, barcode: str, weeks: int, qty: int = 5) -> None:
        """构造 weeks 周, 每周 qty 单零售销售 (qty<=24 → retail_dominant)."""
        from datetime import timedelta

        with stockpile_db._session() as s:
            for w in range(weeks):
                event_at = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=event_at,
                        event_type="sale",
                        product_barcode=barcode,
                        qty=qty,
                        document_no=f"{barcode}-D{w}",
                    )
                )
            s.commit()


class RunBacktestForSkuTests(_DBBase):
    def test_returns_metrics_dict(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        self._seed_retail_weekly("B1", weeks=30)
        r = run_backtest_for_sku("B1", end_date=date(2026, 5, 13), weeks=30, model_cls=NaiveMean4W)
        assert r is not None
        assert r["barcode"] == "B1"
        assert r["sku_type"] == "retail_dominant"
        assert r["mape"] is not None
        assert "bias" in r
        assert "coverage_p98" in r

    def test_returns_none_if_too_short(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        self._seed_retail_weekly("B1", weeks=5)
        r = run_backtest_for_sku(
            "B1",
            end_date=date(2026, 5, 13),
            weeks=4,
            model_cls=NaiveMean4W,
            window_train=13,
            window_test=4,
        )
        assert r is None

    def test_returns_none_if_min_weeks_not_met(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        self._seed_retail_weekly("B1", weeks=30)
        r = run_backtest_for_sku(
            "B1",
            end_date=date(2026, 5, 13),
            weeks=30,
            model_cls=NaiveMean4W,
            min_weeks=100,
        )
        assert r is None

    def test_wholesale_only_returns_none(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        # 5 个大单 doc → wholesale_only
        with stockpile_db._session() as s:
            for i in range(5):
                s.execute(
                    insert(InventoryEvent).values(
                        event_at="2026-04-01",
                        event_type="sale",
                        product_barcode="WO",
                        qty=720,
                        document_no=f"D{i}",
                    )
                )
            s.commit()
        r = run_backtest_for_sku(
            "WO",
            end_date=date(2026, 5, 13),
            weeks=30,
            model_cls=NaiveMean4W,
            view="base_demand",
        )
        assert r is None

    def test_view_all_includes_wholesale(self) -> None:
        """view='all' 不过 base_demand → wholesale_only SKU 也跑."""
        from datetime import timedelta

        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        with stockpile_db._session() as s:
            for w in range(30):
                event_at = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=event_at,
                        event_type="sale",
                        product_barcode="WO",
                        qty=720,
                        document_no=f"D{w}",
                    )
                )
            s.commit()
        r = run_backtest_for_sku(
            "WO",
            end_date=date(2026, 5, 13),
            weeks=30,
            model_cls=NaiveMean4W,
            view="all",
        )
        assert r is not None
        assert r["sku_type"] == "wholesale_only"


class RunBacktestAllSkusTests(_DBBase):
    def test_writes_run_and_results(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_retail_weekly("B1", weeks=30)
        run_id = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
            notes="test",
        )
        with stockpile_db._session() as s:
            run = s.execute(select(BacktestRun).where(BacktestRun.id == run_id)).scalar_one()
            assert run.model_name == "NaiveMean4W"
            assert run.notes == "test"
            assert run.n_skus_total == 1
            assert run.n_skus_scored == 1
            results = (
                s.execute(select(BacktestResult).where(BacktestResult.run_id == run_id))
                .scalars()
                .all()
            )
            assert len(results) == 1
            assert results[0].product_barcode == "B1"
            assert results[0].sku_type == "retail_dominant"

    def test_skipped_sku_not_in_results(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_retail_weekly("B1", weeks=5)  # 太短
        run_id = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        with stockpile_db._session() as s:
            run = s.execute(select(BacktestRun).where(BacktestRun.id == run_id)).scalar_one()
            assert run.n_skus_total == 1
            assert run.n_skus_scored == 0
            results = (
                s.execute(select(BacktestResult).where(BacktestResult.run_id == run_id))
                .scalars()
                .all()
            )
            assert results == []

    def test_unknown_model_raises(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        with self.assertRaises(ValueError):
            run_backtest_all_skus(
                model_name="DoesNotExist",
                end_date=date(2026, 5, 13),
                barcodes=[],
            )

    def test_unknown_view_raises(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        with self.assertRaises(ValueError):
            run_backtest_all_skus(
                model_name="NaiveMean4W",
                end_date=date(2026, 5, 13),
                view="not_a_view",
                barcodes=[],
            )


class CompareRunPairTests(_DBBase):
    """plan §2.8 双视图回测对比."""

    def test_returns_summary_with_common_skus(self) -> None:
        from app.services.backtest import compare_run_pair, run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_retail_weekly("B1", weeks=30)
        run_a = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            view="all",
            barcodes=["B1"],
        )
        run_b = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            view="base_demand",
            barcodes=["B1"],
        )
        cmp = compare_run_pair(run_a, run_b)
        assert cmp["run_a"]["id"] == run_a
        assert cmp["run_b"]["id"] == run_b
        assert cmp["run_a"]["view"] == "all"
        assert cmp["run_b"]["view"] == "base_demand"
        assert cmp["common_skus"] == 1
        assert len(cmp["items"]) == 1
        item = cmp["items"][0]
        assert item["product_barcode"] == "B1"
        assert "mase_delta" in item

    def test_summary_counts_unchanged_when_identical(self) -> None:
        """同一 SKU 同一视图 同一模型 → MASE 一致 → unchanged 计 1."""
        from datetime import timedelta

        from app.services.backtest import compare_run_pair, run_backtest_all_skus

        # 波动序列, 让 lag-1 naive MAE != 0 → MASE 非 None
        self._seed_stockpile("B1")
        with stockpile_db._session() as s:
            for w in range(30):
                d = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
                qty = 5 + (w % 3)  # 5, 6, 7, 5, 6, 7, ...
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=d,
                        event_type="sale",
                        product_barcode="B1",
                        qty=qty,
                        document_no=f"B1-D{w}",
                    )
                )
            s.commit()
        ra = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        rb = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        cmp = compare_run_pair(ra, rb)
        assert cmp["common_skus"] == 1
        assert cmp["summary"]["improved"] == 0
        assert cmp["summary"]["worsened"] == 0
        assert cmp["summary"]["unchanged"] == 1
        assert cmp["summary"]["median_mase_delta"] == 0.0

    def test_unknown_run_raises(self) -> None:
        from app.services.backtest import compare_run_pair

        with self.assertRaises(ValueError):
            compare_run_pair(99999, 99998)

    def test_no_common_skus_empty_items(self) -> None:
        from app.services.backtest import compare_run_pair, run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_stockpile("B2")
        self._seed_retail_weekly("B1", weeks=30)
        self._seed_retail_weekly("B2", weeks=30)
        ra = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        rb = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B2"],
        )
        cmp = compare_run_pair(ra, rb)
        assert cmp["common_skus"] == 0
        assert cmp["items"] == []


if __name__ == "__main__":
    unittest.main()
