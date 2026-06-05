"""secret key 解析契约: 生产拒用可伪造的硬编码默认 secret.

2026-06-05 加固(codex backlog #1): auth 原来 `app.secret_key or "...dev..."`,
生产没注入时 session cookie 可被伪造. 改为从 FLASK_SECRET_KEY 读;
debug 本地回退 dev 默认; 生产(无 debug)缺失则 fail-fast 拒启.
"""

import pytest

from app.auth import _resolve_secret_key


def test_env_secret_takes_precedence(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "from-env-value")

    assert _resolve_secret_key(debug=False) == "from-env-value"
    # debug 与否都优先用 env 注入值
    assert _resolve_secret_key(debug=True) == "from-env-value"


def test_debug_falls_back_to_dev_secret_when_unset(monkeypatch):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    secret = _resolve_secret_key(debug=True)

    assert secret  # 非空, 本地可用
    assert isinstance(secret, str)


def test_production_without_secret_refuses_to_start(monkeypatch):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="FLASK_SECRET_KEY"):
        _resolve_secret_key(debug=False)
