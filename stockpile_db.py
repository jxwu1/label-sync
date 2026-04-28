import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from config import CONFIG
from models import Stockpile, StockpileChange

DB_PATH = CONFIG.stockpile_db
SCHEMA_VERSION = 2


_SCHEMA = """
    CREATE TABLE IF NOT EXISTS stockpile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_barcode TEXT NOT NULL UNIQUE,
        product_model TEXT NOT NULL,
        stockpile_location TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        extra TEXT DEFAULT '{}',
        source TEXT DEFAULT 'system_export',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS stockpile_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_barcode TEXT NOT NULL,
        field_name TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        change_type TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stockpile_barcode ON stockpile(product_barcode);
    CREATE INDEX IF NOT EXISTS idx_changes_barcode ON stockpile_changes(product_barcode);
"""


_KNOWN_COLS = frozenset({"product_barcode", "product_model", "stockpile_location"})

_STOCKPILE_DICT_COLS = (
    "id", "product_barcode", "product_model", "stockpile_location",
    "is_active", "extra", "source", "created_at", "updated_at",
)
_CHANGE_DICT_COLS = (
    "id", "product_barcode", "field_name", "old_value", "new_value",
    "change_type", "created_at",
)

_ACTIVE = 1
_INACTIVE = 0


class Source:
    SYSTEM_EXPORT = "system_export"
    USER_CORRECTION = "user_correction"
    SCAN_IMPORT = "scan_import"


# === Schema bootstrap (raw sqlite3) ===
# 阶段 1.3 会用 Alembic 替代下面这一节；目前 _SCHEMA 与 stamp 后的 baseline 一致。

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _migrate_schema(conn)
    return conn


def ensure_db() -> None:
    with _connect():
        pass


def _ensure_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(stockpile)")}
    if "is_active" not in columns:
        conn.execute("ALTER TABLE stockpile ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stockpile_active ON stockpile(is_active)")


def _read_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def _write_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(version),),
    )


def _migrate_schema(conn: sqlite3.Connection) -> None:
    _ensure_schema(conn)
    current_version = _read_schema_version(conn)
    if current_version < SCHEMA_VERSION:
        _write_schema_version(conn, SCHEMA_VERSION)


def get_schema_version() -> int:
    with _connect() as conn:
        return _read_schema_version(conn)


# === ORM engine / session ===
# 每个 DB_PATH 缓存一个 engine；NullPool 避免 Windows 文件锁，便于测试 tearDown。

_engine_cache: dict[str, Engine] = {}


def _engine() -> Engine:
    key = str(DB_PATH)
    cached = _engine_cache.get(key)
    if cached is not None:
        return cached
    with _connect():
        pass
    engine = create_engine(f"sqlite:///{key}", future=True, poolclass=NullPool)
    _engine_cache[key] = engine
    return engine


@contextmanager
def _session() -> Iterator[Session]:
    session = Session(_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _stockpile_to_dict(obj) -> dict:
    return {col: getattr(obj, col) for col in _STOCKPILE_DICT_COLS}


def _change_to_dict(obj) -> dict:
    return {col: getattr(obj, col) for col in _CHANGE_DICT_COLS}


# === Pure helpers ===

def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    return "" if s == "nan" else s


def _extra_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in (str(c).strip() for c in df.columns) if c not in _KNOWN_COLS]


def _normalize_row(row, extra_cols: list[str]) -> tuple[str, str, str, dict] | None:
    barcode = _clean(row.get("product_barcode", ""))
    if not barcode:
        return None
    model = _clean(row.get("product_model", ""))
    location = _clean(row.get("stockpile_location", ""))
    extra = {c: _clean(row.get(c, "")) for c in extra_cols}
    return barcode, model, location, extra


# === Write path (ORM) ===

def _log_change(
    session: Session,
    barcode: str,
    field: str,
    old_val: str | None,
    new_val: str | None,
    change_type: str,
) -> None:
    session.add(StockpileChange(
        product_barcode=barcode,
        field_name=field,
        old_value=old_val,
        new_value=new_val,
        change_type=change_type,
    ))


def _upsert(
    session: Session,
    barcode: str,
    model: str,
    location: str,
    extra: dict,
    source: str,
    log_changes: bool = True,
) -> None:
    existing = session.execute(
        select(Stockpile).where(Stockpile.product_barcode == barcode)
    ).scalar_one_or_none()
    extra_json = json.dumps(extra, ensure_ascii=False)
    if existing is not None:
        if log_changes:
            if existing.product_model != model:
                _log_change(
                    session, barcode, "product_model",
                    existing.product_model, model, "update",
                )
            if existing.stockpile_location != location:
                _log_change(
                    session, barcode, "stockpile_location",
                    existing.stockpile_location, location, "update",
                )
            if existing.is_active != _ACTIVE:
                _log_change(
                    session, barcode, "is_active",
                    str(existing.is_active), str(_ACTIVE), "reactivate",
                )
        existing.product_model = model
        existing.stockpile_location = location
        existing.is_active = _ACTIVE
        existing.source = source
        existing.extra = extra_json
        existing.updated_at = func.datetime("now", "localtime")
        return

    session.add(Stockpile(
        product_barcode=barcode,
        product_model=model,
        stockpile_location=location,
        is_active=_ACTIVE,
        extra=extra_json,
        source=source,
    ))
    if log_changes:
        _log_change(session, barcode, "product_barcode", None, barcode, "insert")


