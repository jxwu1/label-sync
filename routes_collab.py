from flask import Blueprint, jsonify, request
from pydantic import BaseModel

import duplicate_service
import message_service
from response_builder import json_result
from route_helpers import NonEmptyStr, OptionalStr, parse_body

bp = Blueprint("collab", __name__)


class _TextSend(BaseModel):
    text: NonEmptyStr
    sender: OptionalStr = "A"


class _TextDelete(BaseModel):
    id: int


@bp.post("/text_send")
def text_send():
    body, err = parse_body(_TextSend)
    if err:
        return err
    return jsonify(message_service.send_text_message(body.text, body.sender))


@bp.get("/text_list")
def text_list():
    return jsonify(message_service.list_text_messages())


@bp.post("/text_delete")
def text_delete():
    body, err = parse_body(_TextDelete)
    if err:
        return err
    return json_result(message_service.delete_text_message(body.id))


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
