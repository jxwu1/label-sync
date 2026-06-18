"""GET /api/history/<barcode>/analytics/extras：深度分析端点（Phase 2b 契约）。

只返回 {ok, extras, holding, heatmap, forecast, restock}（HC-B2-B6）。
鉴权 + 夹具镜像 tests/test_history_analytics_api.py。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import insert, text

from app.models import ForecastOutput


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _get(app, bc):
    return app.test_client().get(
        f"/api/history/{bc}/analytics/extras",
        headers={"X-Upload-Token": "test-token-123"},
    )


def _get_no_propagate(app, bc):
    """TESTING=True は例外を再 raise するので, 500 を検証するテストでは
    PROPAGATE_EXCEPTIONS=False にしたクライアントを使う（test_briefing_routes.py 同様）。
    """
    client = app.test_client()
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    return client.get(
        f"/api/history/{bc}/analytics/extras",
        headers={"X-Upload-Token": "test-token-123"},
    )


def _exec(sql, params):
    from app import db

    with db.get_engine().begin() as conn:
        conn.execute(text(sql), params)


def _seed_stockpile(app, barcode, model):
    import pandas as pd

    from app.repositories import stockpile_db

    with app.app_context():
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [{"product_barcode": barcode, "product_model": model, "stockpile_location": "A1"}]
            )
        )


def _seed_event(barcode, event_type, qty, at, unit_price=None):
    _exec(
        "INSERT INTO inventory_events (product_barcode, event_type, qty, unit_price, event_at) "
        "VALUES (:b, :t, :q, :p, :at)",
        {"b": barcode, "t": event_type, "q": qty, "p": unit_price, "at": at},
    )


def _seed_forecast(barcode):
    """seed ForecastOutput 行（NOT NULL 列全填）。必须在 app_context 内调用。"""
    from app import db

    with db.get_engine().begin() as conn:
        conn.execute(
            insert(ForecastOutput).values(
                product_barcode=barcode,
                model_used="EmpiricalQuantile",
                sku_type="retail_dominant",
                n_weeks_history=52,
                nonzero_weeks=30,
                zero_weeks_last8=0,
                stockout_zero_weeks_last8=0,
                mu=2.0,
                sigma=1.0,
                p50=2.0,
                p98=6.0,
            )
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extras_unauth_returns_401(real_app):
    r = real_app.test_client().get("/api/history/12345/analytics/extras")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_extras_hit_response_key_set(real_app):
    """seed sale+purchase 事件后 GET → 200，响应 key 恰好 {ok,extras,holding,heatmap,forecast,restock}。"""
    _seed_stockpile(real_app, "B2", "M2")
    with real_app.app_context():
        _seed_event("B2", "sale", 3, "2026-05-01", unit_price=10.0)
        _seed_event("B2", "purchase", 5, "2026-04-01", unit_price=6.0)

    r = _get(real_app, "B2")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body.keys()) == {"ok", "extras", "holding", "heatmap", "forecast", "restock"}
    # HC-A5 隔离：2a 的 key 不出现在 2b 响应
    assert "sales" not in body
    assert "purchase" not in body
    assert "customer_split" not in body


def test_restock_projection_key_set(real_app):
    """restock 不为 None 时，验证投影字段集：不含原始大行 key，含 urgency_breakdown。

    seed 条件：active stockpile (is_truly_discontinued=False) + sale + purchase 事件，
    确保 list_sku_summary 返回该 barcode，compute_restock_snapshot 必非 None。
    """
    from app.services.analytics import clear_list_sku_summary_cache

    _seed_stockpile(real_app, "B3", "M3")
    with real_app.app_context():
        _seed_event("B3", "sale", 5, "2026-05-01", unit_price=10.0)
        _seed_event("B3", "purchase", 10, "2026-04-01", unit_price=6.0)
        _seed_forecast("B3")
        # 清缓存，确保 list_sku_summary 使用当前 seed 数据而非前一测试的缓存
        clear_list_sku_summary_cache()

    r = _get(real_app, "B3")
    assert r.status_code == 200
    body = r.get_json()
    restock = body["restock"]
    assert restock is not None, "seeded active SKU must be computable in restock summary"
    # HC-B6: 原始大行 key 不得透传
    leaked = {"supplier_id", "cn_qty", "fo_qty", "weekly_qty_12w", "barcode", "model"}
    assert leaked.isdisjoint(restock.keys()), (
        f"投影字段集包含了不该有的原始 key: {leaked & restock.keys()}"
    )
    # urgency_breakdown 必须在投影字段集内
    assert "urgency_breakdown" in restock


def test_restock_qty_total_none_passes_schema():
    """qty_total=None 从 _project_restock 透传，通过 RestockSnapshot 校验（不应被 0 替换）。

    用投影层测试而非端到端 seed，因为 "有事件但无库存快照" 在测试 DB 中构造不可靠
    （compute_restock_snapshot 聚合逻辑在 restock_calc.py 内部可能补零）。
    直接测 _project_restock + schema 校验层的正确行为更精准。
    """
    from app.routes.history import _RESTOCK_PROJECTION_KEYS, _project_restock
    from app.schemas_api import RestockSnapshot

    # 构造一个最小合法行：qty_total=None，其他非 Optional 字段给合法默认值
    full_row = {k: None for k in _RESTOCK_PROJECTION_KEYS}
    full_row.update(
        {
            "retail_qty_26w": 3,
            "lifetime_purchase_qty": 10,
            "lifetime_sale_revenue_eur": 100.0,
            "lifetime_sale_qty": 8,
            "weekly_velocity": 0.5,
            "weekly_revenue": 5.0,
            "n_active_weeks_26w": 20,
            # qty_total 保持 None
        }
    )

    projected = _project_restock(full_row)
    assert projected["qty_total"] is None  # None 透传，不得被替换成 0

    snapshot = RestockSnapshot.model_validate(projected)
    assert snapshot.qty_total is None  # schema 接受 None


# ---------------------------------------------------------------------------
# Phase 2b 深度测试：分支/边界/原子失败/validator/fetch 次数
# ---------------------------------------------------------------------------


def test_forecast_none_when_no_output(real_app):
    """无 forecast_output 行 → body["forecast"] is None。"""
    _seed_stockpile(real_app, "FN1", "MFN1")
    with real_app.app_context():
        _seed_event("FN1", "sale", 3, "2026-05-01", unit_price=10.0)

    r = _get(real_app, "FN1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["forecast"] is None


def test_forecast_is_stale_flag(real_app):
    """forecast_output.computed_at > 14 天前 → is_stale is True（RL-9）。"""
    _seed_stockpile(real_app, "FS1", "MFS1")
    stale_date = (date.today() - timedelta(days=30)).isoformat() + " 00:00:00"
    with real_app.app_context():
        _seed_event("FS1", "sale", 5, "2026-05-01", unit_price=10.0)
        # 插入 computed_at 远超 14 天的预测行（用字符串形式写入，与 server_default 同格式）
        from app import db

        with db.get_engine().begin() as conn:
            from sqlalchemy import insert

            from app.models import ForecastOutput

            conn.execute(
                insert(ForecastOutput).values(
                    product_barcode="FS1",
                    model_used="EmpiricalQuantile",
                    sku_type="retail_dominant",
                    n_weeks_history=52,
                    nonzero_weeks=30,
                    zero_weeks_last8=0,
                    stockout_zero_weeks_last8=0,
                    mu=2.0,
                    sigma=1.0,
                    p50=2.0,
                    p98=6.0,
                    computed_at=stale_date,  # 30 days ago — clearly > 14-day threshold
                )
            )

    r = _get(real_app, "FS1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["forecast"] is not None
    assert body["forecast"]["is_stale"] is True


def test_forecast_fresh_flag(real_app):
    """forecast_output.computed_at within 14 days → is_stale is False。"""
    _seed_stockpile(real_app, "FF1", "MFF1")
    fresh_date = (date.today() - timedelta(days=1)).isoformat() + " 10:00:00"
    with real_app.app_context():
        _seed_event("FF1", "sale", 5, "2026-05-01", unit_price=10.0)
        from app import db

        with db.get_engine().begin() as conn:
            from sqlalchemy import insert

            from app.models import ForecastOutput

            conn.execute(
                insert(ForecastOutput).values(
                    product_barcode="FF1",
                    model_used="EmpiricalQuantile",
                    sku_type="retail_dominant",
                    n_weeks_history=52,
                    nonzero_weeks=30,
                    zero_weeks_last8=0,
                    stockout_zero_weeks_last8=0,
                    mu=2.0,
                    sigma=1.0,
                    p50=2.0,
                    p98=6.0,
                    computed_at=fresh_date,  # 1 day ago — clearly <= 14-day threshold
                )
            )

    r = _get(real_app, "FF1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["forecast"] is not None
    assert body["forecast"]["is_stale"] is False


def test_heatmap_12_months_each_year(real_app):
    """heatmap 矩阵中每个 year key 的列表长度必须是 12。"""
    _seed_stockpile(real_app, "HM1", "MHM1")
    with real_app.app_context():
        _seed_event("HM1", "sale", 3, "2026-05-01", unit_price=10.0)

    r = _get(real_app, "HM1")
    assert r.status_code == 200
    body = r.get_json()
    heatmap = body["heatmap"]
    assert "matrix" in heatmap
    for year, months in heatmap["matrix"].items():
        assert len(months) == 12, f"year {year} has {len(months)} months, expected 12"


def test_heatmap_validator_rejects_non_12(real_app, monkeypatch):
    """compute_monthly_heatmap 返回 11-month matrix → SkuExtrasResponse 校验失败 → 500。

    patch 目标：app.services.analytics.compute_monthly_heatmap（route 通过
    `from app.services import analytics as analytics_service` 读该属性）。
    """
    import app.services.analytics as _analytics_mod

    monkeypatch.setattr(
        _analytics_mod,
        "compute_monthly_heatmap",
        lambda *a, **kw: {"years": ["2026"], "matrix": {"2026": [0] * 11}, "max_qty": 0},
    )

    _seed_stockpile(real_app, "HV1", "MHV1")
    with real_app.app_context():
        _seed_event("HV1", "sale", 3, "2026-05-01", unit_price=10.0)

    r = _get_no_propagate(real_app, "HV1")
    assert r.status_code == 500, (
        f"expected 500 from validator rejection of 11-month matrix, got {r.status_code}"
    )


def test_fetch_event_rows_called_once(real_app, monkeypatch):
    """fetch_event_rows 在每个请求中恰好被调用一次（HC-B2 单次取行复用）。"""
    import app.services.analytics as _analytics_mod

    original_fetch = _analytics_mod.fetch_event_rows
    call_count = {"n": 0}

    def counting_fetch(bc, **kw):
        call_count["n"] += 1
        return original_fetch(bc, **kw)

    monkeypatch.setattr(_analytics_mod, "fetch_event_rows", counting_fetch)

    _seed_stockpile(real_app, "FC1", "MFC1")
    with real_app.app_context():
        _seed_event("FC1", "sale", 3, "2026-05-01", unit_price=10.0)

    r = _get(real_app, "FC1")
    assert r.status_code == 200
    assert call_count["n"] == 1, (
        f"fetch_event_rows was called {call_count['n']} times, expected exactly 1"
    )


@pytest.mark.parametrize(
    "fn_name",
    [
        "fetch_event_rows",
        "compute_sku_extras",
        "compute_avg_holding_days",
        "compute_monthly_heatmap",
        "compute_forecast_snapshot",
        "compute_restock_snapshot",
    ],
)
def test_atomic_failure_any_function_raises_500(real_app, monkeypatch, fn_name):
    """任意 analytics_service 函数抛 RuntimeError → 端点返回 500。"""
    import app.services.analytics as _analytics_mod

    monkeypatch.setattr(
        _analytics_mod,
        fn_name,
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(f"injected failure in {fn_name}")),
    )

    _seed_stockpile(real_app, f"AF_{fn_name[:4]}", "MAF1")
    with real_app.app_context():
        _seed_event(f"AF_{fn_name[:4]}", "sale", 2, "2026-05-01", unit_price=10.0)

    r = _get_no_propagate(real_app, f"AF_{fn_name[:4]}")
    assert r.status_code == 500, f"expected 500 when {fn_name} raises, got {r.status_code}"
