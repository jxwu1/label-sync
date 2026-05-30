"""扫描会话服务：生命周期 + 物化现有格式扫描 .xlsx。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from app.models import Employee, ScanSession, get_session
from app.state import INPUT_DIR
import app.repositories.scan_session as repo

_SAFE = re.compile(r"[\\/:*?\"<>|]+")


def _employee(operator_employee_id: str) -> Employee | None:
    with get_session() as s:
        return s.get(Employee, operator_employee_id)


def start_session(operator_employee_id: str) -> dict:
    emp = _employee(operator_employee_id)
    if emp is None or not emp.is_scanner:
        raise ValueError("该员工不在扫描名单中")
    active = repo.get_active_session()
    if active is not None:
        return _session_dict(active.id)
    sid = repo.create_session(operator_employee_id, emp.name)
    return _session_dict(sid)


def add_scan(session_id: int, raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("空扫描")
    repo.append_item(session_id, raw)
    return _session_dict(session_id)


def undo_last(session_id: int) -> dict:
    repo.pop_last_item(session_id)
    return _session_dict(session_id)


def finalize(session_id: int) -> dict:
    sess = repo.get_session_row(session_id)
    if sess is None:
        raise ValueError("会话不存在")
    if (sess.item_count or 0) == 0:
        raise ValueError("空会话不能保存")
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    batch_label = f"{sess.operator_name}价格标{ts}"
    with get_session() as s:
        row = s.get(ScanSession, session_id)
        row.batch_label = batch_label
        row.finalized_at = datetime.now().isoformat(timespec="seconds")
    repo.set_status(session_id, "pending")
    return _session_dict(session_id)


def materialize_xlsx(session_id: int) -> Path:
    sess = repo.get_session_row(session_id)
    items = repo.list_items(session_id)
    safe_name = _SAFE.sub("_", sess.operator_name).strip() or f"pda{session_id}"
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = INPUT_DIR / f"{safe_name}.xlsx"
    wb = Workbook()
    ws = wb.active
    for it in items:
        ws.append([it.raw])  # 单列、按 seq 顺序，无表头
    wb.save(path)
    return path


def list_pending() -> list[dict]:
    return [
        {
            "id": s.id,
            "operator_name": s.operator_name,
            "item_count": s.item_count,
            "batch_label": s.batch_label,
            "finalized_at": s.finalized_at,
        }
        for s in repo.list_pending()
    ]


def process_pending(session_id: int) -> None:
    # 清掉旧的扫描 xlsx，避免 phase1 的 sorted()[0].stem 取错文件
    for old in INPUT_DIR.glob("*.xlsx"):
        try:
            old.unlink()
        except OSError:
            pass
    materialize_xlsx(session_id)
    repo.set_status(session_id, "processing")


def discard_pending(session_id: int) -> None:
    repo.set_status(session_id, "discarded")


def _session_dict(session_id: int) -> dict:
    sess = repo.get_session_row(session_id)
    items = repo.list_items(session_id)
    return {
        "ok": True,
        "session_id": sess.id,
        "operator_name": sess.operator_name,
        "status": sess.status,
        "item_count": sess.item_count,
        "rows": [{"seq": i.seq, "raw": i.raw, "kind": i.kind} for i in items],
    }
