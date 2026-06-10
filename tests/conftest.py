"""全局测试夹具：DB 隔离。

两种模式：
- 默认（本地）：autouse `_isolate_db` 每个测试用独立 tmp sqlite，绝不碰真实库 / PG。
- `TEST_DATABASE_URL` 设定时（CI 的 PG 矩阵腿）：统一 engine 指向该一次性 PG 库，
  schema 每会话 drop+create 一次，每个测试 TRUNCATE 全表隔离。
  绑死裸 sqlite3 的测试标 `sqlite_only` marker，PG 模式自动 skip。

只负责隔离，不做任何 seed——每个测试自己 seed。
`db_path` fixture：唯一裸 sqlite3 写入入口，与 SQLAlchemy engine 指向同一文件
（仅 sqlite 模式成立；用它裸写的测试必须标 sqlite_only）。
"""

import os

import pytest

# 注意：必须在 import 时读一次而非每个 fixture 里读——测试自身会 monkeypatch
# DATABASE_URL（如 test_db.py），但模式选择以进程启动时的意图为准。
TEST_PG_URL = os.environ.get("TEST_DATABASE_URL")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "sqlite_only: 测试绑死裸 sqlite3，TEST_DATABASE_URL（PG）模式下跳过"
    )


def pytest_collection_modifyitems(config, items):
    if not TEST_PG_URL:
        return
    skip = pytest.mark.skip(reason="裸 sqlite3 测试，PG 模式跳过")
    for item in items:
        if "sqlite_only" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def db_path(tmp_path):
    """per-test tmp sqlite 路径；裸 sqlite3 写入必须用它。"""
    return tmp_path / "stockpile.db"


@pytest.fixture(scope="session")
def _pg_schema():
    """PG 模式：schema 每会话建一次。先 drop_all 清掉上一轮残留，结构以 ORM 为准不走迁移。"""
    os.environ["DATABASE_URL"] = TEST_PG_URL
    from app import db
    from app.models import Base

    db.reset_engine()
    Base.metadata.drop_all(db.get_engine())
    db.ensure_db()
    yield
    db.reset_engine()


def _truncate_all_tables():
    from sqlalchemy import text

    from app import db
    from app.models import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with db.get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _isolate_db(db_path, monkeypatch, request):
    # 测试环境提供 secret，避免 create_app/init_auth 在 debug=False 下触发
    # 生产 fail-fast(FLASK_SECRET_KEY 缺失则拒启)。需要测该分支的用例自行 delenv。
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-key")
    from app import db
    from app.services import data_quality

    if TEST_PG_URL:
        request.getfixturevalue("_pg_schema")
        # 前一个测试可能改过 env（如 test_db.py），拉回 PG；engine 按 URL 缓存复用，
        # 不每测 dispose——重建连接池让全套慢 ~3 倍
        monkeypatch.setenv("DATABASE_URL", TEST_PG_URL)
        _truncate_all_tables()
        db.ensure_db()  # 补回 schema_meta bootstrap 行
    else:
        # 关键：清掉 DATABASE_URL，否则本地 dev.ps1 设了 PG 会直连 PG 而非 tmp。
        monkeypatch.delenv("DATABASE_URL", raising=False)
        db.reset_engine(db_path)
        db.ensure_db()
    # 模块级缓存与 per-test DB 隔离冲突：上个测试的报告不能漏进下个测试
    data_quality.clear_report_cache()
    yield
    if not TEST_PG_URL:
        db.reset_engine(db_path)  # 收尾 dispose，防止 tmp 文件句柄泄漏；PG engine 留给下个测试复用
