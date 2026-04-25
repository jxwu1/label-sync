import json
import sqlite3

import pandas as pd

from config import CONFIG

DB_PATH = CONFIG.stockpile_db


_SCHEMA = """
    CREATE TABLE IF NOT EXISTS stockpile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_barcode TEXT NOT NULL UNIQUE,
        product_model TEXT NOT NULL,
        stockpile_location TEXT NOT NULL,
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
    CREATE INDEX IF NOT EXISTS idx_stockpile_barcode ON stockpile(product_barcode);
    CREATE INDEX IF NOT EXISTS idx_changes_barcode ON stockpile_changes(product_barcode);
"""


_KNOWN_COLS = frozenset({"product_barcode", "product_model", "stockpile_location"})


class Source:
    SYSTEM_EXPORT = "system_export"
    USER_CORRECTION = "user_correction"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def ensure_db() -> None:
    """显式触发 schema 创建（一般不需要调用，_connect 自动会做）。"""
    with _connect():
        pass


def _clean(value) -> str:
    """规范化 DataFrame 单元值：处理 NaN、float、空白；统一返回 str。"""
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
    """返回 (barcode, model, location, extra)；barcode 为空时返回 None。"""
    barcode = _clean(row.get("product_barcode", ""))
    if not barcode:
        return None
    model = _clean(row.get("product_model", ""))
    location = _clean(row.get("stockpile_location", ""))
    extra = {c: _clean(row.get(c, "")) for c in extra_cols}
    return barcode, model, location, extra


def _log_change(conn: sqlite3.Connection, barcode: str, field: str,
                old_val: str | None, new_val: str | None, change_type: str) -> None:
    conn.execute(
        "INSERT INTO stockpile_changes (product_barcode, field_name, old_value, new_value, change_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (barcode, field, old_val, new_val, change_type),
    )


def _upsert(conn: sqlite3.Connection, barcode: str, model: str, location: str,
            extra: dict, source: str, log_changes: bool = True) -> None:
    """写入或更新一条 stockpile 记录。log_changes=True 时记录变更。"""
    existing = conn.execute(
        "SELECT product_model, stockpile_location FROM stockpile WHERE product_barcode = ?",
        (barcode,),
    ).fetchone()
    extra_json = json.dumps(extra, ensure_ascii=False)
    if existing:
        if log_changes:
            if existing["product_model"] != model:
                _log_change(conn, barcode, "product_model", existing["product_model"], model, "update")
            if existing["stockpile_location"] != location:
                _log_change(conn, barcode, "stockpile_location", existing["stockpile_location"], location, "update")
        conn.execute(
            "UPDATE stockpile SET product_model=?, stockpile_location=?, source=?, extra=?, "
            "updated_at=datetime('now','localtime') WHERE product_barcode=?",
            (model, location, source, extra_json, barcode),
        )
    else:
        conn.execute(
            "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, extra, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (barcode, model, location, extra_json, source),
        )
        if log_changes:
            _log_change(conn, barcode, "product_barcode", None, barcode, "insert")


def is_initialized() -> bool:
    return count_records() > 0


def count_records() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM stockpile")
        return cur.fetchone()[0]


def query_by_barcode(barcode: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
    return dict(row) if row else None


def query_all_as_system_records() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    with _connect() as conn:
        cur = conn.execute("SELECT product_barcode, product_model, stockpile_location FROM stockpile")
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
        cur = conn.execute("SELECT product_barcode FROM stockpile")
        return {row["product_barcode"] for row in cur}


def insert_or_update(barcode: str, model: str, location: str,
                     source: str = Source.USER_CORRECTION, extra: dict | None = None) -> None:
    with _connect() as conn:
        _upsert(conn, barcode, model, location, extra or {}, source, log_changes=True)


def update_location(barcode: str, new_location: str) -> None:
    with _connect() as conn:
        existing = conn.execute(
            "SELECT stockpile_location FROM stockpile WHERE product_barcode = ?", (barcode,)
        ).fetchone()
        if not existing:
            return
        old_location = existing["stockpile_location"]
        if old_location == new_location:
            return
        _log_change(conn, barcode, "stockpile_location", old_location, new_location, "update")
        conn.execute(
            "UPDATE stockpile SET stockpile_location=?, source=?, updated_at=datetime('now','localtime') "
            "WHERE product_barcode=?",
            (new_location, Source.USER_CORRECTION, barcode),
        )


def import_from_dataframe(df: pd.DataFrame) -> int:
    extra_cols = _extra_cols(df)
    inserted = 0
    with _connect() as conn:
        for _, row in df.iterrows():
            normalized = _normalize_row(row, extra_cols)
            if not normalized:
                continue
            barcode, model, location, extra = normalized
            _upsert(conn, barcode, model, location, extra, Source.SYSTEM_EXPORT, log_changes=True)
            inserted += 1
    return inserted


def apply_export_updates(df: pd.DataFrame) -> int:
    extra_cols = _extra_cols(df)
    updated = 0
    with _connect() as conn:
        for _, row in df.iterrows():
            normalized = _normalize_row(row, extra_cols)
            if not normalized:
                continue
            barcode, model, location, extra = normalized
            _upsert(conn, barcode, model, location, extra, Source.SYSTEM_EXPORT, log_changes=True)
            updated += 1
    return updated


def compare_with_dataframe(df: pd.DataFrame) -> dict:
    extra_cols: list[str] = []  # 比对不读 extra
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
