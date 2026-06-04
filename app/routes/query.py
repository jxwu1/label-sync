from flask import Blueprint, jsonify, send_file

from app.repositories.output import output_zip_path
from app.services import query as query_service

bp = Blueprint("query", __name__)


@bp.get("/barcodes")
def barcodes():
    payload = query_service.read_barcode_list()
    if not payload["ok"]:
        return jsonify(payload), 404
    return jsonify(payload)


@bp.get("/models")
def models():
    from flask import request

    batch_id = request.args.get("batch_id")
    payload = query_service.read_model_list(batch_id=batch_id)
    if not payload["ok"]:
        status_code = 404 if "找不到" in payload["msg"] else 500
        return jsonify(payload), status_code
    return jsonify(payload)


@bp.get("/files")
def files():
    return jsonify(query_service.read_file_list())


@bp.get("/download_zip/<path:filename>")
def download_zip(filename):
    zip_path = output_zip_path(filename)
    if not zip_path.exists():
        return jsonify({"ok": False, "msg": "文件不存在"}), 404
    return send_file(zip_path, as_attachment=True)
