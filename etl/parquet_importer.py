"""清洗后 parquet → DB 的导入逻辑。

定位：**一次性历史回填工具**。日常增量走 inventory_admin.py import-batch（HTML）。

设计取舍：
- 直接复用 inventory_importer.import_events，零核心逻辑改动
- mapping 接近 identity（parquet 列名已对齐内部字段名），仅需把
  customer_id/customer_name 路由到 partner_id/partner_name（sale 时），或
  supplier_id/supplier_name 路由到 partner_id/partner_name（purchase 时）
- 按 parquet 的 event_type 列拆 sale/purchase 两批，分别调 import_events
- erp_category_code 不传（importer 内部从 erp_category_raw 重新 parse，保持单源）
- session 由调用方传入，与现有 importer 习惯一致
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.importers.inventory import ImportResult, import_events
from app.models import InventoryEvent, Stockpile

_COMMON_MAPPING = {
    "event_at": "event_at",
    "product_barcode": "product_barcode",
    "qty": "qty",
    "unit_price": "unit_price",
    "discount_pct": "discount_pct",
    "document_no": "document_no",
    "shipping_doc": "shipping_doc",
    "warehouse": "warehouse",
    "erp_category_raw": "erp_category_raw",
    "product_name_zh": "product_name_zh",
    "product_name_local": "product_name_local",
}

SALE_MAPPING = {
    **_COMMON_MAPPING,
    "customer_id": "partner_id",
    "customer_name": "partner_name",
}

PURCHASE_MAPPING = {
    **_COMMON_MAPPING,
    "supplier_id": "partner_id",
    "supplier_name": "partner_name",
}


def _update_last_purchase_unit_price(barcodes: set[str], session: Session) -> int:
    """对每个 barcode 重新查 DB 最近一次有效采购 (qty>0 + unit_price>0) 的折后净价,
    写回 stockpile.last_purchase_unit_price.

    跨方言: 用普通 SELECT ORDER BY DESC LIMIT 1 per barcode, 不依赖 DISTINCT ON.
    barcodes 来自这次 import 的 purchase batch, 避免全表扫.
    返回更新行数."""
    if not barcodes:
        return 0
    updated = 0
    for bc in barcodes:
        row = session.execute(
            select(InventoryEvent.unit_price, InventoryEvent.discount_pct)
            .where(
                (InventoryEvent.product_barcode == bc)
                & (InventoryEvent.event_type == "purchase")
                & (InventoryEvent.qty > 0)
                & (InventoryEvent.unit_price > 0)
            )
            .order_by(InventoryEvent.event_at.desc())
            .limit(1)
        ).first()
        if row is None:
            continue
        unit_price = float(row[0])
        discount = float(row[1] or 0.0)
        net = round(unit_price * (1.0 - discount / 100.0), 4)
        result = session.execute(
            update(Stockpile)
            .where(Stockpile.product_barcode == bc)
            .values(last_purchase_unit_price=net)
        )
        if result.rowcount:
            updated += 1
    return updated


def import_dataframe(
    df: pd.DataFrame,
    session: Session,
) -> tuple[ImportResult, ImportResult]:
    """按 event_type 拆 sale/purchase，分别调 import_events。

    每次 purchase 批量 import 后, 同步回填 stockpile.last_purchase_unit_price
    (取每个 barcode 当前 DB 里最近一次 qty>0+unit_price>0 的 purchase event 净价).

    Args:
        df: cleaned parquet 的 DataFrame。必须含 event_type 列。
        session: SQLAlchemy session（调用方负责 commit）

    Returns:
        (sale_result, purchase_result)。任一为空批返回 ImportResult() 占位。
    """
    if "event_type" not in df.columns:
        raise ValueError("缺 event_type 列，无法拆 sale/purchase")

    sale_df = df[df["event_type"] == "sale"]
    purchase_df = df[df["event_type"] == "purchase"]

    sale_result = ImportResult()
    purchase_result = ImportResult()

    if len(sale_df) > 0:
        sale_result = import_events(sale_df, SALE_MAPPING, "sale", session)
    if len(purchase_df) > 0:
        purchase_result = import_events(purchase_df, PURCHASE_MAPPING, "purchase", session)
        # 回填 stockpile.last_purchase_unit_price (这次 batch 涉及的 barcode)
        affected = set(purchase_df["product_barcode"].dropna().astype(str))
        _update_last_purchase_unit_price(affected, session)

    return sale_result, purchase_result


def import_cleaned_parquet(
    src: Path | str,
    session: Session,
) -> tuple[ImportResult, ImportResult]:
    """读 cleaned parquet 路径，拆批落库。

    Args:
        src: cleaned parquet 路径
        session: SQLAlchemy session（调用方负责 commit）

    Returns:
        (sale_result, purchase_result)
    """
    df = pd.read_parquet(Path(src))
    return import_dataframe(df, session)
