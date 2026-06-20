"""GET /api/restock/suppressed：补货抑制集 canonical 端点（pydantic 契约，Vue Phase 1）。

只读，复用 restock_decisions.list_suppressed。鉴权镜像 tests/test_history_api.py
（X-Upload-Token cron 旁路）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas_api import RestockSuppressedEntry, RestockSuppressedList


def test_suppressed_entry_accepts_full_and_null_reason():
    e = RestockSuppressedEntry.model_validate(
        {"skipped_at": "2026-06-10 09:00:00", "reason": None, "days_left": 4}
    )
    assert e.days_left == 4


def test_suppressed_entry_rejects_extra_key():
    with pytest.raises(ValidationError):
        RestockSuppressedEntry.model_validate(
            {"skipped_at": "x", "reason": None, "days_left": 1, "junk": 1}
        )


def test_suppressed_list_empty_ok():
    m = RestockSuppressedList.model_validate({"ok": True, "items": {}})
    assert m.items == {}


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def test_api_restock_suppressed_shape(real_app):
    resp = real_app.test_client().get(
        "/api/restock/suppressed", headers={"X-Upload-Token": "test-token-123"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["items"], dict)
