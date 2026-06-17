"""GET /api/forecast-eval/data：预测效果看板 canonical 端点（pydantic 契约）。

参照 app/services/forecast_eval.build_forecast_eval_dashboard 的形状。纯只读。
鉴权镜像 tests/test_api_briefing.py（X-Upload-Token）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from app.models import BacktestResult, BacktestRun, ForecastOutput, Stockpile
from app.repositories import stockpile_db


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _get(app):
    return app.test_client().get(
        "/api/forecast-eval/data", headers={"X-Upload-Token": "test-token-123"}
    )


# ---- seed helpers（复制自 tests/test_forecast_eval_dashboard.py，含全部 NOT NULL 列）----
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


def _seed_forecast(barcode, *, hist, nz, zero8, stockout_zero8=0, sku_type="retail_dominant"):
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
                stockout_zero_weeks_last8=stockout_zero8,
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


def test_forecast_eval_unauthenticated_returns_json_401(real_app):
    """未带 token / 未登录：/api/* 必须 JSON 401（不渲染 200，不跳 HTML 登录页）。"""
    r = real_app.test_client().get("/api/forecast-eval/data")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_forecast_eval_empty_db_returns_valid_empty_shape(real_app):
    """空库（仅 seed_auth，无 forecast 数据）：200 + run_id None + tiers 全 0 + 列表空。"""
    r = _get(real_app)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["run_id"] is None
    assert body["forecast_skus"] == 0
    assert body["scored_skus"] == 0
    assert body["tiers"] == {"high": 0, "medium": 0, "low": 0}
    assert body["headline"]["n"] == 0
    assert body["by_sku_type"] == []
    assert body["models"] == []


def test_forecast_eval_seeded_returns_run_and_tiers(real_app):
    """seed 生产 run + 一条已评分高可信 SKU：run_id 出现，high tier 计数 1，模型列表含生产模型。"""
    run_id = _seed_run()
    _seed_forecast("B1", hist=60, nz=20, zero8=0)
    _seed_result(run_id, "B1", mase=0.5, cov=0.99)

    r = _get(real_app)
    assert r.status_code == 200
    body = r.get_json()
    assert body["run_id"] == run_id
    assert body["forecast_skus"] == 1
    assert body["scored_skus"] == 1
    assert body["tiers"]["high"] == 1
    assert body["headline"]["beats_naive_pct"] == 100.0
    assert any(
        m["model_name"] == "EmpiricalQuantile" and m["is_production"] for m in body["models"]
    )
