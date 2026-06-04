"""读 inventory_snapshot_*.parquet 入 stockpile_inventory_snapshot 表.

幂等策略: 同 snapshot_date 整体替换 (DELETE + INSERT). 重复 import 同一份
parquet 不会爆 UNIQUE, 不会留陈旧行.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import StockpileInventorySnapshot


def import_inventory_snapshot(path: Path, session: Session) -> dict:
    """读 parquet → upsert stockpile_inventory_snapshot.

    返回 {'snapshot_date', 'rows_imported', 'rows_replaced'}.

    rows_replaced: 同 snapshot_date 此前已存在的行数 (被本次 DELETE 清除).
    """
    df = pd.read_parquet(path)
    if len(df) == 0:
        return {"snapshot_date": None, "rows_imported": 0, "rows_replaced": 0}

    if "snapshot_date" not in df.columns:
        raise ValueError("inventory parquet 缺 snapshot_date 列")
    snap_date = str(df["snapshot_date"].iloc[0])
    unique_dates = df["snapshot_date"].astype(str).unique()
    if len(unique_dates) > 1:
        raise ValueError(f"inventory parquet 同时含多个 snapshot_date: {sorted(unique_dates)}")

    result = session.execute(
        delete(StockpileInventorySnapshot).where(
            StockpileInventorySnapshot.snapshot_date == snap_date
        )
    )
    rows_replaced = result.rowcount or 0

    records = []
    for _, r in df.iterrows():
        records.append(
            {
                "snapshot_date": snap_date,
                "product_model": r["product_model"],
                "product_name_zh": _none_if_na(r.get("product_name_zh")),
                "erp_category_code": _none_if_na(r.get("erp_category_code")),
                "erp_category_raw": _none_if_na(r.get("erp_category_raw")),
                "last_purchase_at": _none_if_na(r.get("last_purchase_at")),
                "last_arrival_at": _none_if_na(r.get("last_arrival_at")),
                "qty_store": _int_or_none(r.get("qty_store")),
                "qty_total": int(r["qty_total"]),
                "reorder_min": _int_or_none(r.get("reorder_min")),
                "reorder_max": _int_or_none(r.get("reorder_max")),
                "is_discontinued_in_erp": bool(r.get("is_discontinued_in_erp", False)),
            }
        )
    session.bulk_insert_mappings(StockpileInventorySnapshot, records)

    return {
        "snapshot_date": snap_date,
        "rows_imported": len(records),
        "rows_replaced": rows_replaced,
    }


def _none_if_na(v):
    if v is None or pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


def _int_or_none(v):
    if v is None or pd.isna(v):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
