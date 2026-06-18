"""GET /api/history/<barcode>/analytics/extras：深度分析端点（Phase 2b 契约）。

只返回 {ok, extras, holding, heatmap, forecast, restock}（HC-B2-B6）。
鉴权 + 夹具镜像 tests/test_history_analytics_api.py。
"""

from __future__ import annotations

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


def _seed_forecast(app, barcode):
    """seed ForecastOutput 行（NOT NULL 列全填）。"""
    from app.repositories import stockpile_db

    with app.app_context():
        with stockpile_db._session() as s:
            s.execute(
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
            s.commit()


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
    """若 restock 不为 None，验证投影字段集：不含原始大行 key，含 urgency_breakdown。"""
    _seed_stockpile(real_app, "B3", "M3")
    with real_app.app_context():
        _seed_event("B3", "sale", 5, "2026-05-01", unit_price=10.0)
        _seed_event("B3", "purchase", 10, "2026-04-01", unit_price=6.0)
        _seed_forecast(real_app, "B3")

    r = _get(real_app, "B3")
    assert r.status_code == 200
    body = r.get_json()
    restock = body["restock"]
    if restock is not None:
        # HC-B6: 原始大行 key 不得透传
        raw_only_keys = {"supplier_id", "cn_qty", "fo_qty", "weekly_qty_12w", "barcode", "model"}
        assert raw_only_keys.isdisjoint(restock.keys()), (
            f"投影字段集包含了不该有的原始 key: {raw_only_keys & restock.keys()}"
        )
        # urgency_breakdown 必须在投影字段集内
        assert "urgency_breakdown" in restock
