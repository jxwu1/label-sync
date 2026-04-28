"""SQLAlchemy 声明式 ORM 模型层。

阶段 1.0 起步用了 automap_base 反射现有 stockpile.db，导致 import 时强依赖
DB 存在，与测试 fixture 冲突（fixture 在 import 前已 patch CONFIG 指向空目录）。
1.2 阶段切回声明式：schema 写在代码里，与 stockpile_db._SCHEMA 字符串保持手动一致。
1.3 阶段会删 _SCHEMA，由 Alembic 用本模块的 metadata 自动 autogenerate。

使用方式：
    from models import Stockpile, StockpileChange, get_session
    with get_session() as session:
        rows = session.query(Stockpile).limit(10).all()
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import Integer, String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from config import CONFIG

DB_URL = f"sqlite:///{CONFIG.stockpile_db}"

_engine: Engine = create_engine(DB_URL, future=True)


@event.listens_for(_engine, "connect")
def _enable_wal(dbapi_conn, _) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


class Base(DeclarativeBase):
    pass


class Stockpile(Base):
    __tablename__ = "stockpile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_barcode: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    product_model: Mapped[str] = mapped_column(String, nullable=False)
    stockpile_location: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extra: Mapped[Optional[str]] = mapped_column(String, default="{}")
    source: Mapped[Optional[str]] = mapped_column(String, default="system_export")
    created_at: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[Optional[str]] = mapped_column(String)


class StockpileChange(Base):
    __tablename__ = "stockpile_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_barcode: Mapped[str] = mapped_column(String, nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(String)
    new_value: Mapped[Optional[str]] = mapped_column(String)
    change_type: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[Optional[str]] = mapped_column(String)


class SchemaMeta(Base):
    __tablename__ = "schema_meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)


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
