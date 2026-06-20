"""Phase 4c：旧书签 /?page=history 服务端 302 兜底到 /ui/history。

认证套路照搬 tests/test_index_render_smoke.py（seed admin + session_transaction）。
"""

from urllib.parse import parse_qs, urlparse

import pytest


@pytest.fixture
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _login(app, client):
    with app.app_context():
        from app.db import get_session
        from app.models import User

        with get_session() as s:
            admin = s.query(User).filter_by(role="admin").first()
            aid = str(admin.id)
    with client.session_transaction() as sess:
        sess["_user_id"] = aid
        sess["_fresh"] = True


def test_page_history_redirects_to_vue(real_app):
    client = real_app.test_client()
    _login(real_app, client)
    resp = client.get("/?page=history")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/ui/history"


def test_root_and_other_pages_not_redirected(real_app):
    client = real_app.test_client()
    _login(real_app, client)
    assert client.get("/").status_code == 200
    assert client.get("/?page=main").status_code == 200


def test_unauthenticated_history_redirects_to_login_preserving_next(real_app):
    """两段独立断言（非端到端表单回跳）：
    (a) 未登录访问 /?page=history → 登录闸 302 到 /login，next 保留 page=history；
    (b) 有会话后访问 /?page=history → 302 到 /ui/history。
    注：真实表单登录后由 SPA 客户端读取 next 跳转，超出本测试范围（用 session 注入模拟已登录）。
    """
    client = real_app.test_client()
    resp = client.get("/?page=history")  # 未登录
    assert resp.status_code == 302
    loc = urlparse(resp.headers["Location"])
    assert loc.path.endswith("/login")
    next_url = parse_qs(loc.query).get("next", [""])[0]
    assert "page=history" in next_url
    # 登录后重放原 URL
    _login(real_app, client)
    resp2 = client.get("/?page=history")
    assert resp2.status_code == 302
    assert urlparse(resp2.headers["Location"]).path == "/ui/history"
