"""forecast_service 单测 (plan 阶段 3.3 EmpiricalQuantileModel)."""

from __future__ import annotations

import unittest

import numpy as np


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


class HoltWintersModelTests(unittest.TestCase):
    """HoltWinters 指数平滑 (plan 阶段 3.2)."""

    def _new(self):
        from app.services.forecast import HoltWintersModel

        return HoltWintersModel()

    def test_protocol_attrs(self) -> None:
        m = self._new()
        assert m.name == "HoltWinters"

    def test_empty_history_zero_dist(self) -> None:
        m = self._new()
        m.fit([])
        d = m.predict()
        assert d.mu == 0.0
        assert d.p98 == 0.0
        assert m.used_path == "none"

    def test_short_history_below_min_returns_zero(self) -> None:
        m = self._new()
        m.fit([1.0, 2.0, 3.0])  # 3 < 13
        d = m.predict()
        assert d.mu == 0.0
        assert m.used_path == "none"

    def test_medium_history_uses_trend_only(self) -> None:
        """30 周 < 104, 走 trend-only 分支."""
        m = self._new()
        history = [5.0 + 0.1 * i for i in range(30)]  # 线性增长
        m.fit(history)
        assert m.used_path == "trend"
        d = m.predict()
        # 增长趋势 → 下一周预测应 >= 序列末值附近
        assert d.mu >= 7.0
        assert d.mu <= 10.0
        # mu 非负 (业务量非负)
        assert d.mu >= 0.0
        assert d.p98 >= d.mu

    def test_long_seasonal_history_uses_seasonal(self) -> None:
        """104+ 周 + 明显年度周期 → 走 seasonal 分支."""
        m = self._new()
        # 构造 2.5 年, 52 周一个 sin 波 + 噪声
        rng = np.random.default_rng(seed=42)
        weeks = 130
        seasonal = [10.0 + 5.0 * np.sin(2 * np.pi * i / 52) for i in range(weeks)]
        noisy = [s + rng.normal(0, 0.5) for s in seasonal]
        m.fit(noisy)
        # seasonal 可能因数据形态被 statsmodels 拒绝 → 接受 seasonal 或 trend
        assert m.used_path in ("seasonal", "trend")
        d = m.predict()
        # mu 应在合理范围 (-5..25 之间, 季节性数据)
        assert -5.0 <= d.mu <= 25.0
        # 实际我们的 dist clip 了 mu 到 >= 0
        assert d.mu >= 0.0

    def test_constant_history_predicts_constant(self) -> None:
        m = self._new()
        history = [10.0] * 30
        m.fit(history)
        d = m.predict()
        # 常数序列预测应接近 10
        assert 8.0 <= d.mu <= 12.0
        # sigma 应接近 0 (残差极小)
        assert d.sigma < 1.0

    def test_p98_geq_mu(self) -> None:
        """p98 = mu + 2.054·sigma, 必须 >= mu."""
        m = self._new()
        history = [float(i % 10) for i in range(30)]
        m.fit(history)
        d = m.predict()
        assert d.p98 >= d.mu

    def test_mu_clipped_nonneg(self) -> None:
        """业务量非负, 即使 HW 预测出负值也 clip 到 0."""
        m = self._new()
        # 强下降趋势, 可能预测负
        history = [10.0 - 0.3 * i for i in range(30)]
        m.fit(history)
        d = m.predict()
        assert d.mu >= 0.0

    def test_refit_overrides(self) -> None:
        m = self._new()
        m.fit([float(i) for i in range(30)])
        m.fit([5.0] * 30)
        # 第二次 fit 状态应替换第一次
        assert m.used_path in ("trend", "mean")
        d = m.predict()
        assert 4.0 <= d.mu <= 6.0


