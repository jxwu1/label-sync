"""全局测试夹具：DB 隔离。

autouse `_isolate_db`：每个测试用独立 tmp sqlite，绝不碰真实库 / PG。
只负责隔离，不做任何 seed——每个测试自己 seed。
`db_path` fixture：唯一裸 sqlite3 写入入口，与 SQLAlchemy engine 指向同一文件。
"""

import pytest


@pytest.fixture
def db_path(tmp_path):
    """per-test tmp sqlite 路径；裸 sqlite3 写入必须用它。"""
    return tmp_path / "stockpile.db"


@pytest.fixture(autouse=True)
def _isolate_db(db_path, monkeypatch):
    # 关键：清掉 DATABASE_URL，否则本地 dev.ps1 设了 PG 会直连 PG 而非 tmp。
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db

    db.reset_engine(db_path)
    db.ensure_db()
    yield
    db.reset_engine(db_path)  # 收尾 dispose，防止 tmp 文件句柄泄漏
