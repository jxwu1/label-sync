"""简报路由集成测试。"""

from unittest import mock

import pytest
from flask import Flask
from flask_login import LoginManager

from app.routes.briefing import bp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    # flask-login setup so current_user is accessible in templates
    lm = LoginManager(app)  # noqa: F841
    app.register_blueprint(bp)
    return app.test_client()


def test_briefing_data_ok(client):
    resp = client.get("/briefing/data")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert set(data["cards"]) == {
        "sales_health",
        "restock_risk",
        "stockout_impact",
        "overstock_risk",
        "data_health",
    }
    assert set(data["actions"]) == {"restock", "follow_up", "review_anomalies"}


def test_briefing_data_system_failure_returns_500(client, monkeypatch):
    from app.services import briefing

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(briefing, "build_briefing", boom)
    # 模拟生产: 异常交给 Flask 自己的 500 处理, 而非测试模式直接上抛
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    resp = client.get("/briefing/data")
    assert resp.status_code == 500


def test_briefing_data_500_does_not_leak_sql(client, monkeypatch):
    """review #6: 路由不准吞 SQLAlchemyError 再把 str(exc)(含 SQL 语句)发给客户端。"""
    from sqlalchemy.exc import ProgrammingError

    from app.services import briefing

    def schema_boom(*a, **k):
        raise ProgrammingError(
            "SELECT secret_col FROM hidden_table", {}, Exception("column does not exist")
        )

    monkeypatch.setattr(briefing, "build_briefing", schema_boom)
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    resp = client.get("/briefing/data")
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert "hidden_table" not in body
    assert "column does not exist" not in body
