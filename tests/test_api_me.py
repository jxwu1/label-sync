"""/api/me：壳用的当前用户信息（display_name + is_admin）。"""

import pytest

from app.models import User
from app.auth import hash_password
from app.repositories import stockpile_db


@pytest.fixture
def client():
    """无 seed 的纯净 app + test_client；session cookie 在同一 client 内自动保持。"""
    from server import create_app

    app = create_app(seed_auth=False, prewarm=False)
    app.config["TESTING"] = True
    return app.test_client()


def _mk_user(username, role, display_name=None):
    with stockpile_db._session() as s:
        u = User(username=username, password_hash=hash_password("x"), role=role)
        if display_name is not None:
            u.display_name = display_name
        s.add(u)
        s.commit()


def _login(client, username):
    return client.post("/login", data={"username": username, "password": "x"})


def test_me_admin(client):
    _mk_user("boss", "admin", display_name="老板")
    _login(client, "boss")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.get_json() == {"display_name": "老板", "is_admin": True}


def test_me_display_name_falls_back_to_username(client):
    _mk_user("plainadmin", "admin", display_name=None)
    _login(client, "plainadmin")
    assert (r := client.get("/api/me"))
    assert r.get_json()["display_name"] == "plainadmin"


def test_me_scanner_is_not_admin_and_not_redirected(client):
    """scanner 调 /api/me 必须拿 JSON（不被 302 跳 PDA）。"""
    _mk_user("scan1", "scanner")
    _login(client, "scan1")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.get_json()["is_admin"] is False


def test_me_unauthenticated_returns_json_401(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}
