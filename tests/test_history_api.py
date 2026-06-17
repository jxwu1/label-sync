"""GET /api/history?q=：货号历史 canonical 端点（pydantic 契约，Phase 1）。

只读，复用 history_service.build_response。鉴权镜像 tests/test_api_briefing.py。
seed 复用 tests/test_history_service.py 的 text() 插入（proven 列，sqlite/PG 通用）。
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


def _get(app, q):
    return app.test_client().get(
        f"/api/history?q={q}", headers={"X-Upload-Token": "test-token-123"}
    )


def _exec(sql, params):
    from app import db

    with db.get_engine().begin() as conn:
        conn.execute(text(sql), params)


def _seed_stockpile(barcode, model, loc="A22-04-04", is_active=1, source="scan_import"):
    _exec(
        "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, is_active, source) "
        "VALUES (:b, :m, :l, :a, :s)",
        {"b": barcode, "m": model, "l": loc, "a": is_active, "s": source},
    )


def _seed_change(barcode, field, old, new, ctype, at):
    _exec(
        "INSERT INTO stockpile_changes "
        "(product_barcode, field_name, old_value, new_value, change_type, created_at) "
        "VALUES (:b, :f, :o, :n, :c, :at)",
        {"b": barcode, "f": field, "o": old, "n": new, "c": ctype, "at": at},
    )


def test_history_unauthenticated_returns_json_401(real_app):
    r = real_app.test_client().get("/api/history?q=x")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_history_empty_q_returns_400_not_schema(real_app):
    """HC-7：空 q 走 {ok:false,msg} 400，不走 HistorySearchData。"""
    r = _get(real_app, "")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_history_not_found(real_app):
    r = _get(real_app, "nosuchcode")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["found"] is False
    assert not body.get("fuzzy_matches")


def test_history_fuzzy_matches(real_app):
    _seed_stockpile("8299979002791", "ABC123")
    r = _get(real_app, "ABC")
    assert r.status_code == 200
    body = r.get_json()
    assert body["found"] is False
    assert len(body["fuzzy_matches"]) >= 1
    assert body["fuzzy_matches"][0]["barcode"] == "8299979002791"


def test_history_exact_hit_with_events(real_app):
    # current_locations 走子表 stockpile_locations，必须经 import_from_dataframe dual-write 填子表
    import pandas as pd

    from app.repositories import stockpile_db

    with real_app.app_context():
        stockpile_db.import_from_dataframe(
            pd.DataFrame(
                [
                    {
                        "product_barcode": "8299979002791",
                        "product_model": "ABC123",
                        "stockpile_location": "A22-04-04",
                    }
                ]
            )
        )
    _seed_change(
        "8299979002791",
        "stockpile_location",
        "A22-04-04",
        "A22/X11",
        "update",
        "2026-04-25 16:52:43",
    )
    r = _get(real_app, "8299979002791")
    assert r.status_code == 200
    body = r.get_json()
    assert body["found"] is True
    assert body["current"]["barcode"] == "8299979002791"
    assert body["current"]["model"] == "ABC123"
    assert body["current"]["store_locations"] == ["A22-04-04"]
    assert len(body["events"]) >= 1
    # import_from_dataframe 写了 insert change；我们找我们手动插入的 update change
    update_ev = next(e for e in body["events"] if e["change_type"] == "update")
    ch = update_ev["changes"][0]
    assert ch["field"] == "stockpile_location"
    assert ch["new_split"]["stores"] == ["A22"]
    assert ch["new_split"]["warehouses"] == ["X11"]
