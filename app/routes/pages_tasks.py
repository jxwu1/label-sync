import os

from flask import Blueprint, jsonify, render_template, request, send_file
from pydantic import BaseModel

from app.config import CONFIG
from app.services import barcode as barcode_service
from app.services import storage as storage_service
from app.services import task as task_service
from app.utils.response_builder import json_result
from app.utils.route_helpers import NonEmptyStr, parse_body
from app.state import INPUT_DIR, task_state

bp = Blueprint("pages_tasks", __name__)


class _BarcodeCorrect(BaseModel):
    old_barcode: NonEmptyStr
    new_barcode: NonEmptyStr


class _LocationCorrect(BaseModel):
    old_location: NonEmptyStr
    new_location: NonEmptyStr


class _ExceptionResolve(BaseModel):
    barcode: NonEmptyStr
    resolution: NonEmptyStr


class _BarcodeDelete(BaseModel):
    barcode: NonEmptyStr


@bp.get("/")
def index():
    return render_template("index.html", enable_transfer=CONFIG.enable_transfer)


@bp.post("/upload")
def upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400
    return jsonify({"ok": True, "saved": storage_service.save_uploaded_files(files, INPUT_DIR)})


@bp.post("/run")
def run():
    if task_state.is_running() or task_state.is_waiting():
        return jsonify({"ok": False, "msg": "已有任务在运行或等待中"}), 400

    is_valid, error_message = storage_service.validate_stockpile_is_ready()
    if not is_valid:
        return jsonify({"ok": False, "msg": error_message}), 400

    task_service.start_background_task(task_service.run_phase_one)
    return jsonify({"ok": True})


@bp.post("/continue")
def continue_processing():
    if not task_state.is_waiting():
        return jsonify({"ok": False, "msg": "当前不在等待状态"}), 400
    if task_state.is_running():
        return jsonify({"ok": False, "msg": "已有任务在运行"}), 400

    waiting_stage = task_state.waiting_stage()
    if waiting_stage in ("anomaly", "location_format"):
        task_service.start_background_task(task_service.run_phase_two)
    else:
        task_service.start_background_task(task_service.run_phase_three)
    return jsonify({"ok": True})


@bp.get("/status")
def status():
    snapshot = task_state.snapshot()
    done = (
        not snapshot.running
        and not snapshot.waiting
        and snapshot.result_zip is not None
    )
    batch_id = ""
    if done and snapshot.result_zip:
        batch_id = os.path.splitext(os.path.basename(snapshot.result_zip))[0]
    return jsonify(
        {
            "running": snapshot.running,
            "waiting": snapshot.waiting,
            "waiting_stage": snapshot.waiting_stage,
            "log": snapshot.log,
            "done": done,
            "batch_id": batch_id,
            "error": snapshot.error,
            "barcode_warnings": [warning.to_dict() for warning in snapshot.barcode_warnings],
            "location_warnings": [warning.to_dict() for warning in snapshot.location_warnings],
            "new_barcodes": snapshot.new_barcodes,
            "phase2_warnings": [warning.to_dict() for warning in snapshot.phase2_warnings],
        }
    )


@bp.post("/correct")
def correct():
    body, err = parse_body(_BarcodeCorrect)
    if err:
        return err
    return json_result(barcode_service.correct_barcode(body.old_barcode, body.new_barcode))


@bp.post("/correct_location")
def correct_location():
    body, err = parse_body(_LocationCorrect)
    if err:
        return err
    return json_result(barcode_service.correct_location(body.old_location, body.new_location))


@bp.post("/resolve_exception")
def resolve_exception():
    body, err = parse_body(_ExceptionResolve)
    if err:
        return err
    return json_result(barcode_service.resolve_phase2_exception(body.barcode, body.resolution))


@bp.post("/delete_barcode")
def delete_barcode():
    body, err = parse_body(_BarcodeDelete)
    if err:
        return err
    return json_result(barcode_service.delete_barcode(body.barcode))


@bp.get("/download")
def download():
    zip_path = storage_service.current_result_path()
    if not zip_path or not os.path.exists(zip_path):
        return jsonify({"ok": False, "msg": "结果文件不存在"}), 404
    return send_file(zip_path, as_attachment=True)
