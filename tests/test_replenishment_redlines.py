"""补货数值红线测试 — 逐条对应 docs/adr/replenishment-redlines.md。

两类测试：
- [守住] RL-5 / RL-7：当前行为正确，测试**现在就跑**，防回退。
- [修复] RL-1/2/3/4/6/8/9：按修复后接口写好（接口定义见
  docs/superpowers/plans/2026-06-11-replenishment-correctness.md），标 skip，
  实施对应 Task 时解除 skip 作为验收。

预期值均为手算/可复算的合成数据，与生产数据无关。
"""

from __future__ import annotations

import math

import pytest

from app.services.analytics.restock_calc import (
    _compute_urgency_score,
    _restock_recommendation,
    _round_up_to_pack,
)
from app.services.forecast import EmpiricalQuantileModel, _dist_from_mu_sigma

# ──────────────────────────────────────────────────────────────────────
# RL-5 [守住] 输出不变量 — 非负与分位单调（live，现在就跑）
# ──────────────────────────────────────────────────────────────────────


class TestRL5DistInvariants:
    def test_rl5_dist_negative_mu_clamped(self):
        d = _dist_from_mu_sigma(-5.0, 2.0)
        assert d.mu == 0.0
        assert d.p50 == 0.0
        assert d.p98 >= 0.0

    def test_rl5_dist_negative_sigma_clamped(self):
        d = _dist_from_mu_sigma(3.0, -1.0)
        assert d.sigma == 0.0
        assert d.p98 == d.p50  # sigma=0 → p98 = mu

    def test_rl5_dist_quantile_monotonic(self):
        d = _dist_from_mu_sigma(3.0, 2.0)
        assert 0.0 <= d.p50 <= d.p98

    def test_rl5_empirical_model_invariants(self):
        m = EmpiricalQuantileModel()
        m.fit([0.0, 0.0, 3.0, 1.0, 4.0, 0.0, 15.0, 2.0, 0.0, 5.0, 0.0, 1.0, 7.0])
        d = m.predict()
        assert d.mu >= 0.0
        assert d.sigma >= 0.0
        assert 0.0 <= d.p50 <= d.p98

    def test_rl5_empirical_model_empty_history(self):
        m = EmpiricalQuantileModel()
        m.fit([])
        d = m.predict()
        assert (d.mu, d.sigma, d.p50, d.p98) == (0.0, 0.0, 0.0, 0.0)


class TestRL5PackRounding:
    @pytest.mark.parametrize(
        ("qty", "pack", "expected"),
        [
            (10, 12, 12),  # 向上凑到 1 包
            (12, 12, 12),  # 恰好整包不变
            (13, 12, 24),  # 超 1 件凑到 2 包
            (0, 12, 0),  # 0 不凑（不会无中生有）
            (None, 12, None),  # None 透传
            (10, None, 10),  # 无中包恒等
            (10, 0, 10),  # pack=0 恒等
            (10, 1, 10),  # pack=1 恒等
        ],
    )
    def test_rl5_pack_rounding_bounds(self, qty, pack, expected):
        assert _round_up_to_pack(qty, pack) == expected

    @pytest.mark.parametrize("qty", [1, 5, 11, 13, 25, 999])
    @pytest.mark.parametrize("pack", [2, 6, 12, 100])
    def test_rl5_pack_rounding_property(self, qty, pack):
        """凑整只向上，且增量 < 1 个中包。"""
        r = _round_up_to_pack(qty, pack)
        assert qty <= r < qty + pack
        assert r % pack == 0


