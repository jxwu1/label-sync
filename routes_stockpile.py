import os

from flask import Blueprint, jsonify, request, send_file

import stockpile_db
from file_io import read_input_file
from path_safety import safe_filename
from schemas import ServiceResult
from state import INPUT_DIR

bp = Blueprint("stockpile", __name__)


@bp.post("/stockpile/init")
def init_stockpile():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400

    file_storage = files[0]
    if not file_storage.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    filename = safe_filename(file_storage.filename)
    file_path = INPUT_DIR / filename
    file_storage.save(file_path)

    dataframe = read_input_file(file_path)
    if dataframe is None:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"ok": False, "msg": "无法读取文件，支持 .xlsx/.xls/.csv"}), 400

    count = stockpile_db.import_from_dataframe(dataframe)

    try:
        os.remove(file_path)
    except OSError:
        pass

    return jsonify({"ok": True, "count": count})


@bp.post("/stockpile/compare")
def compare_stockpile():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400

    file_storage = files[0]
    if not file_storage.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    filename = safe_filename(file_storage.filename)
    file_path = INPUT_DIR / filename
    file_storage.save(file_path)

    dataframe = read_input_file(file_path)
    if dataframe is None:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"ok": False, "msg": "无法读取文件，支持 .xlsx/.xls/.csv"}), 400

    diff = stockpile_db.compare_with_dataframe(dataframe)

    try:
        os.remove(file_path)
    except OSError:
        pass

    return jsonify({"ok": True, "diff": diff})


@bp.post("/stockpile/apply-export")
def apply_export():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400

    file_storage = files[0]
    if not file_storage.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    filename = safe_filename(file_storage.filename)
    file_path = INPUT_DIR / filename
    file_storage.save(file_path)

    dataframe = read_input_file(file_path)
    if dataframe is None:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"ok": False, "msg": "无法读取文件，支持 .xlsx/.xls/.csv"}), 400

    updated = stockpile_db.apply_export_updates(dataframe)

    try:
        os.remove(file_path)
    except OSError:
        pass

    return jsonify({"ok": True, "updated": updated})


@bp.get("/stockpile/status")
def stockpile_status():
    initialized = stockpile_db.is_initialized()
    count = stockpile_db.count_records() if initialized else 0
    return jsonify({"ok": True, "initialized": initialized, "count": count})
