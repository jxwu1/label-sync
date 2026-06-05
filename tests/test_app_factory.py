"""Flask app factory startup behavior tests."""

import importlib
import sys

from app.models import User, get_session


def _user_count() -> int:
    with get_session() as s:
        return s.query(User).count()


def test_importing_server_does_not_create_app_or_seed_users():
    sys.modules.pop("server", None)

    server = importlib.import_module("server")

    assert not hasattr(server, "app")
    assert _user_count() == 0


def test_create_app_can_skip_auth_seed():
    from server import create_app

    create_app(seed_auth=False, prewarm=False)

    assert _user_count() == 0


def test_create_app_seeds_default_users_when_requested():
    from server import create_app

    create_app(seed_auth=True, prewarm=False)

    with get_session() as s:
        users = {u.username: u.role for u in s.query(User).order_by(User.username)}

    assert users == {"admin": "admin", "pda": "scanner"}