class RefreshForecastOutputTests(unittest.TestCase):
    """§3.7 refresh_forecast_output: 全量 SKU 写 forecast_output 表."""

    # DB 隔离由 conftest autouse _isolate_db 负责（unified engine 指向 tmp db_path）

    def _seed_retail(self, barcode: str, weeks: int = 30, qty: int = 5) -> None:
        from datetime import date, timedelta

        from sqlalchemy import insert

        from app.models import InventoryEvent, Stockpile
        from app.repositories import stockpile_db

        with stockpile_db._session() as s:
            s.execute(
                insert(Stockpile).values(
                    product_barcode=barcode,
                    product_model=barcode,
                    stockpile_location="",
                    is_active=1,
                )
            )
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

    def test_writes_row_for_retail_sku(self) -> None:
        from datetime import date

        from sqlalchemy import select

        from app.models import ForecastOutput
        from app.repositories import stockpile_db
        from app.services.forecast import refresh_forecast_output

        self._seed_retail("B1", weeks=30)
        result = refresh_forecast_output(end_date=date(2026, 5, 13), barcodes=["B1"])

        assert result["n_total"] == 1
        assert result["n_written"] == 1
        assert result["n_skipped"] == 0

        with stockpile_db._session() as s:
            row = s.execute(
                select(ForecastOutput).where(ForecastOutput.product_barcode == "B1")
            ).scalar_one()
            assert row.model_used == "EmpiricalQuantile"
            assert row.sku_type == "retail_dominant"
            assert row.n_weeks_history > 0
            assert row.p98 >= row.p50

    def test_writes_confidence_inputs(self) -> None:
        """第1期③: refresh 顺手写 nonzero_weeks / zero_weeks_last8。

        连续 30 周每周有量 → nonzero_weeks > 0 且最近 8 周无零需求 → zero_weeks_last8 == 0。
        """
        from datetime import date

        from sqlalchemy import select

        from app.models import ForecastOutput
        from app.repositories import stockpile_db
        from app.services.forecast import refresh_forecast_output

        self._seed_retail("B1", weeks=30, qty=5)
        refresh_forecast_output(end_date=date(2026, 5, 13), barcodes=["B1"])

        with stockpile_db._session() as s:
            row = s.execute(
                select(ForecastOutput).where(ForecastOutput.product_barcode == "B1")
            ).scalar_one()
            assert row.nonzero_weeks > 0
            assert row.nonzero_weeks <= row.n_weeks_history
            assert row.zero_weeks_last8 == 0

    def test_upsert_replaces_previous_row(self) -> None:
        from datetime import date

        from sqlalchemy import select

        from app.models import ForecastOutput
        from app.repositories import stockpile_db
        from app.services.forecast import refresh_forecast_output

        self._seed_retail("B1", weeks=30, qty=5)
        refresh_forecast_output(end_date=date(2026, 5, 13), barcodes=["B1"])
        refresh_forecast_output(end_date=date(2026, 5, 13), barcodes=["B1"])

        with stockpile_db._session() as s:
            rows = s.execute(
                select(ForecastOutput).where(ForecastOutput.product_barcode == "B1")
            ).all()
            assert len(rows) == 1

    def test_skips_sku_with_no_history(self) -> None:
        from datetime import date

        from sqlalchemy import insert, select

        from app.models import ForecastOutput, Stockpile
        from app.repositories import stockpile_db
        from app.services.forecast import refresh_forecast_output

        with stockpile_db._session() as s:
            s.execute(
                insert(Stockpile).values(
                    product_barcode="EMPTY",
                    product_model="EMPTY",
                    stockpile_location="",
                    is_active=1,
                )
            )
            s.commit()

        result = refresh_forecast_output(end_date=date(2026, 5, 13), barcodes=["EMPTY"])
        assert result["n_written"] == 0
        assert result["n_skipped"] == 1
        with stockpile_db._session() as s:
            rows = s.execute(select(ForecastOutput)).all()
            assert rows == []


if __name__ == "__main__":
    unittest.main()
