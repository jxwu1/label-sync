"""阶段 2 回测框架 — 算法层 (plan §2.1-2.4).

不依赖 DB; DB & API 层 (alembic / routes / 批量入口) 留待 PR6.

提供:
- ForecastDist 数据类 + ForecastModel Protocol (§2.1)
- 四个 baseline: NaiveMean4W / NaiveSeasonal52W / LinearTrend12W / CrostonSBA (§2.2)
- walk_forward_backtest 滚动训练/预测/收集 (§2.3)
- mape / mase / bias / coverage_p98 评分 (§2.4)

设计取舍:
- baselines 是点估计; p98 = max(0, mu + 2.054·sigma) 正态近似 (z=2.054 = Φ⁻¹(0.98))
- sigma 用训练残差 std
- 多步预测对 naive baselines 等于单步重复 (不做衰减), HW 阶段再做多步
- MAPE 对 actual=0 周剔除, 全零返回 None
- MASE 标准定义 (Hyndman & Koehler 2006): 逐窗用训练集 in-sample one-step
  naive MAE 做该窗 record 的分母, scaled error 跨全部窗聚合后平均
  (mase_from_records); 分母为 0 的窗剔除, 全部窗为 0 → None
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

_Z98 = 2.054  # Φ⁻¹(0.98)


@dataclass
class ForecastDist:
    mu: float
    sigma: float
    p50: float
    p98: float


class ForecastModel(Protocol):
    name: str

    def fit(self, history: list[float]) -> None: ...

    def predict(self, steps: int = 1) -> ForecastDist: ...


def _zero_dist() -> ForecastDist:
    return ForecastDist(mu=0.0, sigma=0.0, p50=0.0, p98=0.0)


def _dist_from_mu_sigma(mu: float, sigma: float) -> ForecastDist:
    s = max(0.0, sigma)
    return ForecastDist(mu=mu, sigma=s, p50=mu, p98=max(0.0, mu + _Z98 * s))


class NaiveMean4W:
    name = "NaiveMean4W"
    _W = 4

    def __init__(self) -> None:
        self._mu = 0.0
        self._sigma = 0.0
        self._empty = True

    def fit(self, history: list[float]) -> None:
        if not history:
            self._empty = True
            self._mu = self._sigma = 0.0
            return
        self._empty = False
        window = history[-self._W :]
        arr = np.asarray(window, dtype=float)
        self._mu = float(arr.mean())
        self._sigma = float(arr.std()) if len(arr) > 1 else 0.0

    def predict(self, steps: int = 1) -> ForecastDist:
        if self._empty:
            return _zero_dist()
        return _dist_from_mu_sigma(self._mu, self._sigma)


class NaiveSeasonal52W:
    name = "NaiveSeasonal52W"
    _LAG = 52

    def __init__(self) -> None:
        self._dist = _zero_dist()

    def fit(self, history: list[float]) -> None:
        if not history:
            self._dist = _zero_dist()
            return
        n = len(history)
        if n < self._LAG:
            mu = float(np.mean(history))
            sigma = float(np.std(history)) if n > 1 else 0.0
            self._dist = _dist_from_mu_sigma(mu, sigma)
            return
        mu = float(history[-self._LAG])
        residuals = np.asarray(history[self._LAG :], dtype=float) - np.asarray(
            history[: -self._LAG], dtype=float
        )
        sigma = float(residuals.std()) if len(residuals) > 1 else 0.0
        self._dist = _dist_from_mu_sigma(mu, sigma)

    def predict(self, steps: int = 1) -> ForecastDist:
        return self._dist


class LinearTrend12W:
    name = "LinearTrend12W"
    _W = 12

    def __init__(self) -> None:
        self._dist = _zero_dist()

    def fit(self, history: list[float]) -> None:
        if not history:
            self._dist = _zero_dist()
            return
        window = history[-self._W :]
        n = len(window)
        # 样本太少回归不稳, 退化为均值 baseline
        if n < 4:
            arr = np.asarray(window, dtype=float)
            sigma = float(arr.std()) if n > 1 else 0.0
            self._dist = _dist_from_mu_sigma(float(arr.mean()), sigma)
            return
        x = np.arange(n, dtype=float)
        y = np.asarray(window, dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        mu = float(slope * n + intercept)
        residuals = y - (slope * x + intercept)
        sigma = float(residuals.std())
        self._dist = _dist_from_mu_sigma(mu, sigma)

    def predict(self, steps: int = 1) -> ForecastDist:
        return self._dist


class CrostonSBA:
    """间歇需求 SBA (plan §2.2).

    forecast = size / interval × (1 - alpha/2); EWMA 更新.
    """

    name = "CrostonSBA"

    def __init__(self, alpha: float = 0.1) -> None:
        self.alpha = alpha
        self._dist = _zero_dist()

    def fit(self, history: list[float]) -> None:
        if not history:
            self._dist = _zero_dist()
            return
        arr = np.asarray(history, dtype=float)
        nz_idx = [i for i, v in enumerate(history) if v > 0]
        if not nz_idx:
            self._dist = _zero_dist()
            return

        size = float(history[nz_idx[0]])
        interval = float(nz_idx[0] + 1)
        prev = nz_idx[0]
        for idx in nz_idx[1:]:
            gap = float(idx - prev)
            obs = float(history[idx])
            size = self.alpha * obs + (1 - self.alpha) * size
            interval = self.alpha * gap + (1 - self.alpha) * interval
            prev = idx

        mu = (size / interval) * (1.0 - self.alpha / 2.0)
        residuals = arr - mu
        sigma = float(residuals.std()) if len(arr) > 1 else 0.0
        self._dist = _dist_from_mu_sigma(mu, sigma)

    def predict(self, steps: int = 1) -> ForecastDist:
        return self._dist


def walk_forward_backtest(
    series: list[float],
    model_cls: Callable[[], ForecastModel],
    window_train: int = 13,
    window_test: int = 4,
) -> list[dict]:
    """累积窗口回测 (expanding window).

    window_train 是**最小训练长度**, 不是固定窗口宽度. 每次 train 取
    series[:start+window_train], 累计扩张; 这样季节模型 (NaiveSeasonal52W
    需 ≥52w, HoltWinters 需 ≥104w) 在序列长度跨过阈值后能真正生效, 而不是
    永远 fallback 到均值. start 仍每次 +1, test 是下 window_test 周.
    """
    records: list[dict] = []
    n = len(series)
    if n < window_train + window_test:
        return records

    for start in range(n - window_train - window_test + 1):
        train_end = start + window_train
        train = series[:train_end]
        test = series[train_end : train_end + window_test]
        # 该窗训练集 in-sample one-step naive MAE (Hyndman & Koehler 2006 标准 MASE 分母)。
        # 用 train[:train_end] 而非展平 actual 序列, 杜绝跨窗跳变 / 同周重复 (审计 MT-1)。
        train_naive_mae = _in_sample_naive_mae(train)
        model = model_cls()
        model.fit(list(train))
        for h in range(1, window_test + 1):
            d = model.predict(steps=h)
            records.append(
                {
                    "step_idx": start + window_train + h - 1,
                    "horizon": h,
                    "predicted": float(d.mu),
                    "p50": float(d.p50),
                    "p98": float(d.p98),
                    "actual": float(test[h - 1]),
                    "train_naive_mae": train_naive_mae,
                }
            )
    return records


def _in_sample_naive_mae(train: list[float]) -> float | None:
    """训练集内 one-step naive 预测 (上一周) 的 MAE = mean(|train[i]-train[i-1]|).

    < 2 点或全常数 (差分全 0) → None (该窗无法标准化, 调用方剔除)。
    """
    if len(train) < 2:
        return None
    diffs = [abs(train[i] - train[i - 1]) for i in range(1, len(train))]
    mae = sum(diffs) / len(diffs)
    return mae if mae > 0 else None


def mape(actual: list[float], predicted: list[float]) -> float | None:
    if not actual:
        return None
    errs = [abs(a - p) / a for a, p in zip(actual, predicted, strict=False) if a != 0]
    if not errs:
        return None
    return float(sum(errs) / len(errs))


def bias(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    diffs = [p - a for a, p in zip(actual, predicted, strict=False)]
    return float(sum(diffs) / len(diffs))


def mase_from_records(records: list[dict]) -> float | None:
    """标准 MASE (Hyndman & Koehler 2006), expanding-window 逐窗标准化。

    每条 record 的 scaled error = |actual - predicted| / train_naive_mae(该窗)。
    train_naive_mae 为 None 的窗 (训练集常数 / <2 点) 整窗剔除;
    无任何可用 record → None (沿用旧 None 语义)。

    分母与模型无关, 故 6 模型相对排序不受影响 (审计 MT-1 预言)。
    """
    scaled: list[float] = []
    for r in records:
        denom = r.get("train_naive_mae")
        if denom is None or denom <= 0:
            continue
        scaled.append(abs(r["actual"] - r["predicted"]) / denom)
    if not scaled:
        return None
    return float(sum(scaled) / len(scaled))


def coverage_p98(actual: list[float], p98: list[float]) -> float:
    if not actual:
        return 0.0
    in_bound = sum(1 for a, hi in zip(actual, p98, strict=False) if a <= hi)
    return float(in_bound / len(actual))


# ---- §2.6 DB-aware 批量入口 -------------------------------------------------


def _empirical_quantile():
    from app.services.forecast import EmpiricalQuantileModel

    return EmpiricalQuantileModel()


def _holt_winters():
    from app.services.forecast import HoltWintersModel

    return HoltWintersModel()


# 4 baseline + 2 阶段 3 主力模型. 命名沿用 BASELINES 不改, 避免破坏 routes 入口校验
BASELINES: dict[str, Callable[[], ForecastModel]] = {
    "NaiveMean4W": NaiveMean4W,
    "NaiveSeasonal52W": NaiveSeasonal52W,
    "LinearTrend12W": LinearTrend12W,
    "CrostonSBA": CrostonSBA,
    "EmpiricalQuantile": _empirical_quantile,
    "HoltWinters": _holt_winters,
}


def _build_series(
    barcode: str,
    end_date,
    weeks: int,
    view: str,
    session=None,
) -> tuple[list[float], str, int] | None:
    """从 DB 拉单 SKU 周序列 + sku_type + 剔除的缺货周数. None = 不可回测.

    base_demand 视图剔除缺货周（RL-3 / ADR-0001 D7）；all 视图保留原始信号不剔。
    """
    from app.services.stockout import exclude_stockout_weeks, stockout_weeks
    from app.utils.categorizer import classify_sku_type
    from app.utils.forecast_data import base_demand_view, weekly_demand_series

    if view == "base_demand":
        v = base_demand_view(barcode, end_date, weeks, session=session)
        if v["series"] is None:
            return None
        so = stockout_weeks(barcode, end_date, weeks, session=session)
        kept = exclude_stockout_weeks(v["series"], so)
        n_excluded = len(v["series"]) - len(kept)
        return [kept[k] for k in sorted(kept)], v["sku_type"], n_excluded
    if view == "all":
        sku_type = classify_sku_type(barcode, session=session, as_of=end_date)
        if sku_type in ("unclassified", "dying"):
            return None
        d = weekly_demand_series(barcode, end_date, weeks, session=session)
        return [d[k] for k in sorted(d)], sku_type, 0
    raise ValueError(f"unknown view: {view}")


def run_backtest_for_sku(
    barcode: str,
    end_date,
    weeks: int,
    model_cls: Callable[[], ForecastModel],
    view: str = "base_demand",
    window_train: int = 13,
    window_test: int = 4,
    min_weeks: int = 20,
    session=None,
) -> dict | None:
    """单 SKU 回测; 返回 metrics dict 或 None (不达可回测条件).

    None 触发场景:
    - SKU 类型 wholesale_only / unclassified (view=base_demand)
    - 序列长度 < window_train + window_test
    - 非零周数 < min_weeks
    """
    built = _build_series(barcode, end_date, weeks, view, session)
    if built is None:
        return None
    series, sku_type, _n_excluded = built

    if len(series) < window_train + window_test:
        return None
    # 入选过滤只数训练可用段 (审计 SN-2): 测试期销量不再决定该 SKU 是否入选,
    # 否则"后来才卖起来"的 SKU 被纳入 = 幸存者偏差。最后 window_test 周是
    # 末窗的测试期, 必从分母排除。
    train_avail = series[: len(series) - window_test]
    nonzero = sum(1 for v in train_avail if v > 0)
    if nonzero < min_weeks:
        return None

    records = walk_forward_backtest(series, model_cls, window_train, window_test)
    if not records:
        return None

    actual = [r["actual"] for r in records]
    pred = [r["predicted"] for r in records]
    p98_list = [r["p98"] for r in records]
    n = len(actual)
    return {
        "barcode": barcode,
        "sku_type": sku_type,
        "n_weeks_train": window_train,
        "n_weeks_test": window_test,
        "mape": mape(actual, pred),
        "mase": mase_from_records(records),
        "bias": bias(actual, pred),
        "coverage_p98": coverage_p98(actual, p98_list),
        "mean_actual": sum(actual) / n,
        "mean_predicted": sum(pred) / n,
    }


def run_backtest_all_skus(
    model_name: str,
    end_date,
    weeks: int = 156,
    view: str = "base_demand",
    window_train: int = 13,
    window_test: int = 4,
    min_weeks: int = 20,
    notes: str | None = None,
    barcodes: list[str] | None = None,
) -> int:
    """全量 SKU 回测, 写 backtest_runs + backtest_results. 返回 run_id.

    model_name 必须在 BASELINES 字典内。
    barcodes=None: 跑所有 stockpile 主档活跃 SKU。barcodes=[...] 跑指定子集 (测试 / 单跑用)。
    """
    from sqlalchemy import insert, select, update

    from app.models import BacktestResult, BacktestRun, Stockpile
    from app.repositories import stockpile_db

    if model_name not in BASELINES:
        raise ValueError(f"unknown model_name: {model_name}; got: {list(BASELINES)}")
    if view not in ("base_demand", "all"):
        raise ValueError(f"unknown view: {view}")
    model_cls = BASELINES[model_name]

    with stockpile_db._session() as s:
        # 创建 run row
        ins = s.execute(
            insert(BacktestRun).values(
                model_name=model_name,
                view=view,
                window_train=window_train,
                window_test=window_test,
                min_weeks=min_weeks,
                notes=notes,
            )
        )
        run_id = ins.inserted_primary_key[0]

        if barcodes is None:
            rows = s.execute(
                select(Stockpile.product_barcode).where(Stockpile.is_active == 1)
            ).all()
            barcodes = [r[0] for r in rows]

        n_total = len(barcodes)
        n_scored = 0
        for bc in barcodes:
            r = run_backtest_for_sku(
                bc,
                end_date,
                weeks,
                model_cls,
                view=view,
                window_train=window_train,
                window_test=window_test,
                min_weeks=min_weeks,
                session=s,
            )
            if r is None:
                continue
            s.execute(
                insert(BacktestResult).values(
                    run_id=run_id,
                    product_barcode=bc,
                    sku_type=r["sku_type"],
                    n_weeks_train=r["n_weeks_train"],
                    n_weeks_test=r["n_weeks_test"],
                    mape=r["mape"],
                    mase=r["mase"],
                    bias=r["bias"],
                    coverage_p98=r["coverage_p98"],
                    mean_actual=r["mean_actual"],
                    mean_predicted=r["mean_predicted"],
                )
            )
            n_scored += 1

        s.execute(
            update(BacktestRun)
            .where(BacktestRun.id == run_id)
            .values(n_skus_total=n_total, n_skus_scored=n_scored)
        )
        s.commit()
        return run_id


# ---- §2.8 双视图对比 --------------------------------------------------------


def compare_run_pair(run_id_a: int, run_id_b: int) -> dict:
    """对比两次 run 的 per-SKU 分数差异 (plan §2.8 双视图诊断).

    返回 {
        "run_a": {id, model_name, view, n_scored},
        "run_b": {id, model_name, view, n_scored},
        "common_skus": int,
        "items": [{
            "product_barcode", "sku_type",
            "mape_a", "mape_b", "mape_delta" (b - a),
            "mase_a", "mase_b", "mase_delta",
            "coverage_a", "coverage_b",
        }],
        "summary": {
            "median_mase_delta": float | None,
            "improved": int  (b 的 MASE < a),
            "worsened": int,
            "unchanged": int,
        }
    }
    """
    from sqlalchemy import select

    from app.models import BacktestResult, BacktestRun
    from app.repositories import stockpile_db

    with stockpile_db._session() as s:
        run_a = s.execute(
            select(BacktestRun).where(BacktestRun.id == run_id_a)
        ).scalar_one_or_none()
        run_b = s.execute(
            select(BacktestRun).where(BacktestRun.id == run_id_b)
        ).scalar_one_or_none()
        if run_a is None or run_b is None:
            raise ValueError(f"run not found: a={run_id_a} b={run_id_b}")

        rows_a = (
            s.execute(select(BacktestResult).where(BacktestResult.run_id == run_id_a))
            .scalars()
            .all()
        )
        rows_b = (
            s.execute(select(BacktestResult).where(BacktestResult.run_id == run_id_b))
            .scalars()
            .all()
        )

    map_a = {r.product_barcode: r for r in rows_a}
    map_b = {r.product_barcode: r for r in rows_b}
    common = sorted(set(map_a) & set(map_b))

    items: list[dict] = []
    deltas: list[float] = []
    improved = worsened = unchanged = 0
    for bc in common:
        ra, rb = map_a[bc], map_b[bc]
        mape_delta = (rb.mape - ra.mape) if (ra.mape is not None and rb.mape is not None) else None
        mase_delta = (rb.mase - ra.mase) if (ra.mase is not None and rb.mase is not None) else None
        items.append(
            {
                "product_barcode": bc,
                "sku_type": rb.sku_type or ra.sku_type,
                "mape_a": ra.mape,
                "mape_b": rb.mape,
                "mape_delta": mape_delta,
                "mase_a": ra.mase,
                "mase_b": rb.mase,
                "mase_delta": mase_delta,
                "coverage_a": ra.coverage_p98,
                "coverage_b": rb.coverage_p98,
            }
        )
        if mase_delta is not None:
            deltas.append(mase_delta)
            if mase_delta < -1e-9:
                improved += 1
            elif mase_delta > 1e-9:
                worsened += 1
            else:
                unchanged += 1

    median_delta: float | None = None
    if deltas:
        sd = sorted(deltas)
        n = len(sd)
        median_delta = sd[n // 2] if n % 2 else (sd[n // 2 - 1] + sd[n // 2]) / 2.0

    return {
        "run_a": {
            "id": run_a.id,
            "model_name": run_a.model_name,
            "view": run_a.view,
            "n_skus_scored": run_a.n_skus_scored,
        },
        "run_b": {
            "id": run_b.id,
            "model_name": run_b.model_name,
            "view": run_b.view,
            "n_skus_scored": run_b.n_skus_scored,
        },
        "common_skus": len(common),
        "items": items,
        "summary": {
            "median_mase_delta": median_delta,
            "improved": improved,
            "worsened": worsened,
            "unchanged": unchanged,
        },
    }
