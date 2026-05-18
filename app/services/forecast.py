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

import numpy as np

from app.services.backtest import ForecastDist


def _zero_dist() -> ForecastDist:
    return ForecastDist(mu=0.0, sigma=0.0, p50=0.0, p98=0.0)


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
