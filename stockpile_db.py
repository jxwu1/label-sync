import json
import sqlite3

import pandas as pd

from config import CONFIG

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


class Source:
    SYSTEM_EXPORT = "system_export"
    USER_CORRECTION = "user_correction"
    SCAN_IMPORT = "scan_import"


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


def _log_change(
    conn: sqlite3.Connection,
    barcode: str,
    field: str,
    old_val: str | None,
    new_val: str | None,
    change_type: str,
) -> None:
    conn.execute(
        "INSERT INTO stockpile_changes (product_barcode, field_name, old_value, new_value, change_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (barcode, field, old_val, new_val, change_type),
    )


def _upsert(
    conn: sqlite3.Connection,
    barcode: str,
    model: str,
    location: str,
    extra: dict,
    source: str,
    log_changes: bool = True,
) -> None:
    existing = conn.execute(
        "SELECT product_model, stockpile_location, is_active FROM stockpile WHERE product_barcode = ?",
        (barcode,),
    ).fetchone()
    extra_json = json.dumps(extra, ensure_ascii=False)
    if existing:
        if log_changes:
            if existing["product_model"] != model:
                _log_change(conn, barcode, "product_model", existing["product_model"], model, "update")
            if existing["stockpile_location"] != location:
                _log_change(
                    conn,
                    barcode,
                    "stockpile_location",
                    existing["stockpile_location"],
                    location,
                    "update",
                )
            if existing["is_active"] != 1:
                _log_change(conn, barcode, "is_active", str(existing["is_active"]), "1", "reactivate")
        conn.execute(
            "UPDATE stockpile SET product_model=?, stockpile_location=?, is_active=1, source=?, extra=?, "
            "updated_at=datetime('now','localtime') WHERE product_barcode=?",
            (model, location, source, extra_json, barcode),
        )
        return

    conn.execute(
        "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, is_active, extra, source) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (barcode, model, location, extra_json, source),
    )
    if log_changes:
        _log_change(conn, barcode, "product_barcode", None, barcode, "insert")


def _deactivate_missing_records(conn: sqlite3.Connection, active_barcodes: set[str]) -> None:
    rows = list(conn.execute("SELECT product_barcode FROM stockpile WHERE is_active = 1"))
    for row in rows:
        barcode = row["product_barcode"]
        if barcode in active_barcodes:
            continue
        _log_change(conn, barcode, "is_active", "1", "0", "deactivate")
        conn.execute(
            "UPDATE stockpile SET is_active=0, updated_at=datetime('now','localtime') WHERE product_barcode=?",
            (barcode,),
        )


def _sync_export_dataframe(df: pd.DataFrame) -> int:
    extra_cols = _extra_cols(df)
    synced = 0
    active_barcodes: set[str] = set()
    with _connect() as conn:
        for _, row in df.iterrows():
            normalized = _normalize_row(row, extra_cols)
            if not normalized:
                continue
            barcode, model, location, extra = normalized
            active_barcodes.add(barcode)
            _upsert(conn, barcode, model, location, extra, Source.SYSTEM_EXPORT, log_changes=True)
            synced += 1
        _deactivate_missing_records(conn, active_barcodes)
    return synced


def is_initialized() -> bool:
    return count_records() > 0


def count_records() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM stockpile WHERE is_active = 1")
        return cur.fetchone()[0]


def query_by_barcode(barcode: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
    return dict(row) if row else None


def query_all_as_system_records() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT product_barcode, product_model, stockpile_location FROM stockpile WHERE is_active = 1"
        )
        barcode_model_map: dict[str, str] = {}
        system_records: dict[str, dict[str, str]] = {}
        for row in cur:
            barcode = row["product_barcode"]
            barcode_model_map[barcode] = row["product_model"]
            system_records[barcode] = {
                "model": row["product_model"],
                "stockpile_location": row["stockpile_location"],
            }
    return barcode_model_map, system_records


def query_all_barcodes_set() -> set[str]:
    with _connect() as conn:
        cur = conn.execute("SELECT product_barcode FROM stockpile WHERE is_active = 1")
        return {row["product_barcode"] for row in cur}


def list_inactive_records(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM stockpile WHERE is_active = 0 "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur]


def list_changes(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM stockpile_changes ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur]


def search_stockpile(keyword: str, limit: int = 50) -> list[dict]:
    pattern = f"%{keyword}%"
    with _connect() as conn:
        cur = conn.execute(
            "SELECT product_barcode, product_model, stockpile_location, is_active, source, updated_at "
            "FROM stockpile "
            "WHERE is_active = 1 AND (product_barcode LIKE ? OR product_model LIKE ?) "
            "ORDER BY product_barcode LIMIT ?",
            (pattern, pattern, limit),
        )
        return [dict(row) for row in cur]


def insert_or_update(
    barcode: str,
    model: str,
    location: str,
    source: str = Source.USER_CORRECTION,
    extra: dict | None = None,
) -> None:
    with _connect() as conn:
        _upsert(conn, barcode, model, location, extra or {}, source, log_changes=True)


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
        if local["model"] != export["product_model"] or local["stockpile_location"] != export["stockpile_location"]:
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
