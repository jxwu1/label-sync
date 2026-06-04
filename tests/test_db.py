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
