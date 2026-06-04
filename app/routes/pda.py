"""PDA 扫描端 + PC 待处理端路由。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

import app.services.scan_session as scan_svc
from app.auth import require_role
from app.models import Employee, get_session

bp = Blueprint("pda", __name__, url_prefix="/pda")

# 静态资源版本号（内容哈希）：内容一变就换 URL，强制 PDA 浏览器加载新版 JS/CSS，
# 不再被缓存坑（改了扫码逻辑、设备却还跑旧 js）。进程启动算一次。
_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"


def _asset_version() -> str:
    h = hashlib.md5()
    for rel in ("js/pda.js", "css/pda.css"):
        try:
            h.update((_STATIC_DIR / rel).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:8]


_ASSET_V = _asset_version()


def _err(msg: str, code: int = 400):
    return jsonify(ok=False, msg=msg), code


@bp.get("/")
def scan_page():
    return render_template("pda.html", asset_v=_ASSET_V)


@bp.get("/operators")
def operators():
    with get_session() as s:
        rows = s.query(Employee).filter_by(is_scanner=1, active=1).order_by(Employee.name).all()
        return jsonify(ok=True, operators=[{"id": e.employee_id, "name": e.name} for e in rows])


@bp.post("/session/start")
def session_start():
    data = request.get_json(silent=True) or {}
    try:
        out = scan_svc.start_session(data.get("operator_employee_id", ""))
    except ValueError as exc:
        return _err(str(exc))
    return jsonify(out)


@bp.get("/session/<int:session_id>")
def session_get(session_id: int):
    return jsonify(scan_svc._session_dict(session_id))


@bp.post("/session/<int:session_id>/scan")
def session_scan(session_id: int):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(scan_svc.add_scan(session_id, data.get("raw", "")))
    except ValueError as exc:
        return _err(str(exc))


@bp.post("/session/<int:session_id>/undo")
def session_undo(session_id: int):
    return jsonify(scan_svc.undo_last(session_id))


@bp.post("/session/<int:session_id>/update-item")
def session_update_item(session_id: int):
    # 行内修正：把第 seq 行的值覆盖为 raw（点行→直接扫码覆盖）。按 seq 定位即可，
    # 客户端拿的就是服务端返回的 seq。
    data = request.get_json(silent=True) or {}
    try:
        seq = int(data.get("seq"))
    except (TypeError, ValueError):
        return _err("缺少行号")
    try:
        return jsonify(scan_svc.update_item(session_id, seq, data.get("raw", "")))
    except ValueError as exc:
        return _err(str(exc))


@bp.post("/session/<int:session_id>/finalize")
def session_finalize(session_id: int):
    try:
        return jsonify(scan_svc.finalize(session_id))
    except ValueError as exc:
        return _err(str(exc))


# ---- PC 待处理端（admin only） ----


@bp.get("/pending")
@require_role("admin")
def pending_list():
    return jsonify(ok=True, pending=scan_svc.list_pending())


@bp.post("/pending/<int:session_id>/process")
@require_role("admin")
def pending_process(session_id: int):
    from app.services import storage as storage_service
    from app.services import task as task_service
    from app.state import task_state

    if task_state.is_running() or task_state.is_waiting():
        return _err("已有任务在运行或等待中")
    ok, msg = storage_service.validate_stockpile_is_ready()
    if not ok:
        return _err(msg)
    scan_svc.process_pending(session_id)
    task_service.start_background_task(task_service.run_phase_one)
    return jsonify(ok=True)


@bp.post("/pending/<int:session_id>/discard")
@require_role("admin")
def pending_discard(session_id: int):
    scan_svc.discard_pending(session_id)
    return jsonify(ok=True)
