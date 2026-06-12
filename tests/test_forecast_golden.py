"""数值黄金快照 — 锁定预测/补货核心链路在固定输入下的精确输出。

目的：防"重构数值漂移但常规断言全绿"。红线测试守不变量（非负/单调/有界），
本文件守**具体数值**：任何让这里变红的改动，要么是 bug，要么是有意的算法
变更 —— 后者必须在 PR 描述里解释数值为什么该变，再更新基线，二选一。

基线生成自 main@13f2404（2026-06-12）。纯函数 + 固定 seed，不碰 DB，
sqlite/PG 双腿、本地/CI 结果一致（numpy 确定性运算 + PCG64 固定种子）。
输入序列为合成数据，模拟三种典型 SKU 形态：稳定零售 / 短历史含异常大单 /
间歇批发。
"""

from __future__ import annotations

from app.services.analytics.restock_calc import _restock_recommendation
from app.services.backtest import CrostonSBA
from app.services.forecast import EmpiricalQuantileModel, horizon_quantile

# 稳定零售 SKU：40 周，周销 6-16，偶发缺货周 0
RETAIL_40W = [
    12.0,
    8.0,
    15.0,
    0.0,
    9.0,
    11.0,
    7.0,
    14.0,
    10.0,
    6.0,
    13.0,
    9.0,
    8.0,
    12.0,
    0.0,
    10.0,
    11.0,
    9.0,
    7.0,
    16.0,
    12.0,
    8.0,
    10.0,
    9.0,
    11.0,
    13.0,
    0.0,
    8.0,
    10.0,
    12.0,
    9.0,
    7.0,
    11.0,
    14.0,
    10.0,
    8.0,
    9.0,
    12.0,
    10.0,
    11.0,
]

# 短历史 SKU：15 周（< 30 触发 RL-4 收缩），含一笔 120 的异常大单
SHORT_15W = [5.0, 0.0, 8.0, 3.0, 0.0, 120.0, 4.0, 6.0, 0.0, 5.0, 7.0, 3.0, 4.0, 6.0, 5.0]

# 间歇批发 SKU：30 周，8 个非零周，单笔 60-200（ADR-0002 wholesale 形态）
INTERMITTENT_30W = [
    0.0,
    0.0,
    150.0,
    0.0,
    0.0,
    0.0,
    80.0,
    0.0,
    0.0,
    0.0,
    0.0,
    200.0,
    0.0,
    0.0,
    60.0,
    0.0,
    0.0,
    0.0,
    90.0,
    0.0,
    0.0,
    0.0,
    0.0,
    120.0,
    0.0,
    0.0,
    70.0,
    0.0,
    0.0,
    110.0,
]


def _fit_predict(model, series):
    model.fit(series)
    d = model.predict()
    return (round(d.mu, 4), round(d.sigma, 4), round(d.p50, 4), round(d.p98, 4))


class TestModelGolden:
    def test_empirical_quantile_retail_40w(self):
        # ≥30 周：纯经验分位数，无收缩
        assert _fit_predict(EmpiricalQuantileModel(), RETAIL_40W) == (9.525, 3.5213, 10.0, 15.22)

    def test_empirical_quantile_short_15w_shrinkage(self):
        # <30 周：RL-4 收缩生效 —— 经验 p98≈103（被 120 大单顶满）收缩到 p90×1.5=11.4
        assert _fit_predict(EmpiricalQuantileModel(), SHORT_15W) == (11.7333, 29.0344, 5.0, 11.4)

    def test_croston_sba_intermittent_30w(self):
        # SBA: size/interval EWMA + (1-α/2) 修正；p98 走 μ+z·σ 正态近似
        assert _fit_predict(CrostonSBA(), INTERMITTENT_30W) == (34.9537, 53.5993, 34.9537, 145.0467)


class TestHorizonQuantileGolden:
    """bootstrap(seed=42, n_boot=2000) 的和分位数。线性放大对比见各 case 注释。"""

    def test_retail_5w_p98(self):
        # 周 p98=15.22 线性放大 ×5=76.1；bootstrap 和分位 61.0（√N 律收缩）
        assert round(horizon_quantile(RETAIL_40W, 5, 0.98), 4) == 61.0

    def test_intermittent_5w_p50(self):
        assert round(horizon_quantile(INTERMITTENT_30W, 5, 0.5), 4) == 120.0

    def test_intermittent_5w_p98(self):
        assert round(horizon_quantile(INTERMITTENT_30W, 5, 0.98), 4) == 400.2

    def test_intermittent_13w_p98(self):
        assert round(horizon_quantile(INTERMITTENT_30W, 13, 0.98), 4) == 820.0


