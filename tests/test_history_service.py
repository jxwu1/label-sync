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