def _deactivate_missing_records(session: Session, active_barcodes: set[str]) -> None:
    rows = session.execute(
        select(Stockpile).where(Stockpile.is_active == _ACTIVE)
    ).scalars().all()
    for row in rows:
        if row.product_barcode in active_barcodes:
            continue
        _log_change(
            session, row.product_barcode, "is_active",
            str(_ACTIVE), str(_INACTIVE), "deactivate",
        )
        row.is_active = _INACTIVE
        row.updated_at = func.datetime("now", "localtime")


def _sync_export_dataframe(df: pd.DataFrame) -> int:
    extra_cols = _extra_cols(df)
    synced = 0
    active_barcodes: set[str] = set()
    with _session() as session:
        for _, row in df.iterrows():
            normalized = _normalize_row(row, extra_cols)
            if not normalized:
                continue
            barcode, model, location, extra = normalized
            active_barcodes.add(barcode)
            _upsert(session, barcode, model, location, extra, Source.SYSTEM_EXPORT, log_changes=True)
            synced += 1
        _deactivate_missing_records(session, active_barcodes)
    return synced


# === Read path (ORM) ===

def is_initialized() -> bool:
    return count_records() > 0


def count_records() -> int:
    with _session() as session:
        result = session.execute(
            select(func.count()).select_from(Stockpile).where(Stockpile.is_active == _ACTIVE)
        ).scalar()
    return result or 0


def query_by_barcode(barcode: str) -> dict | None:
    with _session() as session:
        obj = session.execute(
            select(Stockpile).where(Stockpile.product_barcode == barcode)
        ).scalar_one_or_none()
        return _stockpile_to_dict(obj) if obj else None


def query_all_as_system_records() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    with _session() as session:
        rows = session.execute(
            select(
                Stockpile.product_barcode,
                Stockpile.product_model,
                Stockpile.stockpile_location,
            ).where(Stockpile.is_active == _ACTIVE)
        ).all()
    barcode_model_map: dict[str, str] = {}
    system_records: dict[str, dict[str, str]] = {}
    for barcode, model, location in rows:
        barcode_model_map[barcode] = model
        system_records[barcode] = {"model": model, "stockpile_location": location}
    return barcode_model_map, system_records


def query_all_barcodes_set() -> set[str]:
    with _session() as session:
        rows = session.execute(
            select(Stockpile.product_barcode).where(Stockpile.is_active == _ACTIVE)
        ).all()
    return {row[0] for row in rows}


def list_inactive_records(limit: int = 100) -> list[dict]:
    with _session() as session:
        objs = session.execute(
            select(Stockpile)
            .where(Stockpile.is_active == _INACTIVE)
            .order_by(Stockpile.updated_at.desc(), Stockpile.id.desc())
            .limit(limit)
        ).scalars().all()
        return [_stockpile_to_dict(o) for o in objs]


def list_changes(limit: int = 100) -> list[dict]:
    with _session() as session:
        objs = session.execute(
            select(StockpileChange).order_by(StockpileChange.id.desc()).limit(limit)
        ).scalars().all()
        return [_change_to_dict(o) for o in objs]


def search_stockpile(keyword: str, limit: int = 50) -> list[dict]:
    pattern = f"%{keyword}%"
    with _session() as session:
        rows = session.execute(
            select(
                Stockpile.product_barcode,
                Stockpile.product_model,
                Stockpile.stockpile_location,
                Stockpile.is_active,
                Stockpile.source,
                Stockpile.updated_at,
            )
            .where(Stockpile.is_active == _ACTIVE)
            .where(
                Stockpile.product_barcode.like(pattern)
                | Stockpile.product_model.like(pattern)
            )
            .order_by(Stockpile.product_barcode)
            .limit(limit)
        ).all()
    return [
        {
            "product_barcode": r[0], "product_model": r[1], "stockpile_location": r[2],
            "is_active": r[3], "source": r[4], "updated_at": r[5],
        }
        for r in rows
    ]


# === Public API ===

def insert_or_update(
    barcode: str,
    model: str,
    location: str,
    source: str = Source.USER_CORRECTION,
    extra: dict | None = None,
) -> None:
    with _session() as session:
        _upsert(session, barcode, model, location, extra or {}, source, log_changes=True)


def import_from_dataframe(df: pd.DataFrame) -> int:
    return _sync_export_dataframe(df)


def apply_export_updates(df: pd.DataFrame) -> int:
    return _sync_export_dataframe(df)


def compare_with_dataframe(df: pd.DataFrame) -> dict:
    extra_cols: list[str] = []
    export_records: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        normalized = _normalize_row(row, extra_cols)
        if not normalized:
            continue
        barcode, model, location, _ = normalized
        export_records[barcode] = {"product_model": model, "stockpile_location": location}

    _, local_records = query_all_as_system_records()
    local_barcodes = set(local_records.keys())
    export_barcodes = set(export_records.keys())

    only_local = sorted(local_barcodes - export_barcodes)
    only_export = sorted(export_barcodes - local_barcodes)

    mismatches: list[dict] = []
    for barcode in local_barcodes & export_barcodes:
        local = local_records[barcode]
        export = export_records[barcode]
        if (
            local["model"] != export["product_model"]
            or local["stockpile_location"] != export["stockpile_location"]
        ):
            mismatches.append({
                "barcode": barcode,
                "local_model": local["model"],
                "export_model": export["product_model"],
                "local_location": local["stockpile_location"],
                "export_location": export["stockpile_location"],
            })

    return {
        "total_local": len(local_barcodes),
        "total_export": len(export_barcodes),
        "only_in_local": only_local,
        "only_in_export": only_export,
        "mismatches": mismatches,
        "consistent": len(local_barcodes & export_barcodes) - len(mismatches),
    }
