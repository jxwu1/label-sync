"""backtest_service 单测 (plan §2.1-2.4 纯算法层)."""
from __future__ import annotations

import unittest


class ForecastDistTests(unittest.TestCase):
    def test_dataclass_fields(self) -> None:
        from backtest_service import ForecastDist

        d = ForecastDist(mu=1.5, sigma=0.3, p50=1.5, p98=2.1)
        assert d.mu == 1.5
        assert d.p98 == 2.1


class MetricsTests(unittest.TestCase):
    def test_mape_simple(self) -> None:
        from backtest_service import mape

        assert abs(mape([10, 20], [12, 18]) - 0.15) < 1e-9

    def test_mape_zero_actuals_excluded(self) -> None:
        from backtest_service import mape

        assert abs(mape([0, 10], [5, 11]) - 0.1) < 1e-9

    def test_mape_all_zero_actuals_returns_none(self) -> None:
        from backtest_service import mape

        assert mape([0, 0, 0], [1, 2, 3]) is None

    def test_mape_empty_returns_none(self) -> None:
        from backtest_service import mape

        assert mape([], []) is None

    def test_bias_signed(self) -> None:
        from backtest_service import bias

        assert abs(bias([10, 20], [12, 17]) - (-0.5)) < 1e-9

    def test_mase(self) -> None:
        from backtest_service import mase

        assert abs(mase([10, 20, 30, 40], [15, 25, 35, 45]) - 0.5) < 1e-9

    def test_mase_constant_actuals_none(self) -> None:
        from backtest_service import mase

        assert mase([5, 5, 5], [4, 6, 5]) is None

    def test_coverage_p98_in_bound(self) -> None:
        from backtest_service import coverage_p98

        assert abs(coverage_p98([5, 15, 25], [10, 20, 20]) - 2 / 3) < 1e-9

    def test_coverage_p98_all_in(self) -> None:
        from backtest_service import coverage_p98

        assert coverage_p98([1, 2, 3], [10, 10, 10]) == 1.0


class NaiveMean4WTests(unittest.TestCase):
    def test_predicts_mean_of_last_4(self) -> None:
        from backtest_service import NaiveMean4W

        m = NaiveMean4W()
        m.fit([1, 2, 3, 4, 5, 6, 7, 8])
        p = m.predict()
        assert p.mu == 6.5
        assert p.p50 == 6.5

    def test_short_history_uses_all(self) -> None:
        from backtest_service import NaiveMean4W

        m = NaiveMean4W()
        m.fit([10, 20])
        assert m.predict().mu == 15.0

    def test_empty_history(self) -> None:
        from backtest_service import NaiveMean4W

        m = NaiveMean4W()
        m.fit([])
        p = m.predict()
        assert p.mu == 0.0
        assert p.sigma == 0.0
        assert p.p98 == 0.0

    def test_p98_never_negative(self) -> None:
        from backtest_service import NaiveMean4W

        m = NaiveMean4W()
        m.fit([0, 0, 0, 0])
        assert m.predict().p98 >= 0


class NaiveSeasonal52WTests(unittest.TestCase):
    def test_predicts_lag_52(self) -> None:
        from backtest_service import NaiveSeasonal52W

        history = [0] + [42] + [0] * 51
        m = NaiveSeasonal52W()
        m.fit(history)
        assert m.predict().mu == 42.0

    def test_short_history_falls_back_to_mean(self) -> None:
        from backtest_service import NaiveSeasonal52W

        m = NaiveSeasonal52W()
        m.fit([1, 2, 3])
        assert m.predict().mu == 2.0


class LinearTrend12WTests(unittest.TestCase):
    def test_increasing_trend(self) -> None:
        from backtest_service import LinearTrend12W

        m = LinearTrend12W()
        m.fit([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        assert abs(m.predict().mu - 13.0) < 1e-6

    def test_constant_trend_predicts_constant(self) -> None:
        from backtest_service import LinearTrend12W

        m = LinearTrend12W()
        m.fit([5] * 12)
        assert abs(m.predict().mu - 5.0) < 1e-6

    def test_short_history_falls_back_to_mean(self) -> None:
        from backtest_service import LinearTrend12W

        m = LinearTrend12W()
        m.fit([5, 10])
        assert m.predict().mu == 7.5

    def test_p98_never_negative(self) -> None:
        from backtest_service import LinearTrend12W

        m = LinearTrend12W()
        m.fit([10, 8, 6, 4, 2, 1, 0, 0, 0, 0, 0, 0])
        assert m.predict().p98 >= 0


class CrostonSBATests(unittest.TestCase):
    """plan §2.2 间歇需求 baseline."""

    def test_basic_intermittent(self) -> None:
        from backtest_service import CrostonSBA

        history = [0, 0, 6, 0, 0, 6, 0, 0, 6]
        m = CrostonSBA()
        m.fit(history)
        p = m.predict()
        assert 1.5 < p.mu < 2.0

    def test_no_demand(self) -> None:
        from backtest_service import CrostonSBA

        m = CrostonSBA()
        m.fit([0, 0, 0, 0, 0])
        assert m.predict().mu == 0.0

    def test_single_demand_at_start(self) -> None:
        from backtest_service import CrostonSBA

        m = CrostonSBA()
        m.fit([10, 0, 0, 0, 0])
        p = m.predict()
        assert 9.0 <= p.mu <= 10.0

    def test_empty_history(self) -> None:
        from backtest_service import CrostonSBA

        m = CrostonSBA()
        m.fit([])
        assert m.predict().mu == 0.0


class WalkForwardTests(unittest.TestCase):
    def test_record_count(self) -> None:
        from backtest_service import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert len(records) == 30

    def test_record_keys(self) -> None:
        from backtest_service import NaiveMean4W, walk_forward_backtest

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
        from backtest_service import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert [r["horizon"] for r in records[:4]] == [1, 2, 1, 2]

    def test_actual_matches_test_window(self) -> None:
        from backtest_service import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert records[0]["actual"] == 5
        assert records[1]["actual"] == 6

    def test_step_idx_global_position(self) -> None:
        from backtest_service import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert records[0]["step_idx"] == 4
        assert records[1]["step_idx"] == 5

    def test_too_short_returns_empty(self) -> None:
        from backtest_service import NaiveMean4W, walk_forward_backtest

        records = walk_forward_backtest([1, 2, 3], NaiveMean4W, window_train=4, window_test=2)
        assert records == []


if __name__ == "__main__":
    unittest.main()
