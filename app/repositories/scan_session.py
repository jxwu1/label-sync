"""ScanSession / ScanItem 数据访问层。"""

from __future__ import annotations

from app.models import ScanItem, ScanSession, get_session


def _kind_of(raw: str) -> str:
    return "location" if raw[:1].isalpha() else "barcode"


def create_session(operator_employee_id: str, operator_name: str) -> int:
    with get_session() as s:
        row = ScanSession(
            operator_employee_id=operator_employee_id,
            operator_name=operator_name,
            status="active",
            item_count=0,
        )
        s.add(row)
        s.flush()
        return row.id


def get_session_row(session_id: int) -> ScanSession | None:
    with get_session() as s:
        return s.get(ScanSession, session_id)


def get_active_session() -> ScanSession | None:
    with get_session() as s:
        return (
            s.query(ScanSession).filter_by(status="active").order_by(ScanSession.id.desc()).first()
        )


def append_item(session_id: int, raw: str) -> ScanItem:
    with get_session() as s:
        sess = s.get(ScanSession, session_id)
        seq = (sess.item_count or 0) + 1
        item = ScanItem(session_id=session_id, seq=seq, raw=raw, kind=_kind_of(raw))
        s.add(item)
        sess.item_count = seq
        s.flush()
        return item


def pop_last_item(session_id: int) -> bool:
    with get_session() as s:
        sess = s.get(ScanSession, session_id)
        last = (
            s.query(ScanItem).filter_by(session_id=session_id).order_by(ScanItem.seq.desc()).first()
        )
        if not last:
            return False
        s.delete(last)
        sess.item_count = max(0, (sess.item_count or 0) - 1)
        return True


def update_item_by_seq(session_id: int, seq: int, raw: str) -> bool:
    """覆盖某一行的扫描值，并按和首次扫描相同的规则重判 kind。改库位行的值即可让其
    下面的条码在 phase1 重新归位（往上推断），无需改动条码。找不到该行返回 False。"""
    with get_session() as s:
        item = s.query(ScanItem).filter_by(session_id=session_id, seq=seq).first()
        if item is None:
            return False
        item.raw = raw
        item.kind = _kind_of(raw)
        return True


def list_items(session_id: int) -> list[ScanItem]:
    with get_session() as s:
        return s.query(ScanItem).filter_by(session_id=session_id).order_by(ScanItem.seq.asc()).all()


def set_status(session_id: int, status: str) -> None:
    with get_session() as s:
        s.get(ScanSession, session_id).status = status


def list_pending() -> list[ScanSession]:
    with get_session() as s:
        return (
            s.query(ScanSession).filter_by(status="pending").order_by(ScanSession.id.desc()).all()
        )
