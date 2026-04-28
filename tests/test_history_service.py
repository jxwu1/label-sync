"""货号历史 service 单元测试。

测试覆盖：
- 双列精确搜索（model / barcode）
- 找不到的情形
- 5 秒窗口聚合
- 5 秒边界（4s 合并 / 6s 拆开）
- 事件按时间倒序
- source / change_type 取组内最新
"""

import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def memdb(tmp_path, monkeypatch):
    """提供一个内存级别的 stockpile.db，独立于真实数据库。"""
    import config
    db_path = tmp_path / "stockpile.db"
    # 由于 CONFIG 是 frozen dataclass，需要替换整个对象
    from dataclasses import replace
    new_cfg = replace(config.CONFIG, base_dir=tmp_path)
    monkeypatch.setattr(config, "CONFIG", new_cfg)
    # stockpile_db.DB_PATH 在模块加载时绑定，需要重新指向
    import stockpile_db
    monkeypatch.setattr(stockpile_db, "DB_PATH", db_path)
    stockpile_db.ensure_db()
    return db_path


def _insert_stockpile(db_path, **kwargs):
    conn = sqlite3.connect(str(db_path))
    cols = ",".join(kwargs.keys())
    placeholders = ",".join("?" * len(kwargs))
    conn.execute(f"INSERT INTO stockpile ({cols}) VALUES ({placeholders})", tuple(kwargs.values()))
    conn.commit()
    conn.close()


def _insert_change(db_path, barcode, field, old, new, ctype, at):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO stockpile_changes "
        "(product_barcode, field_name, old_value, new_value, change_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (barcode, field, old, new, ctype, at),
    )
    conn.commit()
    conn.close()


def test_find_record_by_barcode(memdb):
    import history_service
    _insert_stockpile(
        memdb,
        product_barcode="5828079100248",
        product_model="10024",
        stockpile_location="A22-04-04",
        is_active=1,
        source="scan_import",
    )
    rec = history_service.find_record("5828079100248")
    assert rec is not None
    assert rec["barcode"] == "5828079100248"
    assert rec["model"] == "10024"
    assert rec["location"] == "A22-04-04"
    assert rec["is_active"] is True
    assert rec["source"] == "scan_import"


def test_find_record_by_model(memdb):
    import history_service
    _insert_stockpile(
        memdb,
        product_barcode="5828079100248",
        product_model="10024",
        stockpile_location="A22-04-04",
        is_active=1,
        source="scan_import",
    )
    rec = history_service.find_record("10024")
    assert rec is not None
    assert rec["barcode"] == "5828079100248"


def test_find_record_not_found(memdb):
    import history_service
    assert history_service.find_record("does_not_exist") is None


def test_find_record_empty_input(memdb):
    import history_service
    assert history_service.find_record("") is None
    assert history_service.find_record("   ") is None


def test_aggregate_same_second_into_one_event(memdb):
    import history_service
    bc = "5828079100248"
    # 同一秒 4 条变更（仿真实 batch import 行为）
    for field, old, new in [
        ("product_model",      "10024", "10025"),
        ("stockpile_location", "A22-04-04", ""),
        ("product_model",      "10025", "10024"),
        ("stockpile_location", "", "A22-04-04"),
    ]:
        _insert_change(memdb, bc, field, old, new, "update", "2026-04-25 16:52:43")

    events = history_service.aggregate_events(bc)
    assert len(events) == 1
    assert events[0]["at"] == "2026-04-25 16:52:43"
    assert events[0]["change_type"] == "update"
    assert len(events[0]["changes"]) == 4


def test_aggregate_4_second_gap_merges(memdb):
    import history_service
    bc = "B1"
    _insert_change(memdb, bc, "stockpile_location", "X", "Y", "update", "2026-04-27 10:00:00")
    _insert_change(memdb, bc, "stockpile_location", "Y", "Z", "update", "2026-04-27 10:00:04")
    events = history_service.aggregate_events(bc)
    assert len(events) == 1
    assert len(events[0]["changes"]) == 2


def test_aggregate_6_second_gap_splits(memdb):
    import history_service
    bc = "B2"
    _insert_change(memdb, bc, "stockpile_location", "X", "Y", "update", "2026-04-27 10:00:00")
    _insert_change(memdb, bc, "stockpile_location", "Y", "Z", "update", "2026-04-27 10:00:06")
    events = history_service.aggregate_events(bc)
    assert len(events) == 2


def test_aggregate_returns_empty_when_no_changes(memdb):
    import history_service
    assert history_service.aggregate_events("never_exists") == []


def test_aggregate_orders_events_desc_by_time(memdb):
    import history_service
    bc = "B3"
    _insert_change(memdb, bc, "stockpile_location", "X", "Y", "update", "2026-04-25 10:00:00")
    _insert_change(memdb, bc, "stockpile_location", "Y", "Z", "update", "2026-04-26 10:00:00")
    _insert_change(memdb, bc, "stockpile_location", "Z", "W", "update", "2026-04-27 10:00:00")
    events = history_service.aggregate_events(bc)
    assert len(events) == 3
    assert events[0]["at"] > events[1]["at"] > events[2]["at"]


def test_build_response_found(memdb):
    import history_service
    _insert_stockpile(
        memdb,
        product_barcode="5828079100248",
        product_model="10024",
        stockpile_location="A22-04-04",
        is_active=1,
        source="scan_import",
    )
    _insert_change(memdb, "5828079100248", "stockpile_location", "X", "A22-04-04", "update", "2026-04-27 10:00:00")
    resp = history_service.build_response("10024")
    assert resp["found"] is True
    assert resp["current"]["barcode"] == "5828079100248"
    assert len(resp["events"]) == 1
    # source 注入：events[i]["source"] 应等于 current.source
    assert resp["events"][0]["source"] == "scan_import"


def test_build_response_not_found(memdb):
    import history_service
    resp = history_service.build_response("nope")
    assert resp["found"] is False
    assert "current" not in resp
    assert "events" not in resp
