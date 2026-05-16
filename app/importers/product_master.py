"""产品总档（product.csv）导入器。

输入：source ERP 的 product.csv（61 列），含产品全档信息（条码 / 型号 / 中希英品名 / 库位 /
分类码 / 价格 / 供应商 / 包装尺寸等）。
输出：写到 stockpile 主表 + suppliers 主档。

与 inventory_importer 区别：
- inventory_importer 处理事件流（每条 = 一笔买卖）
- product_master_importer 处理产品总档（每条 = 一个 SKU 当下完整档案）

幂等：UPSERT 模式。同 barcode 重复行（极少见，源数据噪声）first-row-wins 跳过。
"""

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy import insert as sa_insert
from sqlalchemy.orm import Session

from app.repositories import stockpile_db
from app.importers.inventory import (
    _clean_barcode_or_model,
    _clean_float,
    _clean_int,
    _clean_str,
)
from app.models import Stockpile, StockpileSnapshot, Supplier

# 默认列映射：product.csv 的列名 → 内部字段。
# 整列吃掉，复杂字段（包装尺寸 / 价格折扣等）进 stockpile.extra json。
DEFAULT_PRODUCT_MAPPING: dict[str, str] = {
    "product_barcode": "product_barcode",
    "product_model": "product_model",
    "product_description": "product_name_zh",
    "local_description": "product_name_local",
    "stockpile_location": "stockpile_location",
    "product_kind_id": "erp_category_code",
    "product_kind_name": "erp_category_raw",  # 全名（含中文+希腊语）作 raw
    "valid_grade": "manual_grade",
    "stock_price": "stock_price",
    "sale_price": "sale_price",
    "provider_id": "supplier_id",
    "provider_name": "supplier_name",
    "web_status": "web_status",  # Y/N → is_active
}

# 进 extra json 的辅助字段（包装/库存量/限额/备注/源系统 ID）
_EXTRA_FIELDS = (
    "product_id",
    "store_id",
    "store_name",
    "stockpile_shelf",
    "stockpile_quantity",
    "stockpile_remark",
    "inner_quantity",
    "middle_quantity",
    "unit_quantity",
    "pallet_quantity",
    "upper_limit",
    "lower_limit",
    "stock_limit",
    "product_color",
    "product_size",
    "product_brand",
    "en_description",
    "pack_length",
    "pack_width",
    "pack_height",
    "pack_volume",
    "net_weight",
    "gross_weight",
)


@dataclass
class ProductImportResult:
    rows_imported: int = 0  # 新建 SKU
    rows_updated: int = 0  # 已存在更新
    rows_skipped_missing_barcode: int = 0
    rows_skipped_duplicate_barcode: int = 0  # 同份 csv 里 barcode 重复 → first-row-wins
    new_suppliers: int = 0
    skipped_reasons: list[str] = field(default_factory=list)


def _is_active_from_web_status(val: Any) -> int:
    """web_status='Y' → is_active=1，其它（N / NaN / 空）→ 0。

    业务约定：web_status 表示是否在网店上架；source ERP 把下架商品的 web_status 设
    成 N 或留空。我们用这个作为 stockpile.is_active 的来源。
    """
    s = _clean_str(val)
    return 1 if s == "Y" else 0


def _row_to_extra_dict(row: pd.Series) -> dict[str, Any]:
    """把 _EXTRA_FIELDS 里的非空字段打包成 dict（用于 _upsert 的 extra 参数）。"""
    extra: dict[str, Any] = {}
    for key in _EXTRA_FIELDS:
        if key not in row.index:
            continue
        val = row[key]
        if pd.isna(val):
            continue
        if isinstance(val, (int, float)):
            if isinstance(val, float) and val.is_integer():
                extra[key] = str(int(val))
            else:
                extra[key] = str(val)
        else:
            s = str(val).strip()
            if s:
                extra[key] = s
    return extra


def _row_to_extra(row: pd.Series) -> str:
    """旧 helper 保留作 backwards-compat 兼容（已有测试在用）。直接返回 json 字符串。"""
    return json.dumps(_row_to_extra_dict(row), ensure_ascii=False)


