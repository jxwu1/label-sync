import os

from flask import Blueprint, jsonify, render_template, request, send_file

import barcode_service
import storage_service
import task_service
from response_builder import json_result
from state import INPUT_DIR, task_state

bp = Blueprint("pages_tasks", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/admin")
def admin():
    return render_template("admin.html")


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
    return jsonify(
        {
            "running": snapshot.running,
            "waiting": snapshot.waiting,
            "waiting_stage": snapshot.waiting_stage,
            "log": snapshot.log,
            "done": not snapshot.running and not snapshot.waiting and snapshot.result_zip is not None,
            "error": snapshot.error,
            "barcode_warnings": [warning.to_dict() for warning in snapshot.barcode_warnings],
            "location_warnings": [warning.to_dict() for warning in snapshot.location_warnings],
            "new_barcodes": snapshot.new_barcodes,
            "phase2_warnings": [warning.to_dict() for warning in snapshot.phase2_warnings],
        }
    )


@bp.post("/correct")
def correct():
    data = request.get_json(silent=True) or {}
    old_barcode = data.get("old_barcode", "").strip()
    new_barcode = data.get("new_barcode", "").strip()
    if not old_barcode or not new_barcode:
        return jsonify({"ok": False, "msg": "条码不能为空"}), 400
    return json_result(barcode_service.correct_barcode(old_barcode, new_barcode))


@bp.post("/correct_location")
def correct_location():
    data = request.get_json(silent=True) or {}
    old_location = data.get("old_location", "").strip()
    new_location = data.get("new_location", "").strip()
    if not old_location or not new_location:
        return jsonify({"ok": False, "msg": "库位不能为空"}), 400
    return json_result(barcode_service.correct_location(old_location, new_location))


@bp.post("/resolve_exception")
def resolve_exception():
    data = request.get_json(silent=True) or {}
    barcode = data.get("barcode", "").strip()
    resolution = data.get("resolution", "").strip()
    if not barcode or not resolution:
        return jsonify({"ok": False, "msg": "参数不完整"}), 400
    return json_result(barcode_service.resolve_phase2_exception(barcode, resolution))


@bp.post("/delete_barcode")
def delete_barcode():
    data = request.get_json(silent=True) or {}
    barcode = data.get("barcode", "").strip()
    if not barcode:
        return jsonify({"ok": False, "msg": "条码不能为空"}), 400
    return json_result(barcode_service.delete_barcode(barcode))


@bp.get("/download")
def download():
    zip_path = storage_service.current_result_path()
    if not zip_path or not os.path.exists(zip_path):
        return jsonify({"ok": False, "msg": "结果文件不存在"}), 404
    return send_file(zip_path, as_attachment=True)
