"""货号历史 service 单元测试。

测试覆盖：
- 双列精确搜索（model / barcode）
- 找不到的情形
- 5 秒窗口聚合
- 5 秒边界（4s 合并 / 6s 拆开）
- 事件按时间倒序
- source / change_type 取组内最新
"""

import sqlite3

import pytest


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
        ("product_model", "10024", "10025"),
        ("stockpile_location", "A22-04-04", ""),
        ("product_model", "10025", "10024"),
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
    _insert_change(
        memdb,
        "5828079100248",
        "stockpile_location",
        "X",
        "A22-04-04",
        "update",
        "2026-04-27 10:00:00",
    )
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


def test_route_history_returns_json(memdb):
    """用 Flask test client 验证 GET /history 工作。"""
    _insert_stockpile(
        memdb,
        product_barcode="5828079100248",
        product_model="10024",
        stockpile_location="A22-04-04",
        is_active=1,
        source="scan_import",
    )
    from server import app

    client = app.test_client()
    resp = client.get("/history?q=10024")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["found"] is True
    assert body["current"]["barcode"] == "5828079100248"


def test_route_history_missing_q_returns_400(memdb):
    from server import app

    client = app.test_client()
    resp = client.get("/history")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_route_history_not_found(memdb):
    from server import app

    client = app.test_client()
    resp = client.get("/history?q=nope")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is False


# ===== split_location 单测：纯函数，无需 fixture =====

_EMPTY_SPLIT = {"stores": [], "warehouses": [], "unknown": []}


def test_split_location_empty():
    import history_service

    assert history_service.split_location("") == _EMPTY_SPLIT
    assert history_service.split_location(None) == _EMPTY_SPLIT


def test_split_location_store_only():
    import history_service

    assert history_service.split_location("A22-04-04") == {
        "stores": ["A22-04-04"],
        "warehouses": [],
        "unknown": [],
    }


def test_split_location_warehouse_only():
    import history_service

    assert history_service.split_location("X11-02") == {
        "stores": [],
        "warehouses": ["X11-02"],
        "unknown": [],
    }


def test_split_location_store_plus_warehouse():
    import history_service

    assert history_service.split_location("A22-04-04/X11-02") == {
        "stores": ["A22-04-04"],
        "warehouses": ["X11-02"],
        "unknown": [],
    }


def test_split_location_multi_store_future_compat():
    """阶段 1.5 schema 改造后可能出现的多段——展示层提前兼容。"""
    import history_service

    assert history_service.split_location("A22/B13/X11") == {
        "stores": ["A22", "B13"],
        "warehouses": ["X11"],
        "unknown": [],
    }


def test_split_location_unknown_prefix_goes_to_unknown_column():
    """阶段 1.5 PR2：异常前缀进 unknown 列单独展示，不再静默丢弃。"""
    import history_service

    assert history_service.split_location("A22/Q99/X11") == {
        "stores": ["A22"],
        "warehouses": ["X11"],
        "unknown": ["Q99"],
    }


# ===== build_response 注入拆分字段 =====


def test_build_response_injects_split_into_current(memdb):
    """current 状态走子表 stockpile_locations。
    用 stockpile_db.import_from_dataframe 走正常 dual-write 路径填子表。"""
    import pandas as pd

    import history_service
    import stockpile_db

    stockpile_db.import_from_dataframe(
        pd.DataFrame(
            [
                {
                    "product_barcode": "BC1",
                    "product_model": "M1",
                    "stockpile_location": "A22-04-04/X11-02",
                }
            ]
        )
    )
    resp = history_service.build_response("BC1")
    assert resp["current"]["location"] == "A22-04-04/X11-02"  # 原字段保留
    assert resp["current"]["store_locations"] == ["A22-04-04"]
    assert resp["current"]["warehouse_locations"] == ["X11-02"]
    assert resp["current"]["unknown_locations"] == []


def test_build_response_current_with_unknown_prefix(memdb):
    """子表中的 unknown kind 出现在 current.unknown_locations。"""
    import pandas as pd

    import history_service
    import stockpile_db

    stockpile_db.import_from_dataframe(
        pd.DataFrame(
            [
                {
                    "product_barcode": "BCU",
                    "product_model": "MU",
                    "stockpile_location": "A22/Q99/X11",
                }
            ]
        )
    )
    resp = history_service.build_response("BCU")
    assert resp["current"]["store_locations"] == ["A22"]
    assert resp["current"]["warehouse_locations"] == ["X11"]
    assert resp["current"]["unknown_locations"] == ["Q99"]


def test_build_response_injects_split_into_location_changes(memdb):
    import history_service

    _insert_stockpile(
        memdb,
        product_barcode="BC2",
        product_model="M2",
        stockpile_location="A22/X11",
        is_active=1,
        source="scan_import",
    )
    _insert_change(
        memdb, "BC2", "stockpile_location", "A22", "A22/X11", "update", "2026-04-27 10:00:00"
    )
    _insert_change(memdb, "BC2", "product_model", "M0", "M2", "update", "2026-04-27 10:00:00")
    resp = history_service.build_response("BC2")
    changes = resp["events"][0]["changes"]
    loc_change = next(c for c in changes if c["field"] == "stockpile_location")
    model_change = next(c for c in changes if c["field"] == "product_model")
    assert loc_change["old_split"] == {"stores": ["A22"], "warehouses": [], "unknown": []}
    assert loc_change["new_split"] == {"stores": ["A22"], "warehouses": ["X11"], "unknown": []}
    # 非 location 的 change 不该被注入 split
    assert "old_split" not in model_change
    assert "new_split" not in model_change
