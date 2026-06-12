"""API 401 认证契约 — spec §6 v3（完整 init_auth 闸集成测试）。"""

from __future__ import annotations

import pytest


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def test_unauthenticated_api_returns_json_401(real_app):
    r = real_app.test_client().get("/api/briefing/data")
    assert r.status_code == 401
    assert r.content_type.startswith("application/json")
    assert r.get_json() == {"error": "unauthenticated"}


def test_unauthenticated_page_still_redirects(real_app):
    r = real_app.test_client().get("/briefing")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_wrong_cron_token_still_loud_401(real_app):
    r = real_app.test_client().get("/briefing/data", headers={"X-Upload-Token": "wrong"})
    assert r.status_code == 401  # 响亮 4xx，绝不 302（#5 静默空转语义）


def test_correct_cron_token_passes_gate(real_app):
    r = real_app.test_client().get("/briefing/data", headers={"X-Upload-Token": "test-token-123"})
    assert r.status_code == 200
