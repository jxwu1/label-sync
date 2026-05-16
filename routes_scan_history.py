"""扫描历史浏览 endpoints。"""

from flask import Blueprint, abort, jsonify, send_file

from app.services import scan_history as scan_history_service
bp = Blueprint("scan_history", __name__, url_prefix="/scan_history")


@bp.get("/batches")
def list_batches():
    """返回最近 100 个 batch 概览 + 全部员工列表。"""
    batches = scan_history_service.list_batches()
    employees = scan_history_service.list_employees()
    return jsonify({"ok": True, "employees": employees, "batches": batches})


@bp.get("/batches/<path:batch_id>/download/csv")
def download_csv(batch_id: str):
    """重下载 batch 内主 CSV。"""
    csv_path = scan_history_service.get_batch_csv_path(batch_id)
    if csv_path is None:
        abort(404)
    return send_file(
        csv_path,
        as_attachment=True,
        download_name=csv_path.name,
        mimetype="text/csv",
    )


@bp.get("/batches/<path:batch_id>/files/<filename>")
def download_xlsx(batch_id: str, filename: str):
    """下载 batch 内某个 xlsx 文件。"""
    xlsx_path = scan_history_service.get_batch_xlsx_path(batch_id, filename)
    if xlsx_path is None:
        abort(404)
    return send_file(
        xlsx_path,
        as_attachment=True,
        download_name=xlsx_path.name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
