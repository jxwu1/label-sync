from flask import Blueprint, jsonify, request, send_file

import storage_service
from response_builder import json_result
from state import TRANSFER_DIR
from transfer_repository import transfer_file_path

bp = Blueprint("transfer", __name__)


@bp.post("/transfer_upload")
def transfer_upload():
    try:
        files = request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "msg": "没有收到文件"}), 400
        return jsonify({"ok": True, "saved": storage_service.save_uploaded_files(files, TRANSFER_DIR)})
    except OSError as error:
        return jsonify({"ok": False, "msg": f"保存文件失败：{error}"}), 500


@bp.get("/transfer_list")
def transfer_list():
    return jsonify(storage_service.list_transfer_files())


@bp.get("/transfer_download/<path:filename>")
def transfer_download(filename):
    file_path = transfer_file_path(filename)
    if not file_path.exists():
        return jsonify({"ok": False, "msg": "文件不存在"}), 404
    return send_file(file_path, as_attachment=True)


@bp.post("/transfer_delete")
def transfer_delete():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"ok": False, "msg": "文件名不能为空"}), 400
    return json_result(storage_service.delete_transfer_file(filename))
