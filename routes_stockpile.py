import os
from typing import Callable

from flask import Blueprint, jsonify, request

import stockpile_db
from file_io import read_input_file
from path_safety import safe_filename
from state import INPUT_DIR

bp = Blueprint("stockpile", __name__)


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
    count = stockpile_db.count_records() if initialized else 0
    return jsonify({"ok": True, "initialized": initialized, "count": count})


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


@bp.get("/stockpile/schema")
def stockpile_schema():
    return jsonify({"ok": True, "version": stockpile_db.get_schema_version()})
