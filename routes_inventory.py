"""进销存事件 import / 列映射向导 HTTP 路由。

端点：
- POST   /inventory/preview                 上传 .xls 样本 → 返回列名 + 前 5 行预览
- GET    /inventory/profiles/<name>         读取 profile（purchase / sales）
- POST   /inventory/profiles/<name>         保存 profile 列映射
- POST   /inventory/import/<file_type>      上传 .xls + 应用 profile + 入库
- GET    /inventory/stats                   主档与事件计数 (健康检查 / dashboard 用)

行为约定：
- file_type / profile name 严格 "purchase" / "sales"
- import 端点上传文件名固定 form 字段 "file"
- 重复 import 同一文件不会重复落库（依赖 UNIQUE 约束 + INSERT OR IGNORE）
"""

import os
from pathlib import Path

import pandas as pd
from flask import Blueprint, jsonify, request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from werkzeug.utils import secure_filename

import stockpile_db
from inventory_importer import (
    DEFAULT_MAPPING,
    INTERNAL_FIELDS,
    import_events,
)
from models import (
    Customer,
    ImportProfile,
    InventoryEvent,
    InventoryImport,
    Stockpile,
    Supplier,
)
from app.utils.path_safety import safe_filename
from product_master_importer import (
    DEFAULT_PRODUCT_MAPPING,
    import_product_master,
)
from app.utils.route_helpers import parse_body
from state import INPUT_DIR
from xls_html_parser import XlsHtmlParseError, parse_xls_html

bp = Blueprint("inventory", __name__, url_prefix="/inventory")

_PROFILE_NAMES = ("purchase", "sales")
_FILE_TYPE_TO_EVENT = {"purchase": "purchase", "sales": "sale"}


# ========== Pydantic schemas ==========


class _ProfileMapping(BaseModel):
    """列映射：{erp 列名 → internal 字段名}。"""

    mapping: dict[str, str] = Field(min_length=1)

    @field_validator("mapping")
    @classmethod
    def _internal_fields_valid(cls, v: dict[str, str]) -> dict[str, str]:
        bad = {k: target for k, target in v.items() if target not in INTERNAL_FIELDS}
        if bad:
            raise ValueError(
                f"列映射目标必须是 {sorted(INTERNAL_FIELDS)}，发现非法："
                + ", ".join(f"{k}→{t}" for k, t in bad.items())
            )
        return v


# ========== 工具：上传文件保存到临时位置 ==========


