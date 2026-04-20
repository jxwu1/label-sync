from flask import Blueprint, jsonify, request

import duplicate_service
import message_service
from response_builder import json_result

bp = Blueprint("collab", __name__)


@bp.post("/text_send")
def text_send():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    sender = data.get("sender", "A").strip()
    if not text:
        return jsonify({"ok": False, "msg": "内容不能为空"}), 400
    return jsonify(message_service.send_text_message(text, sender))


@bp.get("/text_list")
def text_list():
    return jsonify(message_service.list_text_messages())


@bp.post("/text_delete")
def text_delete():
    data = request.get_json(silent=True) or {}
    message_id = data.get("id")
    if message_id is None:
        return jsonify({"ok": False, "msg": "id 不能为空"}), 400
    return json_result(message_service.delete_text_message(message_id))


@bp.post("/text_clear")
def text_clear():
    return jsonify(message_service.clear_text_messages())


@bp.post("/check_dup")
def check_dup():
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400
    payload = duplicate_service.check_duplicate_file(uploaded_file)
    if not payload["ok"]:
        return jsonify(payload), 400
    return jsonify(payload)
