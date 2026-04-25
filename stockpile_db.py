import json
import sqlite3
from pathlib import Path

import pandas as pd

from config import CONFIG

DB_PATH = CONFIG.stockpile_db


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_db() -> None:
    conn = _connect()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()


def is_initialized() -> bool:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT COUNT(*) FROM stockpile")
    count = cur.fetchone()[0]
    conn.close()
    return count > 0


def import_from_dataframe(df: pd.DataFrame) -> int:
    ensure_db()
    columns = [str(c).strip() for c in df.columns]
    known_cols = {"product_barcode", "product_model", "stockpile_location"}
    extra_cols = [c for c in columns if c not in known_cols]

    conn = _connect()
    inserted = 0
    for _, row in df.iterrows():
        barcode = str(row.get("product_barcode", "")).strip()
        if not barcode or barcode == "nan":
            continue
        model = str(row.get("product_model", "")).strip()
        if model == "nan":
            model = ""
        location = str(row.get("stockpile_location", "")).strip()
        if location == "nan":
            location = ""
        extra = {c: str(row.get(c, "")) for c in extra_cols}
        conn.execute(
            "INSERT OR REPLACE INTO stockpile (product_barcode, product_model, stockpile_location, extra, source, updated_at) "
            "VALUES (?, ?, ?, ?, 'system_export', datetime('now','localtime'))",
            (barcode, model, location, json.dumps(extra, ensure_ascii=False)),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def query_by_barcode(barcode: str) -> dict | None:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def query_all_as_system_records() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT product_barcode, product_model, stockpile_location FROM stockpile")
    barcode_model_map: dict[str, str] = {}
    system_records: dict[str, dict[str, str]] = {}
    for row in cur:
        barcode = row["product_barcode"]
        model = row["product_model"]
        location = row["stockpile_location"]
        barcode_model_map[barcode] = model
        system_records[barcode] = {"model": model, "stockpile_location": location}
    conn.close()
    return barcode_model_map, system_records


def query_all_barcodes_set() -> set[str]:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT product_barcode FROM stockpile")
    result = {row["product_barcode"] for row in cur}
    conn.close()
    return result


def _log_change(conn: sqlite3.Connection, barcode: str, field: str, old_val: str | None, new_val: str | None, change_type: str) -> None:
    conn.execute(
        "INSERT INTO stockpile_changes (product_barcode, field_name, old_value, new_value, change_type) VALUES (?, ?, ?, ?, ?)",
        (barcode, field, old_val, new_val, change_type),
    )


def insert_or_update(barcode: str, model: str, location: str, source: str = "user_correction", extra: dict | None = None) -> None:
    ensure_db()
    conn = _connect()
    existing = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()

    if existing:
        for field_key, field_name in [("product_model", "product_model"), ("stockpile_location", "stockpile_location")]:
            new_value = model if field_key == "product_model" else location
            old_value = existing[field_key]
            if old_value != new_value:
                _log_change(conn, barcode, field_name, old_value, new_value, "update")
        conn.execute(
            "UPDATE stockpile SET product_model=?, stockpile_location=?, source=?, extra=?, updated_at=datetime('now','localtime') WHERE product_barcode=?",
            (model, location, source, json.dumps(extra or {}, ensure_ascii=False), barcode),
        )
    else:
        conn.execute(
            "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, extra, source) VALUES (?, ?, ?, ?, ?)",
            (barcode, model, location, json.dumps(extra or {}, ensure_ascii=False), source),
        )
        _log_change(conn, barcode, "product_barcode", None, barcode, "insert")

    conn.commit()
    conn.close()


def update_location(barcode: str, new_location: str) -> None:
    ensure_db()
    conn = _connect()
    existing = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
    if not existing:
        conn.close()
        return
    old_location = existing["stockpile_location"]
    if old_location != new_location:
        _log_change(conn, barcode, "stockpile_location", old_location, new_location, "update")
        conn.execute(
            "UPDATE stockpile SET stockpile_location=?, source='user_correction', updated_at=datetime('now','localtime') WHERE product_barcode=?",
            (new_location, barcode),
        )
        conn.commit()
    conn.close()


def count_records() -> int:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT COUNT(*) FROM stockpile")
    count = cur.fetchone()[0]
    conn.close()
    return count


def compare_with_dataframe(df: pd.DataFrame) -> dict:
    ensure_db()
    local_barcodes = query_all_barcodes_set()
    columns = [str(c).strip() for c in df.columns]

    export_records: dict[str, dict[str, str]] = {}
    extra_cols = [c for c in columns if c not in {"product_barcode", "product_model", "stockpile_location"}]
    for _, row in df.iterrows():
        barcode = str(row.get("product_barcode", "")).strip()
        if not barcode or barcode == "nan":
            continue
        export_records[barcode] = {
            "product_model": str(row.get("product_model", "")).strip(),
            "stockpile_location": str(row.get("stockpile_location", "")).strip(),
        }

    export_barcodes = set(export_records.keys())

    only_local = sorted(barcode for barcode in local_barcodes if barcode not in export_barcodes)
    only_export = sorted(barcode for barcode in export_barcodes if barcode not in local_barcodes)

    mismatches: list[dict] = []
    conn = _connect()
    for barcode in local_barcodes & export_barcodes:
        local = conn.execute("SELECT product_model, stockpile_location FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
        if local is None:
            continue
        export = export_records[barcode]
        if local["product_model"] != export["product_model"] or local["stockpile_location"] != export["stockpile_location"]:
            mismatches.append({
                "barcode": barcode,
                "local_model": local["product_model"],
                "export_model": export["product_model"],
                "local_location": local["stockpile_location"],
                "export_location": export["stockpile_location"],
            })
    conn.close()

    return {
        "total_local": len(local_barcodes),
        "total_export": len(export_barcodes),
        "only_in_local": only_local,
        "only_in_export": only_export,
        "mismatches": mismatches,
        "consistent": len(local_barcodes & export_barcodes) - len(mismatches),
    }


def apply_export_updates(df: pd.DataFrame) -> int:
    ensure_db()
    columns = [str(c).strip() for c in df.columns]
    extra_cols = [c for c in columns if c not in {"product_barcode", "product_model", "stockpile_location"}]
    conn = _connect()
    updated = 0
    for _, row in df.iterrows():
        barcode = str(row.get("product_barcode", "")).strip()
        if not barcode or barcode == "nan":
            continue
        model = str(row.get("product_model", "")).strip()
        location = str(row.get("stockpile_location", "")).strip()
        extra = {c: str(row.get(c, "")) for c in extra_cols}
        existing = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
        if existing:
            if existing["product_model"] != model or existing["stockpile_location"] != location:
                _log_change(conn, barcode, "product_model", existing["product_model"], model, "update")
                _log_change(conn, barcode, "stockpile_location", existing["stockpile_location"], location, "update")
            conn.execute(
                "UPDATE stockpile SET product_model=?, stockpile_location=?, extra=?, source='system_export', updated_at=datetime('now','localtime') WHERE product_barcode=?",
                (model, location, json.dumps(extra, ensure_ascii=False), barcode),
            )
        else:
            conn.execute(
                "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, extra, source) VALUES (?, ?, ?, ?, 'system_export')",
                (barcode, model, location, json.dumps(extra, ensure_ascii=False)),
            )
            _log_change(conn, barcode, "product_barcode", None, barcode, "insert")
        updated += 1
    conn.commit()
    conn.close()
    return updated
