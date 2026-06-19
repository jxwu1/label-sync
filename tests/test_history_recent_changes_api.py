"""GET /api/history/recent-changes/* 双端点契约测试（Phase 4a）。

鉴权 + 夹具镜像 tests/test_history_extras_api.py（real_app fixture + X-Upload-Token）。
seed 镜像 tests/test_recent_changes_service.py（直接 INSERT snapshot/change）。

覆盖：
- 两端点未鉴权 → JSON 401
- /recent-changes/batches：200，keys=={ok,batches}，开放批次 is_open True & batch_id -1
- /recent-changes/<id>/changes：200，keys=={ok,summary,changes,total_count}
  每行恰好 7 个 ChangeRow key（collapsed + raw 均无 old_value/new_value/created_at/latest_at 泄漏）
- mode=raw 工作；mode=bad → 400；非整数 id abc → 400；-1 → 200；999999 → 404；非 import snapshot → 404
- filter passthrough：field=stockpile_location 收窄；未知 field → 空 changes 仍 200
- spy：get_batch_detail 抛 → 500；_fetch_window_rows 每请求恰好 1 次
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from app.models import StockpileChange, StockpileSnapshot
from app.repositories import stockpile_db


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


_AUTH = {"X-Upload-Token": "test-token-123"}


def _get_batches(app):
    return app.test_client().get("/api/history/recent-changes/batches", headers=_AUTH)


def _get_changes(app, batch_id, query=""):
    return app.test_client().get(
        f"/api/history/recent-changes/{batch_id}/changes{query}", headers=_AUTH
    )


def _get_changes_no_propagate(app, batch_id, query=""):
    """500 检测需要关掉 PROPAGATE_EXCEPTIONS（TESTING=True 默认再 raise）。"""
    client = app.test_client()
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    return client.get(f"/api/history/recent-changes/{batch_id}/changes{query}", headers=_AUTH)


# --- seed helpers（镜像 test_recent_changes_service.py） ---


def _insert_snapshot(taken_at: str, trigger: str = "import", total_local: int = 0) -> int:
    with stockpile_db._session() as session:
        result = session.execute(
            insert(StockpileSnapshot).values(
                taken_at=taken_at, trigger=trigger, total_local=total_local
            )
        )
        session.commit()
        return result.inserted_primary_key[0]


def _insert_change(barcode, field, old, new, change_type="update", created_at=None) -> None:
    with stockpile_db._session() as session:
        values = {
            "product_barcode": barcode,
            "field_name": field,
            "old_value": old,
            "new_value": new,
            "change_type": change_type,
        }
        if created_at:
            values["created_at"] = created_at
        session.execute(insert(StockpileChange).values(**values))
        session.commit()


_CHANGE_ROW_KEYS = {"barcode", "model", "field", "from_value", "to_value", "change_type", "at"}
_LEAK_KEYS = {"old_value", "new_value", "created_at", "latest_at"}


# ---------------------------------------------------------------------------
# 401
# ---------------------------------------------------------------------------


def test_batches_unauth_returns_401(real_app):
    r = real_app.test_client().get("/api/history/recent-changes/batches")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_changes_unauth_returns_401(real_app):
    r = real_app.test_client().get("/api/history/recent-changes/1/changes")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


# ---------------------------------------------------------------------------
# /recent-changes/batches
# ---------------------------------------------------------------------------


def test_batches_returns_ok_and_keys(real_app):
    with real_app.app_context():
        _insert_snapshot("2026-04-29 10:00:00", total_local=100)

    r = _get_batches(real_app)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body.keys()) == {"ok", "batches"}
    assert body["ok"] is True


def test_batches_includes_open_batch(real_app):
    """上次 import 之后有 change → 顶部开放批次 is_open True, batch_id -1。"""
    with real_app.app_context():
        _insert_snapshot("2026-04-29 10:00:00", total_local=100)
        _insert_change("OB1", "stockpile_location", "A1", "B7", created_at="2026-04-29 12:30:00")

    r = _get_batches(real_app)
    assert r.status_code == 200
    batches = r.get_json()["batches"]
    open_batches = [b for b in batches if b["is_open"]]
    assert len(open_batches) == 1
    assert open_batches[0]["batch_id"] == -1


# ---------------------------------------------------------------------------
# /recent-changes/<id>/changes
# ---------------------------------------------------------------------------


def test_changes_returns_ok_and_keys(real_app):
    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")
        _insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

    r = _get_changes(real_app, snap)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body.keys()) == {"ok", "summary", "changes", "total_count"}
    assert body["ok"] is True


def test_changes_collapsed_row_has_exactly_7_keys_no_leak(real_app):
    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")
        _insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

    r = _get_changes(real_app, snap)
    assert r.status_code == 200
    changes = r.get_json()["changes"]
    assert len(changes) == 1
    row = changes[0]
    assert set(row.keys()) == _CHANGE_ROW_KEYS
    assert _LEAK_KEYS.isdisjoint(row.keys())
    # 值正确映射（collapsed latest_at → at, from/to）
    assert row["from_value"] == "A1"
    assert row["to_value"] == "A2"
    assert row["at"] == "2026-04-29 13:00:00"


def test_changes_raw_row_has_exactly_7_keys_no_leak(real_app):
    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")
        _insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

    r = _get_changes(real_app, snap, "?mode=raw")
    assert r.status_code == 200
    changes = r.get_json()["changes"]
    assert len(changes) == 1
    row = changes[0]
    assert set(row.keys()) == _CHANGE_ROW_KEYS
    assert _LEAK_KEYS.isdisjoint(row.keys())
    # raw: old_value/new_value/created_at → from_value/to_value/at
    assert row["from_value"] == "A1"
    assert row["to_value"] == "A2"
    assert row["at"] == "2026-04-29 13:00:00"


# ---------------------------------------------------------------------------
# 400 / 404 / -1
# ---------------------------------------------------------------------------


def test_changes_bad_mode_returns_400(real_app):
    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")

    r = _get_changes(real_app, snap, "?mode=bad")
    assert r.status_code == 400


def test_changes_non_integer_id_returns_400(real_app):
    r = _get_changes(real_app, "abc")
    assert r.status_code == 400


def test_changes_open_batch_minus_one_returns_200(real_app):
    with real_app.app_context():
        _insert_snapshot("2026-04-29 08:00:00")
        _insert_change("B1", "stockpile_location", "A1", "B7", created_at="2026-04-29 09:30:00")

    r = _get_changes(real_app, -1)
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_changes_nonexistent_id_returns_404(real_app):
    r = _get_changes(real_app, 999999)
    assert r.status_code == 404


def test_changes_non_import_snapshot_returns_404(real_app):
    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00", trigger="compare")

    r = _get_changes(real_app, snap)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# filter passthrough
# ---------------------------------------------------------------------------


def test_changes_filter_field_narrows(real_app):
    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")
        _insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
        _insert_change("B2", "product_model", "M1", "M2", created_at="2026-04-29 13:01:00")

    r = _get_changes(real_app, snap, "?field=stockpile_location")
    assert r.status_code == 200
    changes = r.get_json()["changes"]
    assert len(changes) == 1
    assert changes[0]["barcode"] == "B1"


def test_changes_unknown_field_empty_but_200(real_app):
    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")
        _insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

    r = _get_changes(real_app, snap, "?field=no_such_field")
    assert r.status_code == 200
    body = r.get_json()
    assert body["changes"] == []
    assert body["total_count"] == 0


# ---------------------------------------------------------------------------
# spy：get_batch_detail 抛 → 500（证明真经路由调用）
# ---------------------------------------------------------------------------


def test_changes_service_raises_returns_500(real_app, monkeypatch):
    import app.services.recent_changes as _rc

    def boom(*a, **kw):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(_rc, "get_batch_detail", boom)

    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")

    r = _get_changes_no_propagate(real_app, snap)
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# spy：_fetch_window_rows 每请求恰好 1 次（单读）
# ---------------------------------------------------------------------------


def test_changes_fetch_window_rows_called_once(real_app, monkeypatch):
    import app.services.recent_changes as _rc

    original = _rc._fetch_window_rows
    call_count = {"n": 0}

    def counting(session, start, end):
        call_count["n"] += 1
        return original(session, start, end)

    monkeypatch.setattr(_rc, "_fetch_window_rows", counting)

    with real_app.app_context():
        snap = _insert_snapshot("2026-04-29 14:00:00")
        _insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

    r = _get_changes(real_app, snap)
    assert r.status_code == 200
    assert call_count["n"] == 1, f"_fetch_window_rows called {call_count['n']} times, expected 1"