def _upsert_supplier_from_product(session: Session, supplier_id: str, name: str) -> bool:
    """新建 supplier 返回 True，已有返回 False。不动 first/last_seen_at（这是事件
    流的字段，product 主档不该覆盖）。"""
    if not supplier_id:
        return False
    existing = session.get(Supplier, supplier_id)
    if existing is not None:
        # 名字补 NULL（人工修过的不覆盖）
        if name and not existing.supplier_name:
            existing.supplier_name = name
        return False
    session.add(Supplier(supplier_id=supplier_id, supplier_name=name or supplier_id))
    return True


def import_product_master(
    df: pd.DataFrame,
    mapping: dict[str, str],
    session: Session,
) -> ProductImportResult:
    """把 product.csv 落到 stockpile 主表 + suppliers 主档。

    所有 stockpile 写入都走 stockpile_db._upsert（统一入口），自动维护：
    - stockpile_changes（变更日志：location / model / is_active / 价格 等都有记录）
    - stockpile_locations 子表（_sync_locations）
    最后打一个 stockpile_snapshots(trigger='product_master')，让最近改动 tab
    把这次 import 当作一个独立批次显示。

    幂等：同份 csv 内部 barcode 重复 → first-row-wins，第二行起跳过 + 报告。
    """
    result = ProductImportResult()
    seen_barcodes_in_this_call: set[str] = set()

    for idx, row in df.iterrows():
        # 应用列映射 → 内部 dict
        internal: dict[str, Any] = {}
        for col_name, internal_field in mapping.items():
            if internal_field == "ignore":
                continue
            if col_name in row.index:
                internal[internal_field] = row[col_name]

        barcode = _clean_barcode_or_model(internal.get("product_barcode"))
        if not barcode:
            result.rows_skipped_missing_barcode += 1
            continue
        if barcode in seen_barcodes_in_this_call:
            result.rows_skipped_duplicate_barcode += 1
            if len(result.skipped_reasons) < 10:
                result.skipped_reasons.append(
                    f"row {idx}: barcode {barcode} 在本份 csv 已出现，跳过（first-row-wins）"
                )
            continue
        seen_barcodes_in_this_call.add(barcode)

        # 解析各字段
        model = _clean_barcode_or_model(internal.get("product_model")) or barcode
        location = _clean_str(internal.get("stockpile_location")) or ""
        name_zh = _clean_str(internal.get("product_name_zh"))
        name_local = _clean_str(internal.get("product_name_local"))
        cat_code = _clean_str(internal.get("erp_category_code"))
        cat_raw = _clean_str(internal.get("erp_category_raw"))
        grade = _clean_int(internal.get("manual_grade"))
        stock_p = _clean_float(internal.get("stock_price"))
        sale_p = _clean_float(internal.get("sale_price"))
        is_active = _is_active_from_web_status(internal.get("web_status"))
        supplier_id = _clean_str(internal.get("supplier_id"))
        supplier_name = _clean_str(internal.get("supplier_name"))
        extra_dict = _row_to_extra_dict(row)

        # 检测是新建 vs 更新（统计用）
        already_exists = (
            session.execute(
                Stockpile.__table__.select().where(Stockpile.product_barcode == barcode)
            ).first()
            is not None
        )

        # supplier upsert
        if supplier_id:
            if _upsert_supplier_from_product(session, supplier_id, supplier_name or ""):
                result.new_suppliers += 1

        # 统一走 stockpile_db._upsert：自动维护 stockpile_changes + stockpile_locations 子表
        stockpile_db._upsert(
            session,
            barcode=barcode,
            model=model,
            location=location,
            extra=extra_dict,
            source="product_master",
            is_active=is_active,
            product_name_zh=name_zh,
            product_name_local=name_local,
            erp_category_raw=cat_raw,
            erp_category_code=cat_code,
            manual_grade=grade,
            stock_price=stock_p,
            sale_price=sale_p,
        )

        if already_exists:
            result.rows_updated += 1
        else:
            result.rows_imported += 1

        # flush 让本行落库（下一行同 barcode 反查能拿到 / supplier 不重复）
        session.flush()

    # 末尾打一个 snapshot，让最近改动 tab 把这次 product master 当批次显示。
    # trigger 用 'import' 与月度 stockpile.csv 一致 —— 数据视角下都是"产品总档全量
    # 刷新"批次，recent_changes_service 现有的批次窗口逻辑直接 work，不用改。
    active_count = session.scalar(
        select(func.count()).select_from(Stockpile).where(Stockpile.is_active == 1)
    )
    session.execute(
        sa_insert(StockpileSnapshot).values(
            trigger="import",
            total_local=int(active_count or 0),
        )
    )

    return result
