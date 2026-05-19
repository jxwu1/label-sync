"""主力预测模型 (plan 阶段 3).

跟 baseline (backtest.py) 的区别:
- baseline 走 mu+z·sigma 正态近似 p98
- 这里的"主力"针对具体 SKU 类型做优化, 例如 EmpiricalQuantile 直接走经验分位数

模型实现 backtest.ForecastModel Protocol:
    name: str
    fit(history: list[float]) -> None
    predict(steps: int = 1) -> ForecastDist
"""

from __future__ import annotations

import warnings

import numpy as np

from app.services.backtest import ForecastDist

_Z98 = 2.054  # Φ⁻¹(0.98)


def _zero_dist() -> ForecastDist:
    return ForecastDist(mu=0.0, sigma=0.0, p50=0.0, p98=0.0)


def _dist_from_mu_sigma(mu: float, sigma: float) -> ForecastDist:
    s = max(0.0, sigma)
    mu_clipped = max(0.0, mu)  # 业务量非负
    return ForecastDist(
        mu=mu_clipped,
        sigma=s,
        p50=mu_clipped,
        p98=max(0.0, mu_clipped + _Z98 * s),
    )


class EmpiricalQuantileModel:
    """直接对历史取经验分位数 (p50 / p98).

    适用场景: wholesale_only / 间歇序列 / 偶发大单. 这类序列非正态, 用
    mu+z·sigma 正态近似会低估尾部 (0 周多拉低 mu/sigma, p98 被压); 直接
    quantile 反映真实尾部.

    设计取舍:
    - p50 = numpy.quantile(history, 0.5) ← 经验中位数, 不是 mu
    - p98 = numpy.quantile(history, 0.98) ← 经验 98 分位, 不走正态
    - mu/sigma 仍记录, 给 dashboard 等消费者
    - i.i.d. 假设, 多步 = 单步
    - 空 history → zero_dist
    - 单元素 → sigma=0
    - 不裁剪负值, 上游 base_demand_view 已清洗
    """

    name = "EmpiricalQuantile"

    def __init__(self) -> None:
        self._dist: ForecastDist = _zero_dist()

    def fit(self, history: list[float]) -> None:
        if not history:
            self._dist = _zero_dist()
            return

        arr = np.asarray(history, dtype=float)
        mu = float(arr.mean())
        sigma = float(arr.std()) if len(arr) > 1 else 0.0
        p50 = float(np.quantile(arr, 0.5))
        p98 = float(np.quantile(arr, 0.98))
        p98 = max(p98, 0.0)
        self._dist = ForecastDist(mu=mu, sigma=sigma, p50=p50, p98=p98)

    def predict(self, steps: int = 1) -> ForecastDist:
        return self._dist


class HoltWintersModel:
    """Holt-Winters 指数平滑 (plan 阶段 3.2).

    自动判断是否带季节项:
    - len(history) >= 104 周 (2 年) → 尝试 trend + 季节 (period=52)
    - 季节项收敛失败 → 回落到 trend-only (Holt's linear)
    - trend-only 也失败 → 回落到 mean (退化保护)
    - len(history) < 13 周 → zero_dist (太短不预测)

    σ 用历史残差 std (in-sample residuals), 不是原始序列 std (plan §3.4 细节).
    多步预测: 当前实现返回单步分布 (与其他 baseline 对齐); 真正的多步 HW
    forecast 留待框架支持多步评分时再上.
    """

    name = "HoltWinters"
    _SEASONAL_PERIOD = 52
    _MIN_FOR_SEASONAL = 104  # 至少 2 完整年度
    _MIN_FOR_FIT = 13

    def __init__(self) -> None:
        self._dist: ForecastDist = _zero_dist()
        self._used: str = "none"  # "seasonal" / "trend" / "mean" / "none"

    @property
    def used_path(self) -> str:
        """暴露给测试 / 调用方: 实际走了哪条 fit 分支."""
        return self._used

    def fit(self, history: list[float]) -> None:
        n = len(history)
        if n < self._MIN_FOR_FIT:
            self._dist = _zero_dist()
            self._used = "none"
            return

        arr = np.asarray(history, dtype=float)

        if n >= self._MIN_FOR_SEASONAL:
            res = self._try_fit_seasonal(arr)
            if res is not None:
                mu, sigma = res
                self._dist = _dist_from_mu_sigma(mu, sigma)
                self._used = "seasonal"
                return

        res = self._try_fit_trend(arr)
        if res is not None:
            mu, sigma = res
            self._dist = _dist_from_mu_sigma(mu, sigma)
            self._used = "trend"
            return

        # 退化: 用均值
        mu = float(arr.mean())
        sigma = float(arr.std()) if n > 1 else 0.0
        self._dist = _dist_from_mu_sigma(mu, sigma)
        self._used = "mean"

    def _try_fit_seasonal(self, arr: np.ndarray) -> tuple[float, float] | None:
        # statsmodels 各种收敛 warning, 测试期间会被 pytest 捕获 → 屏蔽
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                from statsmodels.tsa.holtwinters import ExponentialSmoothing

                model = ExponentialSmoothing(
                    arr,
                    trend="add",
                    seasonal="add",
                    seasonal_periods=self._SEASONAL_PERIOD,
                    initialization_method="estimated",
                ).fit(
                    optimized=True,
                    use_brute=False,
                    minimize_kwargs={"options": {"maxiter": 50}},
                )
                forecast = model.forecast(steps=1)
                mu = float(forecast[0])
                # σ 用 in-sample 残差; 比原始 std 更准
                resid = np.asarray(model.resid, dtype=float)
                sigma = float(resid.std()) if len(resid) > 1 else 0.0
                if not (np.isfinite(mu) and np.isfinite(sigma)):
                    return None
                return mu, sigma
            except Exception:
                return None

    def _try_fit_trend(self, arr: np.ndarray) -> tuple[float, float] | None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                from statsmodels.tsa.holtwinters import ExponentialSmoothing

                model = ExponentialSmoothing(
                    arr,
                    trend="add",
                    seasonal=None,
                    initialization_method="estimated",
                ).fit(
                    optimized=True,
                    use_brute=False,
                    minimize_kwargs={"options": {"maxiter": 50}},
                )
                forecast = model.forecast(steps=1)
                mu = float(forecast[0])
                resid = np.asarray(model.resid, dtype=float)
                sigma = float(resid.std()) if len(resid) > 1 else 0.0
                if not (np.isfinite(mu) and np.isfinite(sigma)):
                    return None
                return mu, sigma
            except Exception:
                return None

    def predict(self, steps: int = 1) -> ForecastDist:
        return self._dist
