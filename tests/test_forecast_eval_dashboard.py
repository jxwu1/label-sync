"""预测效果看板聚合契约 (第1期任务③ 步骤3).

forecast_output ⨝ 最新 EmpiricalQuantile/base_demand backtest run, 逐 SKU 算
confidence_tier, 聚合出 headline(MASE<1 占比/中位 MASE/coverage) + tier 分布
+ 按 sku_type + 模型对比。Python 端聚合(SQLite/PG 一致)。
"""

from __future__ import annotations

from sqlalchemy import insert

from app.models import BacktestResult, BacktestRun, ForecastOutput, Stockpile
from app.repositories import stockpile_db
from app.services.forecast_eval import build_forecast_eval_dashboard


def _seed_run(model="EmpiricalQuantile", view="base_demand") -> int:
    with stockpile_db._session() as s:
        res = s.execute(
            insert(BacktestRun).values(
                model_name=model,
                view=view,
                window_train=13,
                window_test=4,
                min_weeks=20,
                n_skus_total=0,
                n_skus_scored=0,
            )
        )
        s.commit()
        return res.inserted_primary_key[0]


def _seed_forecast(barcode, *, hist, nz, zero8, sku_type="retail_dominant"):
    with stockpile_db._session() as s:
        s.execute(
            insert(Stockpile).values(
                product_barcode=barcode,
                product_model=barcode,
                stockpile_location="",
                is_active=1,
            )
        )
        s.execute(
            insert(ForecastOutput).values(
                product_barcode=barcode,
                model_used="EmpiricalQuantile",
                sku_type=sku_type,
                n_weeks_history=hist,
                nonzero_weeks=nz,
                zero_weeks_last8=zero8,
                mu=1.0,
                sigma=1.0,
                p50=1.0,
                p98=3.0,
            )
        )
        s.commit()


def _seed_result(run_id, barcode, *, mase, cov, sku_type="retail_dominant"):
    with stockpile_db._session() as s:
        s.execute(
            insert(BacktestResult).values(
                run_id=run_id,
                product_barcode=barcode,
                sku_type=sku_type,
                n_weeks_train=52,
                n_weeks_test=4,
                mape=0.2,
                mase=mase,
                bias=0.0,
                coverage_p98=cov,
                mean_actual=5.0,
                mean_predicted=5.0,
            )
        )
        s.commit()


def _full_fixture() -> int:
    run = _seed_run()
    _seed_forecast("HIGH", hist=60, nz=20, zero8=0)
    _seed_result(run, "HIGH", mase=0.8, cov=0.97)
    _seed_forecast("MED", hist=30, nz=8, zero8=0)
    _seed_result(run, "MED", mase=1.1, cov=0.90)
    _seed_forecast("LOWMASE", hist=60, nz=20, zero8=0)
    _seed_result(run, "LOWMASE", mase=1.5, cov=0.90)
    # 有 forecast 无 backtest → low + missing_backtest
    _seed_forecast("NOBT", hist=60, nz=20, zero8=0)
    return run


def test_dashboard_headline_and_tiers():
    run = _full_fixture()
    with stockpile_db._session() as s:
        dash = build_forecast_eval_dashboard(s)

    assert dash["run_id"] == run
    assert dash["forecast_skus"] == 4
    assert dash["scored_skus"] == 3  # HIGH/MED/LOWMASE 有 backtest, NOBT 没有
    assert dash["tiers"] == {"high": 1, "medium": 1, "low": 2}

    # 跑赢 naive = mase<1 占 scored 比例, 只有 HIGH(0.8) → 1/3
    assert abs(dash["headline"]["beats_naive_pct"] - (1 / 3 * 100)) < 0.01
    # 中位 MASE over [0.8,1.1,1.5] = 1.1
    assert abs(dash["headline"]["median_mase"] - 1.1) < 1e-6


def test_dashboard_picks_latest_empirical_run():
    old = _seed_run()
    new = _seed_run()
    assert new > old
    _seed_forecast("HIGH", hist=60, nz=20, zero8=0)
    _seed_result(new, "HIGH", mase=0.8, cov=0.97)

    with stockpile_db._session() as s:
        dash = build_forecast_eval_dashboard(s)
    assert dash["run_id"] == new


def test_dashboard_models_comparison_lists_each_model():
    # 每个模型一条最新 base_demand run, 看板 models 各列一行
    for m in ("NaiveMean4W", "EmpiricalQuantile"):
        r = _seed_run(model=m)
        _seed_forecast(f"{m}_S", hist=60, nz=20, zero8=0)
        _seed_result(r, f"{m}_S", mase=0.9, cov=0.96)

    with stockpile_db._session() as s:
        dash = build_forecast_eval_dashboard(s)

    names = {row["model_name"] for row in dash["models"]}
    assert {"NaiveMean4W", "EmpiricalQuantile"} <= names
    prod_rows = [r for r in dash["models"] if r["is_production"]]
    assert prod_rows and prod_rows[0]["model_name"] == "EmpiricalQuantile"


def test_dashboard_empty_when_no_runs():
    _seed_forecast("HIGH", hist=60, nz=20, zero8=0)
    with stockpile_db._session() as s:
        dash = build_forecast_eval_dashboard(s)

    assert dash["run_id"] is None
    assert dash["scored_skus"] == 0
    assert dash["forecast_skus"] == 1
    assert dash["tiers"]["low"] == 1
    assert dash["headline"]["median_mase"] is None


def test_dashboard_no_forecast_at_all():
    with stockpile_db._session() as s:
        dash = build_forecast_eval_dashboard(s)
    assert dash["forecast_skus"] == 0
    assert dash["tiers"] == {"high": 0, "medium": 0, "low": 0}