class TestRestockGolden:
    """_restock_recommendation 全字段快照。每个场景锁一条决策路径。"""

    def test_s1_forecast_with_on_order(self):
        # IP = 20 + 30 = 50；p50 档缺口 0；p98 档 95-50=45 过闸，凑整到 48（4×12）
        out = _restock_recommendation(
            barcode="B1",
            qty_total=20,
            weekly_velocity=5.0,
            forecast_by_bc={"B1": (40.0, 95.0, "EmpiricalQuantile", 1)},
            last_purchase_qty_by_bc={"B1": 60},
            middle_qty=12,
            on_order=30,
        )
        assert out == {
            "restock_qty_p50": 0,
            "restock_qty_p98": 48,
            "restock_source": "forecast:EmpiricalQuantile",
            "last_purchase_qty": 60,
            "forecast_p50": 40.0,
            "forecast_p98": 95.0,
            "stockout_zero_weeks_last8": 1,
            "on_order": 30,
            "sanity_flag": None,
        }

    def test_s2_oversold_stockout_override(self):
        # 负库存按 0 计（RL-7）；断货 override 让 2 件微小缺口绕过反震荡闸（RL-8）
        out = _restock_recommendation(
            barcode="B2",
            qty_total=-3,
            weekly_velocity=0.5,
            forecast_by_bc={"B2": (2.0, 6.0, "CrostonSBA", 2)},
            last_purchase_qty_by_bc={},
            middle_qty=10,
            on_order=0,
        )
        assert out == {
            "restock_qty_p50": 10,
            "restock_qty_p98": 10,
            "restock_source": "forecast:CrostonSBA",
            "last_purchase_qty": None,
            "forecast_p50": 2.0,
            "forecast_p98": 6.0,
            "stockout_zero_weeks_last8": 2,
            "on_order": 0,
            "sanity_flag": None,
        }

    def test_s3_velocity_fallback(self):
        # 无预测行 → 销速 ×8 周回退；IP = 5 + 8 = 13；p50: ceil(2.5×8)−13=7
        out = _restock_recommendation(
            barcode="B3",
            qty_total=5,
            weekly_velocity=2.5,
            forecast_by_bc={},
            last_purchase_qty_by_bc={"B3": 40},
            middle_qty=None,
            on_order=8,
        )
        assert out == {
            "restock_qty_p50": 7,
            "restock_qty_p98": 17,
            "restock_source": "velocity",
            "last_purchase_qty": 40,
            "forecast_p50": None,
            "forecast_p98": None,
            "stockout_zero_weeks_last8": 0,
            "on_order": 8,
            "sanity_flag": None,
        }

    def test_s4_churn_hold(self):
        # 缺口 1-2 件 < max(6, 0.25×S)（RL-8）且有库存 → 持有，显示 0
        out = _restock_recommendation(
            barcode="B4",
            qty_total=14,
            weekly_velocity=1.0,
            forecast_by_bc={"B4": (15.0, 16.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={"B4": 30},
            middle_qty=6,
            on_order=0,
        )
        assert out == {
            "restock_qty_p50": 0,
            "restock_qty_p98": 0,
            "restock_source": "forecast:EmpiricalQuantile",
            "last_purchase_qty": 30,
            "forecast_p50": 15.0,
            "forecast_p98": 16.0,
            "stockout_zero_weeks_last8": 0,
            "on_order": 0,
            "sanity_flag": None,
        }

    def test_s5_sanity_flag_not_truncated(self):
        # 900 > max(50×3, 1×10)=150 → 标记 exceeds_historical_max，数值不截断（RL-6）
        out = _restock_recommendation(
            barcode="B5",
            qty_total=0,
            weekly_velocity=10.0,
            forecast_by_bc={"B5": (500.0, 900.0, "EmpiricalQuantile", 0)},
            last_purchase_qty_by_bc={"B5": 50},
            middle_qty=None,
            on_order=0,
        )
        assert out == {
            "restock_qty_p50": 500,
            "restock_qty_p98": 900,
            "restock_source": "forecast:EmpiricalQuantile",
            "last_purchase_qty": 50,
            "forecast_p50": 500.0,
            "forecast_p98": 900.0,
            "stockout_zero_weeks_last8": 0,
            "on_order": 0,
            "sanity_flag": "exceeds_historical_max",
        }
