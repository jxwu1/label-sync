"""GET /api/history/<barcode>/timeline：Phase 3 timeline 端点（TDD）。

鉴权 + 夹具镜像 tests/test_history_extras_api.py。
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


def _exec(sql, params):
    from app import db

    with db.get_engine().begin() as conn:
        conn.execute(text(sql), params)


def _seed_stockpile(app, barcode, model, supplier_id=None):
    import pandas as pd

    from app.repositories import stockpile_db

    with app.app_context():
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": barcode,
                        "product_model": model,
                        "stockpile_location": "A1",
                    }
                ]
            )
        )
    # supplier_id is set via direct SQL after import (import_from_dataframe may not accept it)
    if supplier_id is not None:
        _exec(
            "UPDATE stockpile SET supplier_id = :sid WHERE product_barcode = :bc",
            {"sid": supplier_id, "bc": barcode},
        )


def _seed_event(barcode, event_type, qty, at, unit_price=None, supplier_id=None):
    _exec(
        "INSERT INTO inventory_events "
        "(product_barcode, event_type, qty, unit_price, event_at, supplier_id) "
        "VALUES (:b, :t, :q, :p, :at, :sid)",
        {
            "b": barcode,
            "t": event_type,
            "q": qty,
            "p": unit_price,
            "at": at,
            "sid": supplier_id,
        },
    )


def _logged_in_get(app, url):
    return app.test_client().get(url, headers={"X-Upload-Token": "test-token-123"})


def _logged_in_get_no_propagate(app, url):
    """PROPAGATE_EXCEPTIONS=False で 500 を検証するクライアント。"""
    client = app.test_client()
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    return client.get(url, headers={"X-Upload-Token": "test-token-123"})


# ---------------------------------------------------------------------------
# Task 2 — 基本鉴权 + key/形状测试
# ---------------------------------------------------------------------------


def test_timeline_unauth_returns_401(real_app):
    resp = real_app.test_client().get("/api/history/12345/timeline")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "unauthenticated"


def test_timeline_hit_key_set_and_shapes(real_app):
    """seed sale+purchase 事件后 GET → 200，key 集合/长度/week 字段集/month 字段集。"""
    _seed_stockpile(real_app, "TL1", "MTL1")
    with real_app.app_context():
        _seed_event("TL1", "sale", 3, "2026-05-01", unit_price=10.0)
        _seed_event("TL1", "purchase", 5, "2026-04-01", unit_price=6.0)

    resp = _logged_in_get(real_app, "/api/history/TL1/timeline")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"ok", "timeline", "monthly_sales"}
    assert len(body["timeline"]) == 156
    assert len(body["monthly_sales"]) == 36
    wk = body["timeline"][0]
    assert set(wk.keys()) == {
        "week_start",
        "sale_qty",
        "purchase_unit_price",
        "raw_unit_price_local",
        "currency_local",
    }
    mo = body["monthly_sales"][0]
    assert set(mo.keys()) == {"month_start", "sale_qty", "retail_qty"}


def test_timeline_no_events_sku_ok(real_app):
    """seed stockpile 无事件 → 200；all weeks sale_qty==0 & purchase_unit_price is None；
    all months sale_qty==0 & retail_qty==0。
    （空 barcode 段不测：'/<barcode>/timeline' path 不路由空段。）
    """
    _seed_stockpile(real_app, "TL_NOEV", "MTLNE")
    resp = _logged_in_get(real_app, "/api/history/TL_NOEV/timeline")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert all(w["sale_qty"] == 0 and w["purchase_unit_price"] is None for w in body["timeline"])
    assert all(m["sale_qty"] == 0 and m["retail_qty"] == 0 for m in body["monthly_sales"])


# ---------------------------------------------------------------------------
# Task 3 — CN 货 + 原子失败
# ---------------------------------------------------------------------------


def test_timeline_cn_sku_raw_price_rmb(real_app):
    """CN origin SKU + purchase event → 至少一周有 purchase_unit_price；
    该周 currency_local=="RMB"，raw_unit_price_local not None，purchase_unit_price>0 (EUR)。
    """
    bc = "TL_CN1"
    # supplier_id 以 "CN" 开头 → classify_origin → "CN"
    _seed_stockpile(real_app, bc, "MCNT1", supplier_id="CN001")
    with real_app.app_context():
        # purchase event with supplier_id=CN001 → recorded as CN → RMB path
        _seed_event(bc, "purchase", 10, "2026-04-07", unit_price=42.0, supplier_id="CN001")
        _seed_event(bc, "sale", 3, "2026-05-01", unit_price=10.0)

    resp = _logged_in_get(real_app, f"/api/history/{bc}/timeline")
    assert resp.status_code == 200
    body = resp.get_json()
    priced = [w for w in body["timeline"] if w["purchase_unit_price"] is not None]
    assert priced, "应至少一周有进价"
    w = priced[0]
    assert w["currency_local"] == "RMB"
    assert w["raw_unit_price_local"] is not None
    assert w["purchase_unit_price"] > 0  # EUR 落地成本


@pytest.mark.parametrize("fn_name", ["compute_weekly_timeline", "compute_monthly_sales"])
def test_timeline_atomic_failure_500(real_app, monkeypatch, fn_name):
    """任意 analytics_service 函数抛 RuntimeError → 端点返回 500。"""
    import app.services.analytics as analytics_service

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(analytics_service, fn_name, boom)

    _seed_stockpile(real_app, "TL_AF1", "MTLAF")
    with real_app.app_context():
        _seed_event("TL_AF1", "sale", 2, "2026-05-01", unit_price=10.0)

    resp = _logged_in_get_no_propagate(real_app, "/api/history/TL_AF1/timeline")
    assert resp.status_code == 500, (
        f"expected 500 when {fn_name} raises RuntimeError, got {resp.status_code}"
    )
