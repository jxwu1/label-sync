"""预测置信度分层纯函数契约 (第1期任务③).

用户 2026-06-05 定的规则:
  高 = history_weeks>=52 AND nonzero_weeks>=12 AND MASE<1.0 AND coverage_p98>=0.95
  中 = history_weeks>=26 AND nonzero_weeks>=6  AND MASE<1.2
  低 = 其余
  降级: zero_weeks_last8>=6 → 降一级 (近期零需求偏多, 信号不可靠)
  无 backtest metrics(MASE/coverage 不可算) → 直接 low + reason 'missing_backtest'
返回 ConfidenceResult(tier, reasons)。

注意命名: 用 recent_zero_demand 而非"断货"——没有库存快照证明不了 stockout。
"""

import math

from app.services.forecast_eval import (
    ConfidenceResult,
    confidence_tier,
    demand_history_stats,
)


class TestDemandHistoryStats:
    def test_all_nonzero_no_recent_zero(self):
        nonzero, zero8 = demand_history_stats([5.0] * 30)
        assert nonzero == 30
        assert zero8 == 0

    def test_recent_zeros_counted(self):
        # 20 周有量 + 最近 8 周全 0
        nonzero, zero8 = demand_history_stats([5.0] * 20 + [0.0] * 8)
        assert nonzero == 20
        assert zero8 == 8

    def test_only_last8_window_for_recent(self):
        # 早期的 0 不算进 last8; 最近 8 周 = [3,0,0,5,0,0,1,0] -> <=0 有 5 个
        series = [0.0] * 10 + [5.0] * 5 + [3.0, 0.0, 0.0, 5.0, 0.0, 0.0, 1.0, 0.0]
        nonzero, zero8 = demand_history_stats(series)
        assert zero8 == 5

    def test_negative_counts_as_zero_demand(self):
        # 退货归并后理论不出现负, 但 <=0 都算"无正需求"
        nonzero, zero8 = demand_history_stats([-2.0, 5.0, 0.0])
        assert nonzero == 1  # 只有 5.0 > 0
        assert zero8 == 2  # -2 和 0 都 <=0

    def test_short_series_uses_available_length(self):
        nonzero, zero8 = demand_history_stats([5.0, 0.0, 5.0])
        assert nonzero == 2
        assert zero8 == 1

    def test_empty_series(self):
        assert demand_history_stats([]) == (0, 0)


def _r(**kw):
    base = dict(
        history_weeks=60,
        nonzero_weeks=20,
        mase=0.8,
        coverage_p98=0.97,
        zero_weeks_last8=0,
    )
    base.update(kw)
    return confidence_tier(**base)


def test_high_when_all_gates_pass():
    res = _r()
    assert isinstance(res, ConfidenceResult)
    assert res.tier == "high"


def test_high_boundary_inclusive():
    # 边界: hist=52, nz=12, mase=0.99(<1.0), cov=0.95(>=0.95) → 仍 high
    assert _r(history_weeks=52, nonzero_weeks=12, mase=0.99, coverage_p98=0.95).tier == "high"


def test_medium_when_history_or_mase_between():
    assert _r(history_weeks=30, nonzero_weeks=8, mase=1.1, coverage_p98=0.90).tier == "medium"


def test_mase_exactly_1_0_drops_to_medium():
    # mase=1.0 不满足 high 的 <1.0, 但满足 medium 的 <1.2
    assert _r(history_weeks=60, nonzero_weeks=20, mase=1.0, coverage_p98=0.97).tier == "medium"


def test_low_when_mase_too_high():
    res = _r(history_weeks=60, nonzero_weeks=20, mase=1.5, coverage_p98=0.97)
    assert res.tier == "low"
    assert any("mase" in r for r in res.reasons)


def test_low_when_history_too_short():
    assert _r(history_weeks=20, nonzero_weeks=20, mase=0.8, coverage_p98=0.97).tier == "low"


def test_low_when_nonzero_too_sparse():
    # nonzero<6 → 连 medium 的门槛都不到 → low
    assert _r(history_weeks=60, nonzero_weeks=4, mase=0.8, coverage_p98=0.97).tier == "low"


def test_missing_mase_is_low_with_reason():
    res = _r(mase=None)
    assert res.tier == "low"
    assert res.reasons == ["missing_backtest"]


def test_missing_coverage_is_low_with_reason():
    res = _r(coverage_p98=None)
    assert res.tier == "low"
    assert res.reasons == ["missing_backtest"]


def test_nan_mase_treated_as_missing():
    res = _r(mase=math.nan)
    assert res.tier == "low"
    assert res.reasons == ["missing_backtest"]


def test_downgrade_high_to_medium_on_recent_zero_demand():
    res = _r(zero_weeks_last8=6)  # 其余满足 high
    assert res.tier == "medium"
    assert any("recent_zero_demand" in r for r in res.reasons)


def test_downgrade_medium_to_low():
    res = _r(history_weeks=30, nonzero_weeks=8, mase=1.1, coverage_p98=0.90, zero_weeks_last8=7)
    assert res.tier == "low"
    assert any("recent_zero_demand" in r for r in res.reasons)


def test_no_downgrade_below_threshold():
    # zero_weeks_last8=5 < 6 → 不降级, high 保持
    assert _r(zero_weeks_last8=5).tier == "high"


def test_downgrade_floor_at_low():
    # 已 low + 近期零需求多 → 仍 low, 但带上 reason
    res = _r(history_weeks=20, mase=1.5, zero_weeks_last8=6)
    assert res.tier == "low"
    assert any("recent_zero_demand" in r for r in res.reasons)
