"""app.db 单一 engine 真源测试。"""

from sqlalchemy import text


def test_get_engine_caches_by_effective_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db

    db.reset_engine(tmp_path / "a.db")
    e1 = db.get_engine()
    e2 = db.get_engine()
    assert e1 is e2  # 同 URL 命中缓存


def test_reset_engine_switches_db_and_disposes(monkeypatch, tmp_path):
    """reset 到 A 写数据 → reset 到 B：B 看不到 A 的数据，且 effective URL 变化。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db

    url_a = db.reset_engine(tmp_path / "a.db")
    db.ensure_db()
    with db.get_session() as s:
        s.execute(text("CREATE TABLE t (x INTEGER)"))
        s.execute(text("INSERT INTO t VALUES (1)"))

    url_b = db.reset_engine(tmp_path / "b.db")
    db.ensure_db()
    assert url_a != url_b
    with db.get_session() as s:
        exists = s.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='t'")
        ).first()
        assert exists is None


def test_sqlite_uses_nullpool(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from sqlalchemy.pool import NullPool

    from app import db

    db.reset_engine(tmp_path / "a.db")
    assert isinstance(db.get_engine().pool, NullPool)


def test_get_sqlite_path_returns_db_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db

    db.reset_engine(tmp_path / "x.db")
    assert db.get_sqlite_path().endswith("x.db")


def test_get_sqlite_path_raises_for_non_sqlite(monkeypatch):
    import pytest

    from app import db

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost/db")
    db.reset_engine()
    with pytest.raises(RuntimeError, match="requires sqlite backend"):
        db.get_sqlite_path()


def test_db_reset_engine_no_stale_across_layers(monkeypatch, tmp_path):
    """reset 到 A 写 user → reset 到 B：db / stockpile_db / models 三层都查 B，看不到 A。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db
    from app.models import User, get_session
    from app.repositories import stockpile_db

    # A 库：建 schema + 插一个 user
    db.reset_engine(tmp_path / "A.db")
    db.ensure_db()
    with db.get_session() as s:
        s.add(
            User(
                username="alice",
                password_hash="x",
                display_name="A",
                theme="light",
                role="admin",
            )
        )

    # 切到 B 库
    url_b = db.reset_engine(tmp_path / "B.db")
    db.ensure_db()
    assert url_b.endswith("B.db")

    # ① db.get_engine() 反映新 URL
    assert str(db.get_engine().url).endswith("B.db")
    # ② db.get_session() 查 B（无 alice）
    with db.get_session() as s:
        assert s.query(User).count() == 0
    # ③ stockpile_db._session() 也查 B
    with stockpile_db._session() as s:
        assert s.query(User).count() == 0
    # ④ models.get_session() lazy wrapper 也查 B
    with get_session() as s:
        assert s.query(User).count() == 0
