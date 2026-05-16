from flask import Blueprint, jsonify, request, send_file
from pydantic import BaseModel

import storage_service
from app.utils.response_builder import json_result
from app.utils.route_helpers import NonEmptyStr, parse_body
from state import TRANSFER_DIR
from app.repositories.transfer import transfer_file_path

bp = Blueprint("transfer", __name__)


class _TransferDelete(BaseModel):
    filename: NonEmptyStr


@bp.post("/transfer_upload")
def transfer_upload():
    try:
        files = request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "msg": "没有收到文件"}), 400
        return jsonify(
            {"ok": True, "saved": storage_service.save_uploaded_files(files, TRANSFER_DIR)}
        )
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
    body, err = parse_body(_TransferDelete)
    if err:
        return err
    return json_result(storage_service.delete_transfer_file(body.filename))