def _save_upload_to_tmp() -> tuple[str | None, tuple | None]:
    """从 request.files 取 'file' 字段保存到 INPUT_DIR。返回 (path, None) 或 (None, error)。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return None, (jsonify({"ok": False, "msg": "没有收到文件"}), 400)
    fn = safe_filename(secure_filename(f.filename) or "upload.xls")
    p = INPUT_DIR / fn
    f.save(p)
    return str(p), None


def _cleanup(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ========== 端点 ==========


@bp.post("/preview")
def preview() -> tuple:
    """上传样本 → 返回列名和前 5 行（用于列映射向导）。"""
    path, err = _save_upload_to_tmp()
    if err:
        return err
    assert path is not None
    try:
        df = parse_xls_html(path)
    except XlsHtmlParseError as exc:
        _cleanup(path)
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 400
    finally:
        _cleanup(path)
    columns = list(df.columns)
    head = df.head(5).fillna("").astype(str).to_dict(orient="records")
    return jsonify(
        {
            "ok": True,
            "columns": columns,
            "row_count": int(df.shape[0]),
            "sample": head,
            "default_mapping": DEFAULT_MAPPING,
            "internal_fields": sorted(INTERNAL_FIELDS),
        }
    )


@bp.get("/profiles/<name>")
def get_profile(name: str) -> tuple:
    if name not in _PROFILE_NAMES:
        return jsonify({"ok": False, "msg": f"profile 名必须是 {_PROFILE_NAMES} 之一"}), 400
    with stockpile_db._session() as session:
        prof = session.get(ImportProfile, name)
        if prof is None:
            return jsonify({"ok": True, "name": name, "mapping": DEFAULT_MAPPING, "saved": False})
        import json

        return jsonify(
            {
                "ok": True,
                "name": name,
                "mapping": json.loads(prof.column_mapping_json),
                "saved": True,
                "last_used_at": prof.last_used_at,
            }
        )


@bp.post("/profiles/<name>")
def save_profile(name: str) -> tuple:
    if name not in _PROFILE_NAMES:
        return jsonify({"ok": False, "msg": f"profile 名必须是 {_PROFILE_NAMES} 之一"}), 400
    body, err = parse_body(_ProfileMapping)
    if err:
        return err
    import json

    payload = json.dumps(body.mapping, ensure_ascii=False)
    with stockpile_db._session() as session:
        prof = session.get(ImportProfile, name)
        if prof is None:
            session.add(ImportProfile(profile_name=name, column_mapping_json=payload))
        else:
            prof.column_mapping_json = payload
        session.commit()
    return jsonify({"ok": True, "name": name, "saved": True})


@bp.post("/import/<file_type>")
def do_import(file_type: str) -> tuple:
    """应用保存的 profile 把上传的 .xls 落到 inventory_events 主档。"""
    if file_type not in _PROFILE_NAMES:
        return (
            jsonify({"ok": False, "msg": f"file_type 必须是 {_PROFILE_NAMES} 之一"}),
            400,
        )
    path, err = _save_upload_to_tmp()
    if err:
        return err
    assert path is not None

    import json

    # 取 profile（无则用 DEFAULT_MAPPING）
    with stockpile_db._session() as session:
        prof = session.get(ImportProfile, file_type)
        mapping = json.loads(prof.column_mapping_json) if prof else dict(DEFAULT_MAPPING)

    try:
        df = parse_xls_html(path)
    except XlsHtmlParseError as exc:
        _cleanup(path)
        return jsonify({"ok": False, "msg": f"解析失败：{exc}"}), 400

    event_type = _FILE_TYPE_TO_EVENT[file_type]
    try:
        with stockpile_db._session() as session:
            result = import_events(df, mapping, event_type, session)
            # 更新 profile last_used_at
            prof = session.get(ImportProfile, file_type)
            if prof is not None:
                prof.last_used_at = func.datetime("now", "localtime")
            # PR-FE-5b：写一行 audit 给「最近导入」表用
            session.add(
                InventoryImport(
                    event_type=event_type,
                    filename=Path(path).name,
                    total_rows=int(df.shape[0]),
                    ok_count=result.rows_imported,
                    dup_count=result.rows_skipped_duplicate,
                    error_count=(
                        result.rows_skipped_missing_key
                        + result.rows_skipped_no_date
                        + result.rows_skipped_orphan_barcode
                    ),
                    operator="admin",
                )
            )
            session.commit()
    except Exception as exc:
        _cleanup(path)
        return jsonify({"ok": False, "msg": f"导入失败：{exc}"}), 500
    finally:
        _cleanup(path)

    return jsonify(
        {
            "ok": True,
            "file_type": file_type,
            "rows_imported": result.rows_imported,
            "rows_skipped_duplicate": result.rows_skipped_duplicate,
            "rows_skipped_missing_key": result.rows_skipped_missing_key,
            "rows_skipped_no_date": result.rows_skipped_no_date,
            "rows_skipped_orphan_barcode": result.rows_skipped_orphan_barcode,
            "barcodes_recovered": result.barcodes_recovered,
            "new_customers": result.new_customers,
            "new_suppliers": result.new_suppliers,
            "new_skus": result.new_skus,
            "skipped_reasons": result.skipped_reasons,
        }
    )


@bp.post("/import/product-master")
def do_import_product_master() -> tuple:
    """上传 product.csv 导入产品总档（写 stockpile + suppliers 主档）。"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400
    fn = safe_filename(secure_filename(f.filename) or "product.csv")
    p = INPUT_DIR / fn
    f.save(p)

    try:
        # 强制 string dtype 避免 barcode/model 数字精度损失
        df = pd.read_csv(
            p,
            encoding="utf-8-sig",
            dtype={
                "product_barcode": str,
                "product_model": str,
                "product_kind_id": str,
                "provider_id": str,
            },
            low_memory=False,
        )
    except Exception as exc:
        try:
            os.remove(p)
        except OSError:
            pass
        return jsonify({"ok": False, "msg": f"CSV 解析失败：{exc}"}), 400

    try:
        with stockpile_db._session() as session:
            result = import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"导入失败：{exc}"}), 500
    finally:
        try:
            os.remove(p)
        except OSError:
            pass

    return jsonify(
        {
            "ok": True,
            "rows_imported": result.rows_imported,
            "rows_updated": result.rows_updated,
            "rows_skipped_missing_barcode": result.rows_skipped_missing_barcode,
            "rows_skipped_duplicate_barcode": result.rows_skipped_duplicate_barcode,
            "new_suppliers": result.new_suppliers,
            "skipped_reasons": result.skipped_reasons,
        }
    )


@bp.get("/stats")
def stats() -> tuple:
    """主档与事件计数（dashboard 健康检查用）。"""
    with stockpile_db._session() as session:
        totals = {
            "events_total": session.scalar(select(func.count()).select_from(InventoryEvent)) or 0,
            "events_purchase": session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(InventoryEvent.event_type == "purchase")
            )
            or 0,
            "events_sale": session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(InventoryEvent.event_type == "sale")
            )
            or 0,
            "customers_total": session.scalar(select(func.count()).select_from(Customer)) or 0,
            "suppliers_total": session.scalar(select(func.count()).select_from(Supplier)) or 0,
            "skus_total": session.scalar(select(func.count()).select_from(Stockpile)) or 0,
        }
        # 按客户类型分布
        type_rows = session.execute(
            select(Customer.customer_type, func.count()).group_by(Customer.customer_type)
        ).all()
        totals["customers_by_type"] = {t or "unknown": c for t, c in type_rows}
    return jsonify({"ok": True, **totals})


_RECENT_IMPORTS_DEFAULT_LIMIT = 20
_RECENT_IMPORTS_MAX_LIMIT = 200


@bp.get("/imports")
def recent_imports() -> tuple:
    """PR-FE-5b：返回最近 N 条 import audit 行。给前端「最近导入」表格用。"""
    try:
        limit = int(request.args.get("limit", _RECENT_IMPORTS_DEFAULT_LIMIT))
    except ValueError:
        limit = _RECENT_IMPORTS_DEFAULT_LIMIT
    limit = max(1, min(limit, _RECENT_IMPORTS_MAX_LIMIT))
    with stockpile_db._session() as session:
        rows = (
            session.execute(
                select(InventoryImport)
                .order_by(InventoryImport.imported_at.desc(), InventoryImport.id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        out = [
            {
                "id": r.id,
                "imported_at": r.imported_at,
                "event_type": r.event_type,
                "filename": r.filename,
                "total_rows": r.total_rows,
                "ok_count": r.ok_count,
                "dup_count": r.dup_count,
                "error_count": r.error_count,
                "operator": r.operator,
            }
            for r in rows
        ]
    return jsonify({"ok": True, "imports": out})
