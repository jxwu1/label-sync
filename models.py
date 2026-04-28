"""SQLAlchemy 声明式 ORM 模型层（schema 单源）。

阶段 1.3 起：本模块的 Base.metadata 是 schema 唯一来源。
- stockpile_db._SCHEMA / _ensure_schema / _migrate_schema 已删除
- ensure_db() 通过 Base.metadata.create_all(engine) 建表，幂等
- 新增字段直接改 ORM 类 + alembic revision --autogenerate

使用方式：
    from models import Stockpile, StockpileChange, get_session
    with get_session() as session:
        rows = session.query(Stockpile).limit(10).all()
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import (
    Index,
    Integer,
    Text,
    create_engine,
    event,
    text,
)
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
    __table_args__ = (
        Index("idx_stockpile_barcode", "product_barcode"),
        Index("idx_stockpile_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_barcode: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    product_model: Mapped[str] = mapped_column(Text, nullable=False)
    stockpile_location: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    extra: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'{}'"))
    source: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("'system_export'")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("(datetime('now','localtime'))")
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("(datetime('now','localtime'))")
    )


class StockpileChange(Base):
    __tablename__ = "stockpile_changes"
    __table_args__ = (Index("idx_changes_barcode", "product_barcode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_barcode: Mapped[str] = mapped_column(Text, nullable=False)
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    change_type: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("(datetime('now','localtime'))")
    )


class SchemaMeta(Base):
    __tablename__ = "schema_meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


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
