"""get_batch_detail 单事务单读 单测（Phase 4a Task 2）。

复用 test_recent_changes_service.py 的 seed 约定（直接 INSERT snapshot/change，
DB 隔离由 conftest autouse _isolate_db 负责）。
"""

from sqlalchemy import insert

from app.models import StockpileChange, StockpileSnapshot
from app.repositories import stockpile_db


def _seed_snapshot(taken_at: str = "2026-04-29 14:00:00", trigger: str = "import") -> int:
    with stockpile_db._session() as session:
        result = session.execute(
            insert(StockpileSnapshot).values(taken_at=taken_at, trigger=trigger, total_local=0)
        )
        session.commit()
        return result.inserted_primary_key[0]


def _seed_change(
    barcode: str,
    field: str,
    old: str | None,
    new: str | None,
    change_type: str = "update",
    created_at: str | None = None,
) -> None:
    with stockpile_db._session() as session:
        values = {
            "product_barcode": barcode,
            "field_name": field,
            "old_value": old,
            "new_value": new,
            "change_type": change_type,
        }
        if created_at:
            values["created_at"] = created_at
        session.execute(insert(StockpileChange).values(**values))
        session.commit()


def _seed_import_batch_with_changes() -> int:
    """一个 import 批次 + 窗口内若干 changes，返回 batch_id。"""
    bid = _seed_snapshot("2026-04-29 14:00:00")
    _seed_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    _seed_change("B2", "product_model", "M1", "M2", created_at="2026-04-29 13:01:00")
    return bid


def _seed_import_then_loose_change() -> None:
    """import 批次后再来一条 loose change → 开放批次 (-1) 窗口非空。"""
    _seed_snapshot("2026-04-29 08:00:00")
    _seed_change("B1", "stockpile_location", "A1", "B7", created_at="2026-04-29 09:30:00")


def _seed_import_batch_with_n_changes(n: int) -> int:
    """import 批次 + n 条 DISTINCT (barcode, field) changes（raw 不折叠 → n 行）。"""
    bid = _seed_snapshot("2026-04-29 14:00:00")
    with stockpile_db._session() as session:
        for i in range(n):
            session.execute(
                insert(StockpileChange).values(
                    product_barcode=f"B{i}",
                    field_name="stockpile_location",
                    old_value="A1",
                    new_value="A2",
                    change_type="update",
                    created_at=f"2026-04-29 13:00:{i % 60:02d}.{i:06d}",
                )
            )
        session.commit()
    return bid


def test_get_batch_detail_single_window_read(monkeypatch):
    import app.services.recent_changes as rc

    calls = {"n": 0}
    orig = rc._fetch_window_rows

    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(rc, "_fetch_window_rows", counting)
    bid = _seed_import_batch_with_changes()
    rc.get_batch_detail(bid, mode="collapsed")
    assert calls["n"] == 1


def test_get_batch_detail_nonexistent_returns_none():
    import app.services.recent_changes as rc

    assert rc.get_batch_detail(999999) is None


def test_get_batch_detail_non_import_snapshot_returns_none():
    import app.services.recent_changes as rc

    sid = _seed_snapshot(trigger="manual")
    assert rc.get_batch_detail(sid) is None


def test_get_batch_detail_open_batch_ok():
    import app.services.recent_changes as rc

    _seed_import_then_loose_change()
    d = rc.get_batch_detail(-1, mode="collapsed")
    assert d is not None and "summary" in d and "changes" in d and "total_count" in d


def test_get_batch_detail_cap_and_total():
    import app.services.recent_changes as rc

    bid = _seed_import_batch_with_n_changes(600)  # > _RC_MAX_ROWS
    d = rc.get_batch_detail(bid, mode="raw")
    assert len(d["changes"]) == 500
    assert d["total_count"] == 600
