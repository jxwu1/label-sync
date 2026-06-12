"""补货数值不变量 property 测试 — hypothesis 随机轰炸纯函数层。

与 test_replenishment_redlines.py 的分工：红线测试 = 手算预期值的确定性
样例（每条 RL 一组）；本文件 = 同一批不变量在整个输入空间上的随机验证，
专防"样例点正确、边界点崩"的回归。只测纯函数，不碰 DB。

输入前置条件（与生产一致）：
- 周销量序列非负 —— EmpiricalQuantileModel 文档声明"不裁剪负值，上游
  base_demand_view 已清洗"，故生成器只产非负值。给模型喂负值不是这里
  要守的不变量，是上游清洗层的失职。
- RL-1 的"horizon_q ≤ 周分位 × H"在数学上**不是普适定理**（分位数不次可加，
  VaR 反例：极端间歇序列的经验周分位被插值压到 0 时，bootstrap 和分位反而
  更大——且更正确）。故本文件只断言普适成立的不变量，线性放大对比留在
  红线测试的受控样例里。
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.analytics.restock_calc import (
    _churn_gate,
    _compute_urgency_score,
    _restock_recommendation,
    _round_up_to_pack,
)
from app.services.backtest import CrostonSBA
from app.services.forecast import (
    EmpiricalQuantileModel,
    _dist_from_mu_sigma,
    horizon_quantile,
)

# 周销量：间歇为主（一半概率 0），偶发大单
_week_value = st.one_of(
    st.just(0.0),
    st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
)
_history = st.lists(_week_value, min_size=0, max_size=60)
_history_nonempty = st.lists(_week_value, min_size=1, max_size=60)


# ──────────────────────────────────────────────────────────────────────
# _round_up_to_pack — RL-5.4/5.5
# ──────────────────────────────────────────────────────────────────────


@settings(deadline=None)
@given(
    qty=st.integers(min_value=1, max_value=100_000), pack=st.integers(min_value=2, max_value=200)
)
def test_pack_rounding_bounds_and_divisibility(qty: int, pack: int) -> None:
    rounded = _round_up_to_pack(qty, pack)
    assert rounded % pack == 0
    assert 0 <= rounded - qty < pack  # 只向上，且增量 < 1 个中包


@settings(deadline=None)
@given(
    qty=st.one_of(st.none(), st.integers(min_value=-100, max_value=100_000)),
    pack=st.one_of(st.none(), st.integers(min_value=-5, max_value=1)),
)
def test_pack_rounding_identity_when_pack_invalid(qty: int | None, pack: int | None) -> None:
    assert _round_up_to_pack(qty, pack) == qty  # pack ∈ {None, ≤1} 恒等


# ──────────────────────────────────────────────────────────────────────
# ForecastDist 构造 — RL-5.1/5.2
# ──────────────────────────────────────────────────────────────────────


@settings(deadline=None)
@given(
    mu=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    sigma=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_dist_from_mu_sigma_invariants(mu: float, sigma: float) -> None:
    d = _dist_from_mu_sigma(mu, sigma)
    assert d.mu >= 0 and d.sigma >= 0 and d.p50 >= 0 and d.p98 >= 0
    assert d.p50 <= d.p98


@settings(deadline=None)
@given(history=_history)
def test_empirical_model_invariants(history: list[float]) -> None:
    m = EmpiricalQuantileModel()
    m.fit(history)
    d = m.predict()
    assert d.mu >= 0 and d.sigma >= 0
    assert 0 <= d.p50 <= d.p98
    if history:
        assert d.p98 <= max(history) + 1e-9  # 经验分位 + 收缩都不会超过历史最大值


@settings(deadline=None)
@given(history=st.lists(_week_value, min_size=2, max_size=29))
def test_empirical_model_short_series_shrinkage(history: list[float]) -> None:
    """RL-4：< 30 周时收缩估计不得高于纯经验 p98（收缩只能往下）。"""
    import numpy as np

    m = EmpiricalQuantileModel()
    m.fit(history)
    assert m.predict().p98 <= float(np.quantile(np.asarray(history), 0.98)) + 1e-9


@settings(deadline=None)
@given(history=_history)
def test_croston_sba_invariants(history: list[float]) -> None:
    m = CrostonSBA()
    m.fit(history)
    d = m.predict()
    assert d.mu >= 0 and d.sigma >= 0
    assert 0 <= d.p50 <= d.p98


# ──────────────────────────────────────────────────────────────────────
# horizon_quantile — RL-1（普适不变量部分）
# ──────────────────────────────────────────────────────────────────────


@settings(deadline=None)
@given(
    history=_history_nonempty,
    horizon=st.integers(min_value=1, max_value=13),
    q=st.sampled_from([0.5, 0.9, 0.98]),
)
def test_horizon_quantile_bounded_by_support(history: list[float], horizon: int, q: float) -> None:
    hq = horizon_quantile(history, horizon, q)
    assert horizon * min(history) - 1e-6 <= hq <= horizon * max(history) + 1e-6


@settings(deadline=None)
@given(history=_history_nonempty, horizon=st.integers(min_value=1, max_value=13))
def test_horizon_quantile_monotonic_in_q(history: list[float], horizon: int) -> None:
    assert (
        horizon_quantile(history, horizon, 0.5)
        <= horizon_quantile(history, horizon, 0.9)
        <= horizon_quantile(history, horizon, 0.98)
    )


@settings(deadline=None)
@given(history=_history_nonempty, horizon=st.integers(min_value=1, max_value=13))
def test_horizon_quantile_deterministic(history: list[float], horizon: int) -> None:
    assert horizon_quantile(history, horizon, 0.98) == horizon_quantile(history, horizon, 0.98)


@settings(deadline=None)
@given(
    c=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    n=st.integers(min_value=1, max_value=40),
    horizon=st.integers(min_value=1, max_value=13),
)
def test_horizon_quantile_constant_series_exact(c: float, n: int, horizon: int) -> None:
    assert math.isclose(
        horizon_quantile([c] * n, horizon, 0.98), horizon * c, rel_tol=1e-9, abs_tol=1e-9
    )


@settings(deadline=None)
@given(horizon=st.integers(min_value=-3, max_value=0))
def test_horizon_quantile_degenerate_inputs(horizon: int) -> None:
    assert horizon_quantile([], 5, 0.98) == 0.0
    assert horizon_quantile([1.0, 2.0], horizon, 0.98) == 0.0


# ──────────────────────────────────────────────────────────────────────
# _churn_gate — RL-8
# ──────────────────────────────────────────────────────────────────────


@settings(deadline=None)
@given(
    qty=st.integers(min_value=-10, max_value=10_000),
    s_level=st.integers(min_value=0, max_value=10_000),
    stock=st.integers(min_value=-100, max_value=10_000),
    pack=st.one_of(st.none(), st.integers(min_value=1, max_value=100)),
)
def test_churn_gate_passthrough_or_zero(
    qty: int, s_level: int, stock: int, pack: int | None
) -> None:
    out = _churn_gate(qty, s_level, stock, pack)
    assert out in (0, qty)  # 闸只放行或归零，绝不修改数值
    if qty > 0 and stock <= 0 and s_level > 0:
        assert out == qty  # 断货必触发，不许被阈值压住（死亡螺旋保护）
    if qty <= 0:
        assert out == 0


# ──────────────────────────────────────────────────────────────────────
# _restock_recommendation — RL-2/5/6/7/8 组合不变量
# ──────────────────────────────────────────────────────────────────────

_fc_pair = st.tuples(
    st.floats(min_value=0.0, max_value=5_000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=5_000.0, allow_nan=False, allow_infinity=False),
).map(lambda t: (min(t), max(t)))  # 保证 p50_h ≤ p98_h（上游 RL-5 已保证）


@st.composite
def _restock_inputs(draw):
    p50_h, p98_h = draw(_fc_pair)
    has_fc = draw(st.booleans())
    return dict(
        barcode="B",
        qty_total=draw(st.integers(min_value=-1_000, max_value=20_000)),
        weekly_velocity=draw(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
        ),
        forecast_by_bc={"B": (p50_h, p98_h, "EmpiricalQuantile", 0)} if has_fc else {},
        last_purchase_qty_by_bc=draw(
            st.one_of(
                st.just({}), st.fixed_dictionaries({"B": st.integers(min_value=1, max_value=5_000)})
            )
        ),
        middle_qty=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=50))),
        on_order=draw(st.integers(min_value=0, max_value=20_000)),
    )


@settings(deadline=None, max_examples=300)
@given(kw=_restock_inputs())
def test_restock_recommendation_invariants(kw: dict) -> None:
    out = _restock_recommendation(**kw)
    q50, q98 = out["restock_qty_p50"], out["restock_qty_p98"]
    # 非负（None = 无数据，允许）
    assert q50 is None or q50 >= 0
    assert q98 is None or q98 >= 0
    # 分位单调：p50 档推荐不得超过 p98 档（凑整、闸后仍须成立）
    if q50 is not None and q98 is not None:
        assert q50 <= q98
    # 凑整：正推荐必须是中包整数倍
    pack = kw["middle_qty"]
    if pack and pack > 1:
        for q in (q50, q98):
            if q:
                assert q % pack == 0
    # RL-6 闸只标记不截断：flag 蕴含 qty_p98 > cap —— 若有人加了截断该断言恒假
    if out["sanity_flag"] is not None:
        last_pq = kw["last_purchase_qty_by_bc"].get("B")
        assert last_pq is not None
        assert q98 > max(last_pq * 3, (pack or 1) * 10)


@settings(deadline=None)
@given(kw=_restock_inputs())
def test_restock_negative_stock_equals_zero_stock(kw: dict) -> None:
    """RL-7：ERP 超卖（负库存）按 0 计 —— 负库存输入与 0 库存输出完全一致。"""
    if kw["qty_total"] >= 0:
        kw["qty_total"] = -kw["qty_total"] - 1  # 强制负值
    neg = _restock_recommendation(**kw)
    zero = _restock_recommendation(**{**kw, "qty_total": 0})
    assert neg == zero


@settings(deadline=None, max_examples=300)
@given(kw=_restock_inputs(), extra=st.integers(min_value=0, max_value=20_000))
def test_restock_on_order_covers_gap(kw: dict, extra: int) -> None:
    """RL-2：在途量足够覆盖 S 时推荐必须为 0（杜绝重复下单）。"""
    fc = kw["forecast_by_bc"].get("B")
    if not fc:
        return
    kw["on_order"] = math.ceil(fc[1]) + extra  # 在途 ≥ ceil(p98_h) ≥ S
    out = _restock_recommendation(**kw)
    assert out["restock_qty_p98"] == 0
    assert out["restock_qty_p50"] == 0


@settings(deadline=None)
@given(kw=_restock_inputs())
def test_restock_stockout_always_recommends(kw: dict) -> None:
    """RL-8 断货 override：无库存无在途且有需求 → 推荐必须 > 0，不许被反震荡闸吃掉。"""
    fc = kw["forecast_by_bc"].get("B")
    if not fc or fc[0] < 1.0:
        return
    kw["qty_total"] = 0
    kw["on_order"] = 0
    out = _restock_recommendation(**kw)
    assert out["restock_qty_p50"] and out["restock_qty_p50"] > 0
    assert out["restock_qty_p98"] and out["restock_qty_p98"] > 0


# ──────────────────────────────────────────────────────────────────────
# 紧迫分 — 分数有界
# ──────────────────────────────────────────────────────────────────────


@settings(deadline=None)
@given(
    velocity_pctile=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
    weeks_of_cover=st.one_of(
        st.none(),
        st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    ),
    last_purchase_days=st.one_of(st.none(), st.integers(min_value=0, max_value=10_000)),
    margin_pctile=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
    n_active_weeks=st.integers(min_value=0, max_value=26),
)
def test_urgency_score_bounded(
    velocity_pctile, weeks_of_cover, last_purchase_days, margin_pctile, n_active_weeks
) -> None:
    out = _compute_urgency_score(
        velocity_pctile=velocity_pctile,
        weeks_of_cover=weeks_of_cover,
        last_purchase_days=last_purchase_days,
        margin_pctile=margin_pctile,
        n_active_weeks=n_active_weeks,
    )
    assert 0.0 <= out["total"] <= 100.0
    assert 0.0 <= out["velocity"] <= 30.0
    assert 0.0 <= out["cover"] <= 30.0  # 负 weeks_of_cover（超卖）不得让分数溢出
    assert 0.0 <= out["recency"] <= 10.0
    assert 0.0 <= out["margin"] <= 30.0


@settings(deadline=None)
@given(n_active_weeks=st.integers(min_value=0, max_value=26))
def test_urgency_score_new_item_is_none(n_active_weeks: int) -> None:
    out = _compute_urgency_score(
        velocity_pctile=0.9,
        weeks_of_cover=0.0,
        last_purchase_days=400,
        margin_pctile=0.9,
        is_new_item=True,
        n_active_weeks=n_active_weeks,
    )
    assert out["total"] is None
