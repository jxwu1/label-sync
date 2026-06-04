"""DB engine/session 单一真源。

所有 engine/session/schema bootstrap 收口于此：
- models.py 只放 Base + ORM + 兼容 wrapper(函数内 lazy import 本模块)
- stockpile_db.py / alembic/env.py / auth 经本模块取 engine/session
- 测试隔离：tests/conftest.py autouse 调 reset_engine(tmp) + ensure_db()

设计约束(见 spec)：
1. engine 按 effective URL 缓存(非仅 DB_PATH)
2. get_session 每次 new Session(不留全局 _SessionFactory)
3. reset_engine dispose 全部缓存 engine
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import CONFIG
from app.models import Base, SchemaMeta

# schema_meta.schema_version 行的目标值；与 Alembic 的 alembic_version 表是两套独立机制，
# 改 schema 时走 alembic revision，不要在这里乱加。
SCHEMA_VERSION = 2

# 默认指向 CONFIG.stockpile_db；测试经 reset_engine 重定向。
DB_PATH = CONFIG.stockpile_db

# 非线程安全(check-then-act): 并发 cache-miss 可能各建一个 engine, 多余的会被 GC(NullPool
# 不持连接, 无害)。reset_engine 仅测试用。本工具内网低并发, 暂不加锁。
_engine_cache: dict[str, Engine] = {}


def _effective_url() -> str:
    # DATABASE_URL 优先(PG)，否则回退 sqlite 文件
    return os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}"


def _build_engine(url: str) -> Engine:
    # pool 按方言：sqlite→NullPool(避线程锁/长连接状态)，其它(PG)→默认 QueuePool
    if make_url(url).get_backend_name() == "sqlite":
        engine = create_engine(url, future=True, poolclass=NullPool)
    else:
        engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_conn, _):
        # WAL 是 SQLite 专属；PG 不需要
        if engine.dialect.name != "sqlite":
            return
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def get_engine() -> Engine:
    url = _effective_url()
    cached = _engine_cache.get(url)
    if cached is not None:
        return cached
    engine = _build_engine(url)
    _engine_cache[url] = engine
    return engine


@contextmanager
def get_session() -> Iterator[Session]:
    """提供事务性 Session：正常退出自动 commit，异常 rollback，最后 close。

    注意：commit-on-exit 是契约的一部分，测试 setUp 的 seed 依赖它持久化(load-bearing)。
    """
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _bootstrap_schema_version(engine: Engine) -> None:
    with Session(engine) as session:
        meta = session.execute(
            select(SchemaMeta).where(SchemaMeta.key == "schema_version")
        ).scalar_one_or_none()
        if meta is None:
            session.add(SchemaMeta(key="schema_version", value=str(SCHEMA_VERSION)))
        elif meta.value != str(SCHEMA_VERSION):
            meta.value = str(SCHEMA_VERSION)
        session.commit()


def ensure_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _bootstrap_schema_version(engine)


def reset_engine(db_path=None) -> str:
    """重置 engine：dispose 全部缓存 + 清空 + 可选重设 DB_PATH。返回新 effective URL。"""
    global DB_PATH
    for eng in _engine_cache.values():
        eng.dispose()
    _engine_cache.clear()
    if db_path is not None:
        DB_PATH = db_path
    return _effective_url()


def get_sqlite_path() -> str:
    """raw sqlite3 连接用：从 effective URL 解析真实 sqlite 文件路径。

    必须从 effective URL 解析(而非直接返回 DB_PATH)，否则 DATABASE_URL=sqlite:///其他文件
    时, engine 指 URL 文件而裸 sqlite3 指 DB_PATH → 分裂。非 sqlite(PG) 直接报错。
    用 make_url 解析(而非切前缀)，兼容 sqlite+pysqlite:///... 等 driver 变体。
    """
    parsed = make_url(_effective_url())
    if parsed.get_backend_name() != "sqlite":
        raise RuntimeError(
            f"get_sqlite_path() requires sqlite backend; effective URL is {parsed}. "
            "Rewrite caller to use SQLAlchemy session."
        )
    if not parsed.database:
        raise RuntimeError(f"sqlite URL has no database file: {parsed}")
    return parsed.database
