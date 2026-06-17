"""GET /api/history/<barcode>/analytics：SLA+PUR+客户拆分瘦端点（Phase 2a 契约）。

只返回 {ok, sales, purchase, customer_split}（HC-A5）。鉴权镜像 tests/test_api_briefing.py。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _get(app, bc):
    return app.test_client().get(
        f"/api/history/{bc}/analytics", headers={"X-Upload-Token": "test-token-123"}
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


def test_analytics_unauthenticated_returns_json_401(real_app):
    r = real_app.test_client().get("/api/history/X/analytics")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_analytics_key_set_is_exactly_2a(real_app):
    """HC-A5：响应 key 恰好 {ok, sales, purchase, customer_split}，无 2b key。"""
    _seed_stockpile(real_app, "B1", "M1")
    r = _get(real_app, "B1")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"ok", "sales", "purchase", "customer_split"}
    assert set(body["customer_split"]) == {"cn", "fo"}


def test_analytics_no_sales_returns_zero_shape(real_app):
    """只有主档无事件：sales 全 0、customer_split 两端 0（合法零值，非错误）。"""
    _seed_stockpile(real_app, "B1", "M1")
    body = _get(real_app, "B1").get_json()
    assert body["ok"] is True
    assert body["sales"]["total_qty"] == 0
    assert body["sales"]["trend_slope_pct_per_week"] is None
    assert body["customer_split"]["cn"]["qty"] == 0
    assert body["purchase"]["stock_balance"] == 0


def test_analytics_with_events(real_app):
    """seed sale+purchase 事件：sales.total_qty 汇总、purchase.stock_balance = 进-销。"""
    _seed_stockpile(real_app, "B1", "M1")
    _seed_event("B1", "sale", 3, "2026-05-01", unit_price=10.0)
    _seed_event("B1", "sale", 2, "2026-05-08", unit_price=10.0)
    _seed_event("B1", "purchase", 10, "2026-04-01", unit_price=6.0)
    body = _get(real_app, "B1").get_json()
    assert body["sales"]["total_qty"] == 5
    assert body["purchase"]["stock_balance"] == 5
