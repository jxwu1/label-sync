"""预测模型效果看板 + 置信度分层 (第1期任务③).

置信度分层把 forecast_output(history/nonzero) 与 backtest_results(MASE/coverage)
合成一个"高/中/低可信"标签 + 解释理由, 给补货页/老板看板用。立场: 预测是补货
风险参考非精确销量, 故分层偏保守。

命名约定: 近期信号污染叫 `recent_zero_demand`(近期零需求偏多), **不叫"断货"**——
第1期没有库存快照, 证明不了 stockout(有货卖不出 vs 没人买)。第2期接库存快照后
再升级成真正的缺货修正。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 用户 2026-06-05 定的阈值。
_HIGH_HISTORY = 52
_HIGH_NONZERO = 12
_HIGH_MASE = 1.0
_HIGH_COVERAGE = 0.95

_MED_HISTORY = 26
_MED_NONZERO = 6
_MED_MASE = 1.2

# 近期零需求周数达到此值 → 降一级。>=4 太容易误伤间歇/季节性 SKU, 用户定死 6。
_RECENT_ZERO_DOWNGRADE = 6

_TIERS = ("low", "medium", "high")


@dataclass(frozen=True)
class ConfidenceResult:
    """分层结果 + 可解释理由。

    tier: "high" | "medium" | "low"
    reasons: 机器可读标签列表, 解释为何落在该档(含降级原因), 供看板/老板解释复用。
    """

    tier: str
    reasons: list[str]


def demand_history_stats(series: list[float]) -> tuple[int, int]:
    """从周需求序列(升序, 最新在末) 算 (nonzero_weeks, zero_weeks_last8)。

    - nonzero_weeks: 整段里 >0 的周数 (与 backtest min_weeks 口径一致)。
    - zero_weeks_last8: 最近 8 周里 <=0 的周数 (近期零需求信号)。序列短于 8 周时
      就在现有长度上数。
    """
    nonzero_weeks = sum(1 for v in series if v > 0)
    zero_weeks_last8 = sum(1 for v in series[-8:] if v <= 0)
    return nonzero_weeks, zero_weeks_last8


def _is_usable_metric(x: float | None) -> bool:
    """metric 可用 = 非 None 且非 NaN。backtest 没跑过 → None; 计算不出 → NaN。"""
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def confidence_tier(
    *,
    history_weeks: int,
    nonzero_weeks: int,
    mase: float | None,
    coverage_p98: float | None,
    zero_weeks_last8: int,
) -> ConfidenceResult:
    """把一个 SKU 的预测可信度分成 high/medium/low + 理由。

    无 backtest metrics(MASE/coverage 任一不可算) → 直接 low + missing_backtest,
    这样线上 backtest 空表时整页可解释(不会假装有可信度)。
    """
    if not _is_usable_metric(mase) or not _is_usable_metric(coverage_p98):
        return ConfidenceResult("low", ["missing_backtest"])

    reasons: list[str] = []

    if (
        history_weeks >= _HIGH_HISTORY
        and nonzero_weeks >= _HIGH_NONZERO
        and mase < _HIGH_MASE
        and coverage_p98 >= _HIGH_COVERAGE
    ):
        tier = "high"
        reasons += ["history>=52", "nonzero>=12", "mase<1.0", "coverage_p98>=0.95"]
    elif history_weeks >= _MED_HISTORY and nonzero_weeks >= _MED_NONZERO and mase < _MED_MASE:
        tier = "medium"
        reasons += ["history>=26", "nonzero>=6", "mase<1.2"]
    else:
        tier = "low"
        if history_weeks < _MED_HISTORY:
            reasons.append("history<26")
        if nonzero_weeks < _MED_NONZERO:
            reasons.append("nonzero<6")
        if mase >= _MED_MASE:
            reasons.append("mase>=1.2")

    # 降级: 近期零需求偏多 → 信号不可靠, 降一级(已 low 则保持, 仍记理由)。
    if zero_weeks_last8 >= _RECENT_ZERO_DOWNGRADE:
        idx = _TIERS.index(tier)
        if idx > 0:
            tier = _TIERS[idx - 1]
            reasons.append("downgrade:recent_zero_demand")
        else:
            reasons.append("recent_zero_demand")

    return ConfidenceResult(tier, reasons)


# ── 预测效果看板 (步骤3) ──────────────────────────────────────────────
# 生产 forecast 只用 EmpiricalQuantile/base_demand(见 refresh_forecast_output),
# 故置信分层 join 这条线的最新 run; 模型对比则跑遍所有 baseline 的最新 base_demand run。
_PROD_MODEL = "EmpiricalQuantile"
_PROD_VIEW = "base_demand"
_COMPARE_MODELS = (
    "NaiveMean4W",
    "NaiveSeasonal52W",
    "LinearTrend12W",
    "CrostonSBA",
    "EmpiricalQuantile",
    "HoltWinters",
)


def _latest_run(session, model_name: str, view: str):
    """该 (model, view) 最新一次 run 的 (id, created_at), 没有则 None。id 自增=创建序。"""
    from sqlalchemy import select

    from app.models import BacktestRun

    return session.execute(
        select(BacktestRun.id, BacktestRun.created_at)
        .where(BacktestRun.model_name == model_name, BacktestRun.view == view)
        .order_by(BacktestRun.id.desc())
        .limit(1)
    ).first()


def _aggregate_metrics(maybe_mases: list[float], coverages: list[float]) -> dict:
    """对一组 (mase, coverage) 算 headline 指标。mase<1 占比=跑赢 naive 比例。"""
    import numpy as np

    n = len(maybe_mases)
    if n == 0:
        return {"n": 0, "median_mase": None, "beats_naive_pct": None, "avg_coverage_p98": None}
    arr = np.asarray(maybe_mases, dtype=float)
    beats = float(np.mean(arr < 1.0)) * 100.0
    return {
        "n": n,
        "median_mase": float(np.median(arr)),
        "beats_naive_pct": beats,
        "avg_coverage_p98": float(np.mean(coverages)) if coverages else None,
    }


def _run_metrics(session, run_id: int) -> dict:
    """某 run 全部 SKU 的 backtest 聚合 (模型对比用)。"""
    from sqlalchemy import select

    from app.models import BacktestResult

    mases: list[float] = []
    covs: list[float] = []
    for mase, cov in session.execute(
        select(BacktestResult.mase, BacktestResult.coverage_p98).where(
            BacktestResult.run_id == run_id
        )
    ):
        if _is_usable_metric(mase):
            mases.append(float(mase))
        if cov is not None:
            covs.append(float(cov))
    return _aggregate_metrics(mases, covs)


def build_forecast_eval_dashboard(session) -> dict:
    """预测效果看板聚合 (步骤3).

    - tier 分布: 全部 forecast_output 行, 各按 confidence_tier 落 high/medium/low
      (没匹配 backtest → low + missing_backtest)。
    - headline: 已评分 SKU(有 backtest mase) 的 MASE<1 占比 / 中位 MASE / 平均 coverage。
    - by_sku_type: 已评分 SKU 按 sku_type 分组同上。
    - models: 6 个 baseline 各自最新 base_demand run 的聚合, 给"该不该换模型"看。
    """
    from collections import defaultdict

    from sqlalchemy import select

    from app.models import BacktestResult, ForecastOutput

    prod = _latest_run(session, _PROD_MODEL, _PROD_VIEW)
    run_id = prod.id if prod else None
    backtest_date = prod.created_at if prod else None

    # run 44 的 per-SKU backtest 指标: barcode -> (mase, coverage)
    metrics: dict[str, tuple] = {}
    if run_id is not None:
        for bc, mase, cov in session.execute(
            select(
                BacktestResult.product_barcode,
                BacktestResult.mase,
                BacktestResult.coverage_p98,
            ).where(BacktestResult.run_id == run_id)
        ):
            metrics[bc] = (mase, cov)

    rows = session.execute(
        select(
            ForecastOutput.product_barcode,
            ForecastOutput.sku_type,
            ForecastOutput.n_weeks_history,
            ForecastOutput.nonzero_weeks,
            ForecastOutput.zero_weeks_last8,
        )
    ).all()

    tiers = {"high": 0, "medium": 0, "low": 0}
    scored_mase: list[float] = []
    scored_cov: list[float] = []
    by_type_mase: dict[str, list[float]] = defaultdict(list)
    by_type_cov: dict[str, list[float]] = defaultdict(list)
    scored = 0

    for bc, sku_type, hist, nz, z8 in rows:
        mase, cov = metrics.get(bc, (None, None))
        res = confidence_tier(
            history_weeks=hist,
            nonzero_weeks=nz,
            mase=mase,
            coverage_p98=cov,
            zero_weeks_last8=z8,
        )
        tiers[res.tier] += 1
        if _is_usable_metric(mase):
            scored += 1
            scored_mase.append(float(mase))
            by_type_mase[sku_type].append(float(mase))
            if cov is not None:
                scored_cov.append(float(cov))
                by_type_cov[sku_type].append(float(cov))

    by_sku_type = [
        {"sku_type": t, **_aggregate_metrics(by_type_mase[t], by_type_cov.get(t, []))}
        for t in sorted(by_type_mase)
    ]

    models = []
    for m in _COMPARE_MODELS:
        r = _latest_run(session, m, _PROD_VIEW)
        if r is None:
            continue
        models.append(
            {
                "model_name": m,
                "run_id": r.id,
                "created_at": r.created_at,
                "is_production": m == _PROD_MODEL,
                **_run_metrics(session, r.id),
            }
        )

    return {
        "run_id": run_id,
        "backtest_date": backtest_date,
        "forecast_skus": len(rows),
        "scored_skus": scored,
        "tiers": tiers,
        "headline": _aggregate_metrics(scored_mase, scored_cov),
        "by_sku_type": by_sku_type,
        "models": models,
    }
