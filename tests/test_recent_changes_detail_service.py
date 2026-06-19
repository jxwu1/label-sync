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


def test_get_batch_detail_collapse_deterministic_on_tied_timestamp():
    """同 (barcode, field) 两条变更 created_at 完全相同 → 折叠须按 id 次级排序确定。

    seed 顺序（= 自增 id 顺序 = 语义正确的时间序）：
        row1: old=A new=B   (先发生)
        row2: old=B new=C   (后发生)
    两行 created_at 相同。正确折叠：from_value=first.old=A → to_value=last.new=C。

    sqlite 的 rowid 隐式有序可能让本测在未修复时也碰巧通过；但 PostgreSQL
    (生产后端) 对同值排序键不保证返回行序，仅 created_at 排序时 group[0]/group[-1]
    可能取反 → 显示 from→to 颠倒。显式追加 StockpileChange.id 次级排序键消除该
    非确定性，本测作为回归守护。
    """
    import app.services.recent_changes as rc

    bid = _seed_snapshot("2026-04-29 14:00:00")
    tied_at = "2026-04-29 13:00:00"
    _seed_change("BTIE", "stockpile_location", "A", "B", created_at=tied_at)
    _seed_change("BTIE", "stockpile_location", "B", "C", created_at=tied_at)

    d = rc.get_batch_detail(bid, mode="collapsed")
    rows = [c for c in d["changes"] if c["barcode"] == "BTIE"]
    assert len(rows) == 1
    assert rows[0]["from_value"] == "A"
    assert rows[0]["to_value"] == "C"


def _seed_import_batch_mixed_fields() -> int:
    """import 批次 + 混合 field/change_type changes，返回 batch_id。

    窗口内含：
      - 2 条 stockpile_location update（非 roundtrip）
      - 2 条 product_model update（非 roundtrip）
    → _summarize 给 location_changes=2 且 model_changes=2（两个非空桶）。
    """
    bid = _seed_snapshot("2026-04-29 14:00:00")
    _seed_change("L1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    _seed_change("L2", "stockpile_location", "B1", "B2", created_at="2026-04-29 13:00:10")
    _seed_change("M1", "product_model", "P1", "P2", created_at="2026-04-29 13:00:20")
    _seed_change("M2", "product_model", "Q1", "Q2", created_at="2026-04-29 13:00:30")
    return bid


def test_get_batch_detail_summary_ignores_filter():
    """summary 永远基于全窗口，与 filter_field 无关（最微妙的正确性不变量）。"""
    import app.services.recent_changes as rc

    bid = _seed_import_batch_mixed_fields()

    unfiltered = rc.get_batch_detail(bid, mode="collapsed")
    filtered = rc.get_batch_detail(bid, mode="collapsed", filter_field="stockpile_location")

    # summary 全量计算：两个桶都非空，且 model_changes 在“仅按 filtered 行算”时会变 0
    assert unfiltered["summary"]["location_changes"] == 2
    assert unfiltered["summary"]["model_changes"] == 2

    # 不变量：filtered 的 summary 与 unfiltered 完全一致（不随 filter 收窄）
    assert filtered["summary"] == unfiltered["summary"]
    # 判别桶：若 summary 误按 filtered 行算，model_changes 会是 0 → 此断言守护它
    assert filtered["summary"]["model_changes"] == 2

    # filter 确实收窄了 changes 列表（证明过滤生效，summary 独立性才有意义）
    assert filtered["total_count"] < unfiltered["total_count"]
    assert filtered["total_count"] == 2
    assert unfiltered["total_count"] == 4
    assert all(c["field"] == "stockpile_location" for c in filtered["changes"])
