"""forecast_service 单测 (plan 阶段 3.3 EmpiricalQuantileModel)."""

from __future__ import annotations

import unittest


class EmpiricalQuantileModelTests(unittest.TestCase):
    """直接经验分位数模型 — 给 wholesale_only / 间歇序列用.

    设计要点:
    - mu = mean(history), sigma = std(history)  (常规)
    - p50 = quantile(history, 0.5)  ← 直接经验中位数
    - p98 = quantile(history, 0.98) ← 直接经验 98 分位
    - 不走 mu + z·sigma 正态近似 (wholesale 序列非正态, 偶发大单, 0 周多)
    """

    def _new(self):
        from app.services.forecast import EmpiricalQuantileModel
        return EmpiricalQuantileModel()

    def test_protocol_attrs(self) -> None:
        m = self._new()
        assert m.name == "EmpiricalQuantile"

    def test_predict_returns_forecast_dist(self) -> None:
        from app.services.backtest import ForecastDist
        m = self._new()
        m.fit([1.0, 2.0, 3.0])
        d = m.predict()
        assert isinstance(d, ForecastDist)

    def test_empty_history_zero_dist(self) -> None:
        m = self._new()
        m.fit([])
        d = m.predict()
        assert d.mu == 0.0
        assert d.sigma == 0.0
        assert d.p50 == 0.0
        assert d.p98 == 0.0

    def test_single_value_all_quantiles_equal(self) -> None:
        m = self._new()
        m.fit([7.0])
        d = m.predict()
        assert d.mu == 7.0
        assert d.sigma == 0.0
        assert d.p50 == 7.0
        assert d.p98 == 7.0

    def test_constant_history(self) -> None:
        m = self._new()
        m.fit([10.0, 10.0, 10.0, 10.0])
        d = m.predict()
        assert d.mu == 10.0
        assert d.sigma == 0.0
        assert d.p50 == 10.0
        assert d.p98 == 10.0

    def test_skewed_long_tail_p98_captures_peak(self) -> None:
        """90 个 0 周 + 10 个 100 单位的大单. p98 应贴近 100, p50 应为 0, mu = 10."""
        m = self._new()
        history = [0.0] * 90 + [100.0] * 10
        m.fit(history)
        d = m.predict()
        assert abs(d.mu - 10.0) < 1e-6
        assert d.p50 == 0.0
        assert d.p98 >= 50.0
        assert d.sigma > 0.0

    def test_wholesale_pattern_intermittent_peaks(self) -> None:
        """模拟批发: 大部分周 0, 偶发数十到数百单. p98 必须 >> p50."""
        m = self._new()
        history = [0.0] * 43 + [30.0, 50.0, 80.0, 50.0, 200.0, 30.0, 50.0]
        m.fit(history)
        d = m.predict()
        assert d.p50 == 0.0
        assert d.p98 >= 50.0
        assert abs(d.mu - 9.8) < 0.01  # 490/50

    def test_negative_values_passthrough(self) -> None:
        """负数 (退货已归并应该不出现, 但模型层不应崩)."""
        m = self._new()
        m.fit([0.0, -2.0, 5.0, 10.0, -1.0])
        d = m.predict()
        assert isinstance(d.mu, float)

    def test_steps_arg_does_not_change_result(self) -> None:
        m = self._new()
        history = [1.0, 5.0, 3.0, 8.0, 2.0]
        m.fit(history)
        d1 = m.predict(steps=1)
        d4 = m.predict(steps=4)
        assert d1.mu == d4.mu
        assert d1.sigma == d4.sigma
        assert d1.p50 == d4.p50
        assert d1.p98 == d4.p98

    def test_refit_overrides_history(self) -> None:
        m = self._new()
        m.fit([100.0, 100.0, 100.0])
        m.fit([1.0, 1.0, 1.0])
        d = m.predict()
        assert d.mu == 1.0
        assert d.p50 == 1.0
        assert d.p98 == 1.0

    def test_p98_quantile_correctness(self) -> None:
        """0..99 (100 个值), p98 应该 ≈ 97 (numpy linear interpolation)."""
        m = self._new()
        m.fit([float(i) for i in range(100)])
        d = m.predict()
        assert 96.0 <= d.p98 <= 98.5
        assert 49.0 <= d.p50 <= 50.0


if __name__ == "__main__":
    unittest.main()
