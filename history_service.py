"""货号历史 service。

只读访问 stockpile / stockpile_changes 表。
"""
import sqlite3
from datetime import datetime
from typing import Optional

import stockpile_db


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(stockpile_db.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def find_record(query: str) -> Optional[dict]:
    """精确匹配 product_model 或 product_barcode（两列均 UNIQUE）。

    返回当前主表行的 dict，或 None。
    """
    q = (query or "").strip()
    if not q:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT product_barcode, product_model, stockpile_location, is_active, "
            "       source, created_at, updated_at "
            "FROM stockpile "
            "WHERE product_barcode = ? OR product_model = ? "
            "LIMIT 1",
            (q, q),
        ).fetchone()
    if row is None:
        return None
    return {
        "barcode": row["product_barcode"],
        "model": row["product_model"],
        "location": row["stockpile_location"],
        "is_active": bool(row["is_active"]),
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
