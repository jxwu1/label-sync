"""auto_category 批量重算 (split-only 拆分自 analytics)。"""

from __future__ import annotations

import time
from collections import Counter
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update

from app.models import InventoryEvent, Stockpile
from app.repositories import stockpile_db
from app.services.analytics._shared import _today
from app.utils.categorizer import classify_from_sales


def recompute_categories(as_of: date | None = None) -> dict[str, Any]:
    """批量重算所有 active SKU 的 auto_category，写回 stockpile。

    单次 SQL 拉所有销售事件 → 内存 group by barcode → 跑 categorizer → 批量 UPDATE。
    5 万 SKU + 几十万事件应该在数秒内完成。

    返回 {'computed': N, 'by_category': {...}, 'duration_s': T}。
    """
    as_of = as_of or _today()
    started = time.time()
    computed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with stockpile_db._session() as session:
        active_barcodes = [
            r[0]
            for r in session.execute(
                select(Stockpile.product_barcode).where(Stockpile.is_active == 1)
            ).all()
        ]
        sales_rows = session.execute(
            select(
                InventoryEvent.product_barcode,
                InventoryEvent.event_at,
                InventoryEvent.qty,
            ).where(InventoryEvent.event_type == "sale")
        ).all()

        sales_by_bc: dict[str, list[tuple[str, int]]] = {}
        for bc, at, qty in sales_rows:
            sales_by_bc.setdefault(bc, []).append((at, qty))

        counts: Counter[str] = Counter()
        for bc in active_barcodes:
            cat = classify_from_sales(sales_by_bc.get(bc, []), as_of)
            counts[cat] += 1
            session.execute(
                update(Stockpile)
                .where(Stockpile.product_barcode == bc)
                .values(auto_category=cat, auto_category_computed_at=computed_at)
            )
        session.commit()

    return {
        "computed": len(active_barcodes),
        "by_category": dict(counts),
        "duration_s": round(time.time() - started, 2),
    }
