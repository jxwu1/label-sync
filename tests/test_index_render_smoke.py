"""主 SPA index.html 渲染冒烟测试。

2026-06-15 事故: 退役旧简报页时删了 partials/_page_briefing.html, 但 index.html
的 include 半残提交未删 → 生产渲染 / 时 jinja2 TemplateNotFound → 500。当时 CI
无任何测试渲染 index.html, 漏检。本测试堵这个洞: 认证态 GET / 必须 200(任何
断 include / 模板错都会在此变红), 且侧栏保留通往 /ui/briefing 的入口。
"""

import pytest


@pytest.fixture
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _login(app, client):
    """用 seed 的 admin 建认证 session(免走表单)。"""
    with app.app_context():
        from app.db import get_session
        from app.models import User

        with get_session() as s:
            admin = s.query(User).filter_by(role="admin").first()
            aid = str(admin.id)
    with client.session_transaction() as sess:
        sess["_user_id"] = aid
        sess["_fresh"] = True


def test_index_renders_for_authed_user(real_app):
    """认证态主页渲染 200 — 删 partial / 断 include 会 TemplateNotFound→500, 此处即红。"""
    client = real_app.test_client()
    _login(real_app, client)
    r = client.get("/")
    assert r.status_code == 200


def test_index_keeps_briefing_link_to_ui(real_app):
    """简报已迁 Vue /ui/briefing: 侧栏保留跳转入口, 防再次"简报消失"。"""
    client = real_app.test_client()
    _login(real_app, client)
    html = client.get("/").get_data(as_text=True)
    assert "/ui/briefing" in html
