"""GET /api/briefing/data — schema 校验 + 与旧端点数据一致（spec §6）。"""

from __future__ import annotations

import pytest


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _get(app, path):
    return app.test_client().get(path, headers={"X-Upload-Token": "test-token-123"})


def test_api_briefing_data_matches_schema(real_app):
    r = _get(real_app, "/api/briefing/data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert set(body["cards"]) == {
        "sales_health",
        "restock_risk",
        "stockout_impact",
        "overstock_risk",
        "data_health",
    }
    assert set(body["actions"]) == {"restock", "follow_up", "review_anomalies"}


def test_api_briefing_consistent_with_legacy(real_app):
    new = _get(real_app, "/api/briefing/data").get_json()
    old = _get(real_app, "/briefing/data").get_json()
    # generated_at 是时间戳必然不同，其余字段必须一致（验收 #2 的测试态版本）
    for k in ("ok", "data_week", "data_week_complete", "cards", "actions"):
        assert new[k] == old[k], k
