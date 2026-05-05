"""进销存事件导入器。

输入：parsed DataFrame（来自 xls_html_parser）+ 列映射 + 事件类型（purchase/sale）。
输出：写到 inventory_events 表，同时维护 customers/suppliers/stockpile 主档。

设计要点：
- 列映射用统一格式 {erp 列名 → internal 字段名 / "ignore"}
- internal 字段用泛型名（partner_id/partner_name），按 event_type 路由到客户或供应商
- 类型清洗在 import 时做（barcode float→str / 日期 ISO 化 / qty 转 int）
- 幂等：同一文件重 import → UNIQUE 约束去重
- SKU 自动 UPSERT 到 stockpile，保留人工修正的字段（COALESCE 逻辑）
- partner 自动 UPSERT，first_seen_at = MIN(...) / last_seen_at = MAX(...)
- 缺失关键字段（barcode/qty/date）的行静默跳过
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from customer_classifier import classify_customer
from erp_category_parser import parse_erp_category
from models import Customer, InventoryEvent, Stockpile, Supplier

# === 内部字段名常量 ===
# 映射目标只能是这些值之一（或 'ignore'）。多了 / 少了由列映射向导校验。
INTERNAL_FIELDS = frozenset(
    {
        "document_no",
        "shipping_doc",
        "partner_id",
        "partner_name",
        "partner_phone",
        "partner_address",
        "warehouse",
        "event_at",
        "product_model",
        "product_barcode",
        "manual_grade",
        "erp_category_raw",
        "product_name_zh",
        "product_name_local",
        "qty",
        "unit_price",
        "discount_pct",
        "ignore",
    }
)

# 默认列映射（基于用户给的 ERP 25 列样本）
DEFAULT_MAPPING: dict[str, str] = {
    "单号": "document_no",
    "查看": "ignore",
    "ID号": "partner_id",
    "名称": "partner_name",
    "联系方法": "partner_phone",
    "地址": "partner_address",
    "邮编": "ignore",
    "城市": "ignore",
    "仓库": "warehouse",
    "日期": "event_at",
    "型号": "product_model",
    "条形码": "product_barcode",
    "等级": "manual_grade",
    "产品种类": "erp_category_raw",
    "品名": "product_name_zh",
    "本地品名": "product_name_local",
    "颜色": "ignore",
    "数量": "qty",
    "差数": "ignore",
    "单价": "unit_price",
    "折扣": "discount_pct",
    "金额(€)": "ignore",
    "备注": "ignore",
    "单据备注": "ignore",
    "状态": "ignore",
}


@dataclass
class ImportResult:
    """单次 import 的统计结果。"""

    rows_imported: int = 0
    rows_skipped_duplicate: int = 0
    rows_skipped_missing_key: int = 0
    new_customers: int = 0
    new_suppliers: int = 0
    new_skus: int = 0
    skipped_reasons: list[str] = field(default_factory=list)

    @property
    def rows_skipped(self) -> int:
        return self.rows_skipped_duplicate + self.rows_skipped_missing_key


# === 类型清洗 ===


def _clean_str(val: Any) -> str | None:
    """None / NaN / 空白 → None，否则 strip 后返回。"""
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s or None


def _clean_barcode_or_model(val: Any) -> str | None:
    """5828079113422.0 (float64) → '5828079113422'，避免精度损失。"""
    if pd.isna(val):
        return None
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return str(val)
    return str(val).strip() or None


def _clean_int(val: Any) -> int | None:
    if pd.isna(val):
        return None
    try:
        return int(float(val))  # 兼容 "100" / "100.0" / 100 / 100.0
    except (TypeError, ValueError):
        return None


def _clean_float(val: Any) -> float | None:
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _clean_date(val: Any) -> str | None:
    """'2026/4/27' / '2026-5-5' / '2026-05-05' → '2026-05-05'。

    兼容 / 和 - 分隔，自动补零。
    """
    if pd.isna(val):
        return None
    s = str(val).strip()
    for sep in ("/", "-"):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    y, m, d = (int(p) for p in parts)
                    if 1900 < y < 2200 and 1 <= m <= 12 and 1 <= d <= 31:
                        return f"{y:04d}-{m:02d}-{d:02d}"
                except ValueError:
                    pass
    return None


# === 主档 UPSERT ===


def _upsert_customer(
    session: Session, partner_id: str, name: str, phone: str | None, address: str | None, dt: str
) -> bool:
    """返回 True 如果是新建客户。"""
    existing = session.get(Customer, partner_id)
    if existing is not None:
        # 只补 NULL 字段，不覆盖人工修正过的
        if phone and not existing.phone:
            existing.phone = phone
        if address and not existing.address:
            existing.address = address
        # first_seen_at = MIN(existing, dt) / last_seen_at = MAX(...)
        if existing.first_seen_at is None or dt < existing.first_seen_at:
            existing.first_seen_at = dt
        if existing.last_seen_at is None or dt > existing.last_seen_at:
            existing.last_seen_at = dt
        return False
    session.add(
        Customer(
            customer_id=partner_id,
            customer_name=name,
            customer_type=classify_customer(name),
            phone=phone,
            address=address,
            first_seen_at=dt,
            last_seen_at=dt,
        )
    )
    return True


def _upsert_supplier(
    session: Session, partner_id: str, name: str, phone: str | None, address: str | None, dt: str
) -> bool:
    existing = session.get(Supplier, partner_id)
    if existing is not None:
        if phone and not existing.phone:
            existing.phone = phone
        if address and not existing.address:
            existing.address = address
        if existing.first_seen_at is None or dt < existing.first_seen_at:
            existing.first_seen_at = dt
        if existing.last_seen_at is None or dt > existing.last_seen_at:
            existing.last_seen_at = dt
        return False
    session.add(
        Supplier(
            supplier_id=partner_id,
            supplier_name=name,
            phone=phone,
            address=address,
            first_seen_at=dt,
            last_seen_at=dt,
        )
    )
    return True


def _ensure_stockpile_sku(session: Session, barcode: str, internal: dict[str, Any]) -> bool:
    """SKU 不存在则 INSERT，存在则只补 NULL 字段（不覆盖人工修正）。返回 True 如果新建。"""
    existing = session.execute(
        Stockpile.__table__.select().where(Stockpile.product_barcode == barcode)
    ).first()
    erp_raw = _clean_str(internal.get("erp_category_raw"))
    erp_code, _ = parse_erp_category(erp_raw)
    name_zh = _clean_str(internal.get("product_name_zh"))
    name_local = _clean_str(internal.get("product_name_local"))
    grade = _clean_int(internal.get("manual_grade"))
    model = _clean_barcode_or_model(internal.get("product_model")) or barcode

    if existing is not None:
        # 只补 NULL，不覆盖
        sp = session.get(Stockpile, existing.id)
        if sp.product_name_zh is None and name_zh:
            sp.product_name_zh = name_zh
        if sp.product_name_local is None and name_local:
            sp.product_name_local = name_local
        if sp.erp_category_raw is None and erp_raw:
            sp.erp_category_raw = erp_raw
        if sp.erp_category_code is None and erp_code:
            sp.erp_category_code = erp_code
        # 等级总是更新到最新事件的值（人工调整就是最新输入）
        if grade is not None:
            sp.manual_grade = grade
        return False

    session.add(
        Stockpile(
            product_barcode=barcode,
            product_model=model,
            stockpile_location="",
            is_active=1,
            source="inventory_import",
            product_name_zh=name_zh,
            product_name_local=name_local,
            erp_category_raw=erp_raw,
            erp_category_code=erp_code or None,
            manual_grade=grade,
        )
    )
    return True


# === 事件插入（幂等） ===


def _insert_event_idempotent(
    session: Session,
    event_type: str,
    internal: dict[str, Any],
    barcode: str,
    qty: int,
    event_at: str,
    partner_id: str | None,
) -> bool:
    """INSERT OR IGNORE。返回 True 如果实际插入了新行。

    注意：SQLite UNIQUE 约束遇到 NULL 视为不同（NULLs are distinct）。所以
    去重键里参与的列我们强制非 NULL：document_no/shipping_doc 默认空串、
    unit_price 默认 0.0。这样同一行真重复 import 才会被识别为冲突。
    """
    erp_raw = _clean_str(internal.get("erp_category_raw"))
    erp_code, _ = parse_erp_category(erp_raw)

    values = {
        "event_at": event_at,
        "event_type": event_type,
        "product_barcode": barcode,
        "qty": qty,
        "unit_price": _clean_float(internal.get("unit_price")) or 0.0,
        "discount_pct": _clean_float(internal.get("discount_pct")),
        "document_no": _clean_str(internal.get("document_no")) or "",
        "shipping_doc": _clean_str(internal.get("shipping_doc")) or "",
        "customer_id": partner_id if event_type == "sale" else None,
        "supplier_id": partner_id if event_type == "purchase" else None,
        "warehouse": _clean_str(internal.get("warehouse")),
        "erp_category_raw": erp_raw,
        "erp_category_code": erp_code or None,
        "manual_grade": _clean_int(internal.get("manual_grade")),
    }
    stmt = sqlite_insert(InventoryEvent).values(**values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[
            "event_type",
            "document_no",
            "shipping_doc",
            "product_barcode",
            "event_at",
            "qty",
            "unit_price",
        ]
    )
    result = session.execute(stmt)
    return bool(result.rowcount)


# === 主入口 ===


def import_events(
    df: pd.DataFrame,
    mapping: dict[str, str],
    event_type: str,
    session: Session,
) -> ImportResult:
    """把 dataframe 按 mapping 落到 inventory_events + 主档表。

    event_type 必须是 'purchase' 或 'sale'。
    session 由调用方管理（commit 在外）。
    """
    if event_type not in ("purchase", "sale"):
        raise ValueError(f"event_type 必须是 purchase 或 sale，得到：{event_type}")

    result = ImportResult()

    for idx, row in df.iterrows():
        # 应用列映射 → 内部 dict
        internal: dict[str, Any] = {}
        for col_name, internal_field in mapping.items():
            if internal_field == "ignore":
                continue
            if internal_field not in INTERNAL_FIELDS:
                continue
            if col_name in row.index:
                internal[internal_field] = row[col_name]

        # 关键字段
        barcode = _clean_barcode_or_model(internal.get("product_barcode"))
        qty = _clean_int(internal.get("qty"))
        event_at = _clean_date(internal.get("event_at"))
        partner_id = _clean_str(internal.get("partner_id"))
        partner_name = _clean_str(internal.get("partner_name"))

        # ERP 导出末尾常带"合计/页脚"行：所有关键字段都空。静默跳过，不计入
        # rows_skipped 也不报到 skipped_reasons，避免给用户错误的"有错"印象。
        all_empty = (
            not barcode and qty is None and not event_at and not partner_id and not partner_name
        )
        if all_empty:
            continue

        if not barcode or qty is None or not event_at:
            result.rows_skipped_missing_key += 1
            if len(result.skipped_reasons) < 10:
                result.skipped_reasons.append(
                    f"row {idx}: 缺关键字段 barcode={barcode!r} qty={qty!r} date={event_at!r}"
                )
            continue

        # 主档 UPSERT
        if partner_id and partner_name:
            phone = _clean_str(internal.get("partner_phone"))
            address = _clean_str(internal.get("partner_address"))
            if event_type == "purchase":
                if _upsert_supplier(session, partner_id, partner_name, phone, address, event_at):
                    result.new_suppliers += 1
            else:
                if _upsert_customer(session, partner_id, partner_name, phone, address, event_at):
                    result.new_customers += 1

        # SKU 自动加（如果不存在）
        if _ensure_stockpile_sku(session, barcode, internal):
            result.new_skus += 1

        # flush 让 partner / sku 落库以便事件插入时外键参照（虽然没设 FK，但
        # 让 dedupe 计数准确还是要 flush）
        session.flush()

        # 事件插入
        if _insert_event_idempotent(
            session, event_type, internal, barcode, qty, event_at, partner_id
        ):
            result.rows_imported += 1
        else:
            result.rows_skipped_duplicate += 1

    return result
