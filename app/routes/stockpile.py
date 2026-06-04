import os
from collections.abc import Callable

from flask import Blueprint, jsonify, request
from pydantic import BaseModel, Field

from app.repositories import stockpile_db
from app.state import INPUT_DIR
from app.utils.file_io import read_input_file
from app.utils.path_safety import safe_filename
from app.utils.route_helpers import NonEmptyStr, OptionalStr, parse_body

bp = Blueprint("stockpile", __name__)


class _UpdateLocation(BaseModel):
    barcode: NonEmptyStr
    location: OptionalStr = ""


class _OverwriteLocations(BaseModel):
    entries: list[dict] = Field(min_length=1)


def _with_uploaded_dataframe(handler: Callable[[object], dict]) -> tuple:
    """统一处理 stockpile 上传：取文件 → 读 dataframe → 调 handler → 保证清理临时文件。

    handler 接收 dataframe，返回成功 payload（不含 ok 字段）。
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400
    file_storage = files[0]
    if not file_storage.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    filename = safe_filename(file_storage.filename)
    file_path = INPUT_DIR / filename
    file_storage.save(file_path)

    try:
        dataframe = read_input_file(file_path)
        if dataframe is None:
            return jsonify({"ok": False, "msg": "无法读取文件，支持 .xlsx/.xls/.csv"}), 400
        payload = handler(dataframe)
        return jsonify({"ok": True, **payload})
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass


@bp.post("/stockpile/init")
def init_stockpile():
    return _with_uploaded_dataframe(lambda df: {"count": stockpile_db.import_from_dataframe(df)})


@bp.post("/stockpile/compare")
def compare_stockpile():
    return _with_uploaded_dataframe(lambda df: {"diff": stockpile_db.compare_with_dataframe(df)})


@bp.post("/stockpile/apply-export")
def apply_export():
    return _with_uploaded_dataframe(lambda df: {"updated": stockpile_db.apply_export_updates(df)})


@bp.get("/stockpile/status")
def stockpile_status():
    initialized = stockpile_db.is_initialized()
    if not initialized:
        return jsonify(
            {
                "ok": True,
                "initialized": False,
                "count": 0,
                "active_count": 0,
                "inactive_count": 0,
                "last_import_at": None,
            }
        )
    active = stockpile_db.count_records()
    return jsonify(
        {
            "ok": True,
            "initialized": True,
            "count": active,  # 向后兼容（substrip / 旧调用方）
            "active_count": active,
            "inactive_count": stockpile_db.count_inactive_records(),
            "last_import_at": stockpile_db.last_import_at(),  # "YYYY-MM-DD HH:MM:SS" or None
        }
    )


@bp.get("/stockpile/inactive")
def stockpile_inactive():
    limit = request.args.get("limit", default=100, type=int) or 100
    limit = max(1, min(limit, 500))
    records = stockpile_db.list_inactive_records(limit=limit)
    return jsonify({"ok": True, "count": len(records), "records": records})


@bp.get("/stockpile/changes")
def stockpile_changes():
    limit = request.args.get("limit", default=100, type=int) or 100
    limit = max(1, min(limit, 500))
    changes = stockpile_db.list_changes(limit=limit)
    return jsonify({"ok": True, "count": len(changes), "changes": changes})


@bp.get("/stockpile/search")
def stockpile_search():
    q = request.args.get("q", default="", type=str).strip()
    if not q:
        return jsonify({"ok": False, "msg": "请输入搜索关键词"}), 400
    if len(q) < 2:
        return jsonify({"ok": False, "msg": "关键词至少2个字符"}), 400
    limit = request.args.get("limit", default=50, type=int) or 50
    limit = max(1, min(limit, 200))
    records = stockpile_db.search_stockpile(q, limit=limit)
    return jsonify({"ok": True, "count": len(records), "records": records})


@bp.post("/stockpile/update-location")
def stockpile_update_location():
    body, err = parse_body(_UpdateLocation)
    if err:
        return err
    existing = stockpile_db.query_by_barcode(body.barcode)
    if not existing:
        return jsonify({"ok": False, "msg": "条码不存在"}), 404
    stockpile_db.insert_or_update(
        barcode=body.barcode,
        model=existing["product_model"],
        location=body.location,
        source=stockpile_db.Source.USER_CORRECTION,
    )
    return jsonify({"ok": True})


@bp.post("/stockpile/overwrite-locations")
def stockpile_overwrite_locations():
    body, err = parse_body(_OverwriteLocations)
    if err:
        return err
    # 单个 entry 内的 barcode/location 仍由本函数 strip + 容错（坏 entry 静默跳过，
    # 而不是整请求失败 —— 对既有前端兼容）
    updated = 0
    for entry in body.entries:
        barcode = (entry.get("barcode") or "").strip()
        location = (entry.get("location") or "").strip()
        if not barcode:
            continue
        existing = stockpile_db.query_by_barcode(barcode)
        if not existing:
            continue
        stockpile_db.insert_or_update(
            barcode=barcode,
            model=existing["product_model"],
            location=location,
            source=stockpile_db.Source.USER_CORRECTION,
        )
        updated += 1
    return jsonify({"ok": True, "updated": updated})


@bp.get("/stockpile/schema")
def stockpile_schema():
    return jsonify({"ok": True, "version": stockpile_db.get_schema_version()})


@bp.get("/stockpile/snapshots")
def stockpile_snapshots():
    """趋势数据：最近 N 个 import / compare 快照。"""
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    trigger = request.args.get("trigger") or None
    return jsonify(
        {
            "ok": True,
            "snapshots": stockpile_db.list_snapshots(limit=limit, trigger=trigger),
        }
    )