class TestRL5RecommendationInvariants:
    def test_rl5_recommendation_monotonic_and_nonneg(self):
        """qty_p50 ≤ qty_p98 且均非负 — 只断言不变量，不绑定具体聚合公式。"""
        rec = _restock_recommendation(
            barcode="1234567890123",
            qty_total=10,
            weekly_velocity=2.0,
            forecast_by_bc={"1234567890123": (5.0, 20.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={},
            middle_qty=12,
        )
        assert rec["restock_qty_p50"] is not None
        assert rec["restock_qty_p98"] is not None
        assert 0 <= rec["restock_qty_p50"] <= rec["restock_qty_p98"]

    def test_rl5_overstocked_sku_recommends_zero(self):
        """库存远超需求 → 推荐 0，绝不为负。"""
        rec = _restock_recommendation(
            barcode="1234567890123",
            qty_total=10_000,
            weekly_velocity=1.0,
            forecast_by_bc={"1234567890123": (1.0, 3.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={},
            middle_qty=None,
        )
        assert rec["restock_qty_p50"] == 0
        assert rec["restock_qty_p98"] == 0


# ──────────────────────────────────────────────────────────────────────
# RL-7 [守住] 负库存（ERP 超卖）按 0 计（live，现在就跑）
# ──────────────────────────────────────────────────────────────────────


class TestRL7NegativeStock:
    def test_rl7_negative_stock_clamped(self):
        """weeks_of_cover < 0（超卖）与 = 0（无库存）必须同分 — cover 满分口径。"""
        kwargs = dict(
            velocity_pctile=0.5,
            last_purchase_days=30,
            margin_pctile=0.5,
            is_new_item=False,
            n_active_weeks=10,
        )
        neg = _compute_urgency_score(weeks_of_cover=-2.0, **kwargs)
        zero = _compute_urgency_score(weeks_of_cover=0.0, **kwargs)
        assert neg["cover"] == zero["cover"]
        assert neg["total"] == zero["total"]

    def test_rl7_score_bounded(self):
        """紧迫分恒在 [0, 100]。"""
        full = _compute_urgency_score(
            velocity_pctile=1.0,
            weeks_of_cover=0.0,
            last_purchase_days=99999,
            margin_pctile=1.0,
            is_new_item=False,
            n_active_weeks=52,
        )
        assert 0.0 <= full["total"] <= 100.0


# ──────────────────────────────────────────────────────────────────────
# RL-1 [修复] 跨期聚合 — bootstrap 和分位数取代 周分位 × N
# 接口（plan Task 1）: app/services/forecast.py::horizon_quantile(
#     history: list[float], horizon_weeks: int, q: float,
#     n_boot: int = 2000, seed: int = 42) -> float
# ──────────────────────────────────────────────────────────────────────

_INTERMITTENT_52W = [0.0, 0.0, 0.0, 20.0] * 13  # 75% 零周 + 13 笔 20 件大单


class TestRL1HorizonQuantile:
    def test_rl1_horizon_quantile_below_linear_scaling(self):
        from app.services.forecast import horizon_quantile

        # 周 p98 ≈ 20（spike 值）；线性放大 = 20×8 = 160。
        # 8 周和 ~ 20 × Binomial(8, 0.25)：均值 40，p98 ≈ 100。
        h_q98 = horizon_quantile(_INTERMITTENT_52W, horizon_weeks=8, q=0.98)
        assert h_q98 < 160.0  # 必须严格低于线性放大
        assert 60.0 <= h_q98 <= 130.0  # 合理带（理论值 ≈ 100）

    def test_rl1_horizon_quantile_deterministic_with_seed(self):
        from app.services.forecast import horizon_quantile

        a = horizon_quantile(_INTERMITTENT_52W, horizon_weeks=8, q=0.98, seed=42)
        b = horizon_quantile(_INTERMITTENT_52W, horizon_weeks=8, q=0.98, seed=42)
        assert a == b

    def test_rl1_horizon_quantile_monotonic_in_q(self):
        from app.services.forecast import horizon_quantile

        q50 = horizon_quantile(_INTERMITTENT_52W, horizon_weeks=8, q=0.50)
        q98 = horizon_quantile(_INTERMITTENT_52W, horizon_weeks=8, q=0.98)
        assert 0.0 <= q50 <= q98

    def test_rl1_constant_series_exact(self):
        from app.services.forecast import horizon_quantile

        # 恒定序列无不确定性：任意分位的 8 周和恒等于 5×8=40。
        assert horizon_quantile([5.0] * 52, horizon_weeks=8, q=0.98) == 40.0

    def test_rl1_empty_history_zero(self):
        from app.services.forecast import horizon_quantile

        assert horizon_quantile([], horizon_weeks=8, q=0.98) == 0.0


# ──────────────────────────────────────────────────────────────────────
# RL-2 [修复] 在途扣减
# 接口（plan Task 3）: _restock_recommendation 增加 on_order: int = 0 参数，
# 推荐量 = max(0, ceil(horizon_q) − max(0, stock) − on_order)。
# app/services/purchase.py::on_order_by_barcode(session) -> dict[str, int]
# ──────────────────────────────────────────────────────────────────────


class TestRL2OnOrderNetting:
    def test_rl2_on_order_netting(self):
        # 缺口 = ceil(40) − 10 = 30；在途 50 ≥ 30 → 推荐 0
        rec = _restock_recommendation(
            barcode="1234567890123",
            qty_total=10,
            weekly_velocity=0.0,
            forecast_by_bc={"1234567890123": (40.0, 90.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={},
            middle_qty=None,
            on_order=50,
        )
        assert rec["restock_qty_p50"] == 0
        # p98 档: ceil(90) − 10 − 50 = 30
        assert rec["restock_qty_p98"] == 30

    @staticmethod
    def _seed_order(status: str, barcode: str, ordered: int, arrived: int) -> None:
        """seed 走 SQLAlchemy（禁裸 sqlite3，PG 腿要过）。"""
        from app.models import PurchaseOrder, PurchaseOrderLine
        from app.repositories import stockpile_db

        with stockpile_db._session() as s:
            po = PurchaseOrder(order_date="2026-06-01", status=status)
            po.lines.append(
                PurchaseOrderLine(product_barcode=barcode, qty_ordered=ordered, qty_arrived=arrived)
            )
            s.add(po)
            s.commit()

    def test_rl2_partial_arrival(self):
        """qty_ordered=100, qty_arrived=40 → 在途 60。"""
        from app.repositories import stockpile_db
        from app.services.purchase import on_order_by_barcode

        self._seed_order("placed", "1234567890123", 100, 40)
        with stockpile_db._session() as s:
            result = on_order_by_barcode(s)
        assert result["1234567890123"] == 60

    def test_rl2_void_orders_excluded(self):
        """status='void' / 'cancelled' 的单不计在途。"""
        from app.repositories import stockpile_db
        from app.services.purchase import on_order_by_barcode

        self._seed_order("void", "9999999999999", 200, 0)
        with stockpile_db._session() as s:
            result = on_order_by_barcode(s)
        assert "9999999999999" not in result

    def test_rl2_over_receipt_clamped(self):
        """qty_arrived > qty_ordered（超收）→ 该行在途按 0，不得为负。"""
        from app.repositories import stockpile_db
        from app.services.purchase import on_order_by_barcode

        self._seed_order("arrived", "8888888888888", 50, 70)
        with stockpile_db._session() as s:
            result = on_order_by_barcode(s)
        assert result.get("8888888888888", 0) == 0


# ──────────────────────────────────────────────────────────────────────
# RL-3 [修复] 缺货周剔除
# 接口（plan Task 4）: app/services/stockout.py::exclude_stockout_weeks(
#     series: dict[date, float], stockout: set[date]) -> dict[date, float]
# ──────────────────────────────────────────────────────────────────────


class TestRL3StockoutExclusion:
    def test_rl3_stockout_weeks_excluded_from_series(self):
        import datetime as dt

        from app.services.stockout import exclude_stockout_weeks

        def mon(s):
            return dt.date.fromisoformat(s)

        series = {
            mon("2026-05-04"): 4.0,
            mon("2026-05-11"): 6.0,
            mon("2026-05-18"): 0.0,  # 缺货周
            mon("2026-05-25"): 0.0,  # 真实零需求周（有货）
            mon("2026-06-01"): 5.0,
        }
        stockout = {mon("2026-05-18")}
        out = exclude_stockout_weeks(series, stockout)
        assert mon("2026-05-18") not in out  # 缺货周剔除
        assert out[mon("2026-05-25")] == 0.0  # 有货零销保留
        assert len(out) == 4

    def test_rl3_exclusion_raises_forecast(self):
        """剔除删失 0 后分位数只升不降。"""
        m_before = EmpiricalQuantileModel()
        m_before.fit([4.0, 6.0, 0.0, 0.0, 5.0] * 4)  # 含删失 0
        m_after = EmpiricalQuantileModel()
        m_after.fit([4.0, 6.0, 0.0, 5.0] * 4)  # 剔除缺货周后
        assert m_after.predict().p50 >= m_before.predict().p50
        assert m_after.predict().p98 >= m_before.predict().p98


# ──────────────────────────────────────────────────────────────────────
# RL-4 [修复] 短序列尾部收缩
# 接口（plan Task 5）: EmpiricalQuantileModel.fit 内生效 —
# len(history) < 30 时 p98 = min(经验p98, p90 × 1.5)
# ──────────────────────────────────────────────────────────────────────


class TestRL4ShortSeriesTail:
    def test_rl4_short_series_tail_shrinkage(self):
        # 13 周: 12 周卖 1 件 + 单笔 100 件大单。
        # 经验 p98 ≈ 76（被大单顶满）；p90 = 1.0 → 收缩后 p98 ≤ 1.5。
        m = EmpiricalQuantileModel()
        m.fit([1.0] * 12 + [100.0])
        assert m.predict().p98 <= 1.5 + 1e-9

    def test_rl4_long_series_uses_empirical(self):
        # ≥30 周不收缩：纯经验分位数。
        import numpy as np

        hist = [1.0] * 48 + [10.0, 10.0, 10.0, 10.0]  # 52 周
        m = EmpiricalQuantileModel()
        m.fit(hist)
        expected = float(np.quantile(np.asarray(hist), 0.98))
        assert math.isclose(m.predict().p98, expected, rel_tol=1e-9)

    def test_rl4_invariant_p50_le_p98(self):
        """收缩后单调性仍成立。"""
        m = EmpiricalQuantileModel()
        m.fit([0.0] * 10 + [50.0, 2.0, 3.0])
        d = m.predict()
        assert 0.0 <= d.p50 <= d.p98


# ──────────────────────────────────────────────────────────────────────
# RL-6 [守住→新增] 合理性上限闸
# 接口（plan Task 6）: 推荐 dict 增加 sanity_flag 字段；
# 阈值 = max(历史最大单次进货量 × 3, 中包 × 10)
# ──────────────────────────────────────────────────────────────────────


class TestRL6SanityGate:
    def test_rl6_sanity_flag_on_extreme_qty(self):
        rec = _restock_recommendation(
            barcode="1234567890123",
            qty_total=0,
            weekly_velocity=0.0,
            forecast_by_bc={"1234567890123": (600.0, 5000.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={"1234567890123": 800},  # 历史最大单次 800
            middle_qty=12,
        )
        # p98 档 5000 > max(800×3, 12×10) = 2400 → 标记
        assert rec["sanity_flag"] == "exceeds_historical_max"
        # 不截断：数值原样保留
        assert rec["restock_qty_p98"] >= 5000

    def test_rl6_no_flag_for_normal_qty(self):
        rec = _restock_recommendation(
            barcode="1234567890123",
            qty_total=10,
            weekly_velocity=2.0,
            forecast_by_bc={"1234567890123": (16.0, 40.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={"1234567890123": 100},
            middle_qty=None,
        )
        assert rec["sanity_flag"] is None


# ──────────────────────────────────────────────────────────────────────
# RL-8 [修复] 反震荡触发阈值
# 接口（plan Task 7）: 推荐计算加触发条件 —
# 触发 ⟺ S − IP ≥ max(1 中包, 0.25 × S) 或 (现库存 ≤ 0 且 S > 0)
# 不触发 → restock_qty_* = 0
# ──────────────────────────────────────────────────────────────────────


class TestRL8AntiChurn:
    def test_rl8_no_churn_below_threshold(self):
        # S(p98)=40, IP=38 → 缺口 2 < max(12, 10) → 不触发，推荐 0
        rec = _restock_recommendation(
            barcode="1234567890123",
            qty_total=38,
            weekly_velocity=0.5,
            forecast_by_bc={"1234567890123": (20.0, 40.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={},
            middle_qty=12,
        )
        assert rec["restock_qty_p98"] == 0

    def test_rl8_stockout_always_triggers(self):
        # 现库存 0 且 S > 0 → 无论缺口多小都触发
        rec = _restock_recommendation(
            barcode="1234567890123",
            qty_total=0,
            weekly_velocity=0.5,
            forecast_by_bc={"1234567890123": (3.0, 8.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={},
            middle_qty=12,
        )
        assert rec["restock_qty_p98"] > 0


# ──────────────────────────────────────────────────────────────────────
# RL-9 [监控] 预测过期检测（纯函数部分）
# 接口（plan Task 8）: app/services/forecast_eval.py::forecast_is_stale(
#     computed_at: str | None, today: date, max_age_days: int = 14) -> bool
# ──────────────────────────────────────────────────────────────────────


class TestRL9Staleness:
    def test_rl9_staleness_detection(self):
        import datetime as dt

        from app.services.forecast_eval import forecast_is_stale

        today = dt.date(2026, 6, 11)
        assert forecast_is_stale("2026-05-20 03:00:00", today) is True  # 22 天
        assert forecast_is_stale("2026-06-05 03:00:00", today) is False  # 6 天
        assert forecast_is_stale(None, today) is True  # 无记录 = 过期


# ──────────────────────────────────────────────────────────────────────
# ADR-0001 D4: lead time 先验 + 经验切换
# 接口（plan Task 5）: app/services/purchase.py::lead_time_weeks(session)
#     -> (weeks: int, source: 'prior'|'empirical', n_samples: int)
# ──────────────────────────────────────────────────────────────────────


class TestLeadTime:
    def test_prior_when_insufficient_samples(self):
        from app.repositories import stockpile_db
        from app.services.purchase import lead_time_weeks

        with stockpile_db._session() as s:
            weeks, source, _n = lead_time_weeks(s)
        assert source == "prior"
        assert weeks >= 1

    def test_empirical_p90_when_enough_samples(self):
        from app.models import PurchaseOrder
        from app.repositories import stockpile_db
        from app.services.purchase import lead_time_weeks

        with stockpile_db._session() as s:
            # 20 单：19 单 lead 21 天 + 1 单 70 天 → p90 = 21 天 → 3 周
            for _ in range(19):
                s.add(
                    PurchaseOrder(
                        order_date="2026-01-01", arrival_date="2026-01-22", status="arrived"
                    )
                )
            s.add(
                PurchaseOrder(order_date="2026-01-01", arrival_date="2026-03-12", status="arrived")
            )
            s.commit()
            weeks, source, n = lead_time_weeks(s)
        assert source == "empirical"
        assert n == 20
        assert weeks == 3


# ──────────────────────────────────────────────────────────────────────
# RL-10 [监控] 快照缺失周巡检
# ──────────────────────────────────────────────────────────────────────


class TestRL10MissingSnapshot:
    def test_rl10_missing_monday_snapshot_detected(self):
        import datetime as dt

        from app.models import StockpileInventorySnapshot
        from app.repositories import stockpile_db
        from app.services.alerts import _missing_monday_snapshots

        with stockpile_db._session() as s:
            # 种最旧周一的快照（绕过冷启动守卫），其余 3 个周一缺失。
            # as_of=周四 → 本周一(06-08)已过去，必须计入。
            s.add(
                StockpileInventorySnapshot(
                    snapshot_date="2026-05-18", product_model="M1", qty_total=5
                )
            )
            s.commit()
            missing = _missing_monday_snapshots(s, dt.date(2026, 6, 11), n_weeks=4)
        assert missing == ["2026-06-08", "2026-06-01", "2026-05-25"]

    def test_rl10_empty_table_cold_start_silent(self):
        import datetime as dt

        from app.repositories import stockpile_db
        from app.services.alerts import _missing_monday_snapshots

        with stockpile_db._session() as s:
            assert _missing_monday_snapshots(s, dt.date(2026, 6, 11)) == []
