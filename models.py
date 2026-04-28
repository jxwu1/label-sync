"""
SQLAlchemy ORM 映射层（automap 反射现有 stockpile.db）。

阶段 1.0 准备文件：本模块只做反射 + 引擎工厂，不引入业务逻辑。
后续阶段会用本模块导出的 Stockpile / StockpileChange 类替换 stockpile_db.py
里 raw sqlite3 + 字符串 SQL 的实现。

使用方式：
    from models import Stockpile, StockpileChange, get_session
    with get_session() as session:
        rows = session.query(Stockpile).limit(10).all()
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session, sessionmaker

from config import CONFIG

DB_URL = f"sqlite:///{CONFIG.stockpile_db}"

_engine: Engine = create_engine(DB_URL, future=True)


@event.listens_for(_engine, "connect")
def _enable_wal(dbapi_conn, _) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


Base = automap_base()
Base.prepare(autoload_with=_engine)

Stockpile = Base.classes.stockpile
StockpileChange = Base.classes.stockpile_changes
SchemaMeta = Base.classes.schema_meta

_SessionFactory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine() -> Engine:
    return _engine
