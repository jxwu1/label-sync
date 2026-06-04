# DB engine/session 单一真源统一 + 测试 DB 隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DB engine/session/schema bootstrap 收口到单一 `app/db.py`，消除 models 与 stockpile_db 两套并存的 engine，并建立 autouse 测试 DB 隔离。

**Architecture:** 新建 `app/db.py` 为唯一真源（effective-URL 缓存、每次 new Session、reset_engine dispose-all、pool 按方言）。`models.py` 瘦身为 Base+ORM+lazy wrapper；`stockpile_db.py` 基础设施委托 db；`alembic/env.py` 改走 db。测试经 `tests/conftest.py` autouse 重定向到 per-test tmp sqlite。迁移期按 models 侧 / stockpile 侧分两批，组内逐文件改完即跑，保证每任务结束全绿。

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, pytest, ruff 0.15.12。

参考 spec：`docs/superpowers/specs/2026-06-04-db-engine-unification-design.md`

---

## File Structure

- **Create** `app/db.py` — engine/session/ensure_db/reset_engine 唯一真源。
- **Create** `tests/conftest.py` — autouse DB 隔离 + `db_path` fixture。
- **Create** `tests/test_db.py` — db 层 + reset_engine 残留回归测试。
- **Modify** `app/models.py` — 删 `DB_URL`/`_engine`/WAL/`_SessionFactory`；`get_session`/`get_engine` 改 lazy wrapper。
- **Modify** `app/repositories/stockpile_db.py` — 删 `_build_engine`/`_engine_cache`/`_bootstrap_schema_version`/`DB_PATH`；`_engine`/`_session`/`ensure_db`/`_connect` 委托 db。
- **Modify** `alembic/env.py` — `get_engine` 从 `app.db` 取。
- **Modify** ~21 测试文件 — 迁到 conftest 隔离 + `db_path`。

---

## Task 1: 建 `app/db.py` + db 层测试

**Files:**
- Create: `app/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: 写失败测试** — `tests/test_db.py`

```python
"""app.db 单一 engine 真源测试。"""

from sqlalchemy import text


def test_get_engine_caches_by_effective_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db

    db.reset_engine(tmp_path / "a.db")
    e1 = db.get_engine()
    e2 = db.get_engine()
    assert e1 is e2  # 同 URL 命中缓存


def test_reset_engine_switches_db_and_disposes(monkeypatch, tmp_path):
    """reset 到 A 写数据 → reset 到 B：B 看不到 A 的数据，且 effective URL 变化。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db

    url_a = db.reset_engine(tmp_path / "a.db")
    db.ensure_db()
    with db.get_session() as s:
        s.execute(text("CREATE TABLE t (x INTEGER)"))
        s.execute(text("INSERT INTO t VALUES (1)"))

    url_b = db.reset_engine(tmp_path / "b.db")
    db.ensure_db()
    assert url_a != url_b
    with db.get_session() as s:
        # B 库无表 t（A 的数据不可见）
        exists = s.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='t'")
        ).first()
        assert exists is None


def test_sqlite_uses_nullpool(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from sqlalchemy.pool import NullPool

    from app import db

    db.reset_engine(tmp_path / "a.db")
    assert isinstance(db.get_engine().pool, NullPool)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.db'`）

- [ ] **Step 3: 建 `app/db.py`**

```python
"""DB engine/session 单一真源。

所有 engine/session/schema bootstrap 收口于此：
- models.py 只放 Base + ORM + 兼容 wrapper(函数内 lazy import 本模块)
- stockpile_db.py / alembic/env.py / auth 经本模块取 engine/session
- 测试隔离：tests/conftest.py autouse 调 reset_engine(tmp) + ensure_db()

设计约束(见 spec)：
1. engine 按 effective URL 缓存(非仅 DB_PATH)
2. get_session 每次 new Session(不留全局 _SessionFactory)
3. reset_engine dispose 全部缓存 engine
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import CONFIG
from app.models import Base, SchemaMeta

SCHEMA_VERSION = 2

# 默认指向 CONFIG.stockpile_db；测试经 reset_engine 重定向。
DB_PATH = CONFIG.stockpile_db

_engine_cache: dict[str, Engine] = {}


def _effective_url() -> str:
    # DATABASE_URL 优先(PG)，否则回退 sqlite 文件
    return os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}"


def _build_engine(url: str) -> Engine:
    # pool 按方言：sqlite→NullPool(避线程锁/长连接状态)，其它(PG)→默认 QueuePool
    if url.startswith("sqlite"):
        engine = create_engine(url, future=True, poolclass=NullPool)
    else:
        engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_conn, _):
        # WAL 是 SQLite 专属；PG 不需要
        if engine.dialect.name != "sqlite":
            return
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def get_engine() -> Engine:
    url = _effective_url()
    cached = _engine_cache.get(url)
    if cached is not None:
        return cached
    engine = _build_engine(url)
    _engine_cache[url] = engine
    return engine


@contextmanager
def get_session() -> Iterator[Session]:
    session = Session(bind=get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _bootstrap_schema_version(engine: Engine) -> None:
    with Session(engine) as session:
        meta = session.execute(
            select(SchemaMeta).where(SchemaMeta.key == "schema_version")
        ).scalar_one_or_none()
        if meta is None:
            session.add(SchemaMeta(key="schema_version", value=str(SCHEMA_VERSION)))
        elif meta.value != str(SCHEMA_VERSION):
            meta.value = str(SCHEMA_VERSION)
        session.commit()


def ensure_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _bootstrap_schema_version(engine)


def reset_engine(db_path=None) -> str:
    """重置 engine：dispose 全部缓存 + 清空 + 可选重设 DB_PATH。返回新 effective URL。"""
    global DB_PATH
    for eng in _engine_cache.values():
        eng.dispose()
    _engine_cache.clear()
    if db_path is not None:
        DB_PATH = db_path
    return _effective_url()


def get_sqlite_path() -> str:
    """raw sqlite3 连接用：从 effective URL 解析真实 sqlite 文件路径。

    必须从 effective URL 解析(而非直接返回 DB_PATH)，否则 DATABASE_URL=sqlite:///其他文件
    时, engine 指 URL 文件而裸 sqlite3 指 DB_PATH → 分裂。非 sqlite(PG) 直接报错。
    用 make_url 解析(而非切前缀)，兼容 sqlite+pysqlite:///... 等合法 driver 变体。
    """
    parsed = make_url(_effective_url())
    if parsed.get_backend_name() != "sqlite":
        raise RuntimeError(
            f"get_sqlite_path() requires sqlite backend; effective URL is {parsed}. "
            "Rewrite caller to use SQLAlchemy session."
        )
    if not parsed.database:
        raise RuntimeError(f"sqlite URL has no database file: {parsed}")
    return parsed.database
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_db.py -v`
Expected: 3 passed

- [ ] **Step 5: ruff + 提交**

```bash
python -m ruff check app/db.py tests/test_db.py
python -m ruff format app/db.py tests/test_db.py
git add app/db.py tests/test_db.py
git commit -m "feat(db): app/db.py 单一 engine/session 真源 + reset_engine"
```

---

## Task 2: 建 `tests/conftest.py` autouse 隔离

此任务 additive：models/stockpile_db 尚未委托 db，autouse 只重定向 db.py 的 engine，对它们**暂无作用**。`delenv DATABASE_URL` 安全（CI 无该变量；本地修掉避免误连 PG）。

⚠️ **不要在此任务跑全量套件断言隔离生效**：此时旧 seam（models._SessionFactory / stockpile_db 自持 engine）仍在，全量"绿"是旧机制在撑，属**假绿**，证明不了 conftest 接管。全量绿的真实验收放到 Task 3/4（届时 models/stockpile_db 已委托 db）。本任务只验证 conftest 不破坏 db 层测试 + 不崩 collection。

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: 写 conftest**

```python
"""全局测试夹具：DB 隔离。

autouse `_isolate_db`：每个测试用独立 tmp sqlite，绝不碰真实库 / PG。
只负责隔离，不做任何 seed——每个测试自己 seed。
`db_path` fixture：唯一裸 sqlite3 写入入口，与 SQLAlchemy engine 指向同一文件。
"""

import pytest


@pytest.fixture
def db_path(tmp_path):
    """per-test tmp sqlite 路径；裸 sqlite3 写入必须用它。"""
    return tmp_path / "stockpile.db"


@pytest.fixture(autouse=True)
def _isolate_db(db_path, monkeypatch):
    # 关键：清掉 DATABASE_URL，否则本地 dev.ps1 设了 PG 会直连 PG 而非 tmp。
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db

    db.reset_engine(db_path)
    db.ensure_db()
    yield
    db.reset_engine(db_path)  # 收尾 dispose，防止 tmp 文件句柄泄漏
```

- [ ] **Step 2: 只验证 conftest 不破坏 db 层 + 不崩 collection**

Run: `python -m pytest tests/test_db.py -q`
Expected: 3 passed（conftest autouse 不干扰 db 层测试）

Run: `python -m pytest tests/ --collect-only -q > $null; echo "collect exit=$LASTEXITCODE"`（PowerShell；bash 用 `python -m pytest tests/ --collect-only -q >/dev/null; echo "collect exit=$?"`）
Expected: collect exit=0（conftest 不破坏任何文件的收集/导入）

注：此处**不跑全量断言隔离**——见任务开头 ⚠️。全量绿验收在 Task 3/4。

- [ ] **Step 3: 提交**

```bash
git add tests/conftest.py
git commit -m "test: autouse DB 隔离 conftest + db_path fixture(暂 inert)"
```

---

## Task 3: models 侧统一 + 迁移 models 侧测试

删 `models._engine`/`_SessionFactory` 会打断用它们的 11 个测试（10 个 monkeypatch `_SessionFactory` + history）。本任务一并迁移，组内逐文件改完即跑。

**Files:**
- Modify: `app/models.py`
- Modify: `tests/test_history_service.py`
- Modify: `tests/test_attendance_import.py`, `tests/test_attendance_import_routes.py`, `tests/test_attendance_report_service.py`, `tests/test_attendance_routes.py`, `tests/test_attendance_service.py`, `tests/test_pda_routes.py`, `tests/test_pda_seed.py`, `tests/test_purchase_orders.py`, `tests/test_scan_session_repository.py`, `tests/test_scan_session_service.py`

- [ ] **Step 1: 改 `app/models.py` import 区**

把 `app/models.py:16` 的 `import os` 删除（DB_URL 移走后不再用）。

把 `app/models.py:20-31` 的 sqlalchemy import 块里 `create_engine,` 和 `event,` 两行删除（保留 JSON/ForeignKey/Index/Integer/Text/UniqueConstraint/func/text）。

把 `app/models.py:33-40` 的 orm import 块里 `sessionmaker,` 删除（保留 DeclarativeBase/Mapped/Session/mapped_column/relationship）。

- [ ] **Step 2: 删 `app/models.py:44-57` 的 engine/WAL 块**

删除这一段（DB_URL / _engine / @event WAL listener）：

```python
# DATABASE_URL 环境变量优先（PG 迁移用），回退 SQLite 文件
DB_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{CONFIG.stockpile_db}"

_engine: Engine = create_engine(DB_URL, future=True)


@event.listens_for(_engine, "connect")
def _enable_wal(dbapi_conn, _) -> None:
    # WAL 是 SQLite 专属；PG 不需要这个 PRAGMA
    if _engine.dialect.name != "sqlite":
        return
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
```

注意：`CONFIG` 若在 models 别处仍用则保留 import；若已不用，ruff 会在 Step 7 报 F401，按提示删。

- [ ] **Step 3: 改 `app/models.py:691-708` 为 lazy wrapper**

把这段：

```python
_SessionFactory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine() -> Engine:
    return _engine
```

替换为：

```python
# engine/session 真源在 app.db；以下为兼容 wrapper(函数内 lazy import 避免循环：
# app.db 顶层 from app.models import Base, SchemaMeta，models 顶层不得 import app.db)。


@contextmanager
def get_session() -> Iterator[Session]:
    from app.db import get_session as _db_get_session

    with _db_get_session() as session:
        yield session


def get_engine() -> Engine:
    from app.db import get_engine as _db_get_engine

    return _db_get_engine()
```

- [ ] **Step 4: 验证 import 不循环 + db 测试仍绿**

Run: `python -c "import app.db; import app.models; from app.models import get_session, get_engine; print('ok')"`
Expected: 打印 `ok`，无 ImportError。

Run: `python -m pytest tests/test_db.py -v`
Expected: 3 passed

- [ ] **Step 5: 迁移 `tests/test_history_service.py`**

`memdb` fixture（当前 monkeypatch `stockpile_db.DB_PATH` + 调 `ensure_db`）改为复用 conftest 的 `db_path`（autouse 已隔离 engine + ensure_db）。把 fixture 体替换为直接返回 `db_path`：

```python
@pytest.fixture
def memdb(db_path):
    """复用 conftest autouse 隔离的 tmp 库；返回路径供裸 sqlite3 写入。"""
    return db_path
```

删除 fixture 内原有的 `from app import config` / `replace` / `monkeypatch.setattr(stockpile_db, "DB_PATH", ...)` / `stockpile_db.ensure_db()` 等行。`_history_client()`（已存在的最小 app）保持不变。

Run: `python -m pytest tests/test_history_service.py -q`
Expected: 33 passed

- [ ] **Step 6: 逐文件迁移 10 个 `_SessionFactory` 测试**

对每个文件做同一变换，**改完一个立即跑该文件**：

变换：删除形如下的 `_SessionFactory` 重绑（不同文件命名略有差异，搜 `_SessionFactory` 定位）：

```python
# 删除这类行：
monkeypatch.setattr(models, "_SessionFactory", sessionmaker(bind=test_engine))
# 及其配套的自建 test_engine / create_engine(...) / ensure_db on it
```

迁移到：依赖 conftest autouse（`models.get_session()` 现在走 db engine→tmp）。测试 seed 改用 `get_session()` 或 `db_path`（裸 sqlite3）。若该文件还自算 tmp db 路径，统一改用 `db_path` fixture。

逐文件命令（改一个跑一个）：

```bash
python -m pytest tests/test_attendance_import.py -q
python -m pytest tests/test_attendance_import_routes.py -q
python -m pytest tests/test_attendance_report_service.py -q
python -m pytest tests/test_attendance_routes.py -q
python -m pytest tests/test_attendance_service.py -q
python -m pytest tests/test_pda_routes.py -q
python -m pytest tests/test_pda_seed.py -q
python -m pytest tests/test_purchase_orders.py -q
python -m pytest tests/test_scan_session_repository.py -q
python -m pytest tests/test_scan_session_service.py -q
```
Expected: 每个文件全绿。若某文件同时用 stockpile_db 裸写自路径导致 SQLAlchemy/sqlite3 指向不一致，把其裸写路径也改成 `db_path`。

- [ ] **Step 7: ruff + 全量 + 提交**

```bash
python -m ruff check app/models.py tests/
python -m ruff format app/models.py tests/
python -m pytest tests/ -q
```
Expected: ruff 0 errors；pytest ≥1002 passed, 0 failed（注：stockpile_db 仍自持 engine，但其测试经各自 DB_PATH monkeypatch 仍有效，未受本任务影响）。

```bash
git add app/models.py tests/
git commit -m "refactor(models): engine/session 委托 app.db + 迁移 models 侧测试到 conftest 隔离"
```

---

## Task 4: stockpile_db 侧统一 + 迁移 stockpile 侧测试

删 `stockpile_db.DB_PATH`/`_engine_cache`/`_build_engine`/`_bootstrap_schema_version` 会打断用它们的约 11 个测试，一并迁移。

**Files:**
- Modify: `app/repositories/stockpile_db.py`
- Modify: `tests/test_analytics_service.py`, `tests/test_backtest_service.py`, `tests/test_categorizer.py`, `tests/test_data_freshness.py`, `tests/test_data_quality_service.py`, `tests/test_fetch_rows_dedup.py`, `tests/test_forecast_data.py`, `tests/test_forecast_service.py`, `tests/test_foreign_customer_routes.py`, `tests/test_foreign_customer_service.py`, `tests/test_inventory_routes.py`, `tests/test_models_smoke.py`, `tests/test_recent_changes_routes.py`, `tests/test_recent_changes_service.py`, `tests/test_restock_decisions.py`, `tests/test_routes_analytics.py`, `tests/test_sku_summary.py`, `tests/test_stockpile_db.py`, `tests/test_stockpile_locations.py`, `tests/test_stockpile_routes.py`

- [ ] **Step 1: 改 `app/repositories/stockpile_db.py` engine 区**

删除 `app/repositories/stockpile_db.py:29` 的 `DB_PATH = CONFIG.stockpile_db`。

删除 `app/repositories/stockpile_db.py:71-120` 区间内自持的引擎机制：`_engine_cache` / `_build_engine` / `_engine` / `_bootstrap_schema_version` / `ensure_db`（这些已在 db.py）。本文件的 `SCHEMA_VERSION = 2`（line 30）也删除（已移至 db.py；若有引用改 `from app.db import SCHEMA_VERSION`）。

新增委托实现（放原 engine 区位置）：

```python
def _engine():
    from app import db

    return db.get_engine()


def ensure_db() -> None:
    from app import db

    db.ensure_db()
```

`_session()`（原 157-167）改为委托：

```python
@contextmanager
def _session() -> Iterator[Session]:
    from app import db

    with db.get_session() as session:
        yield session
```

`_connect()`（原 123-140）改为读 db 的引擎/路径：

```python
def _connect() -> sqlite3.Connection:
    """raw sqlite3 连接，仅供需绕过 ORM 的旧测试 / 维护脚本。"""
    from app import db

    db.ensure_db()
    if db.get_engine().dialect.name != "sqlite":
        raise RuntimeError(
            "_connect() requires SQLite backend; current engine is "
            f"{db.get_engine().dialect.name}. Rewrite caller to use SQLAlchemy session."
        )
    # 从 effective URL 解析真实 sqlite 文件(处理 DATABASE_URL=sqlite:///x 场景)，
    # 不能直接用 db.DB_PATH 否则与 engine 分裂。
    conn = sqlite3.connect(db.get_sqlite_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
```

清理本文件不再使用的 import（如 `create_engine` / `event` / `NullPool`）。**注意**：`select` / `func` / `delete` 等被 repository 查询大量使用，**不要机械删除**——一律以 Step 6 `ruff check` 报出的 F401 为准，按提示删，不靠肉眼猜。

- [ ] **Step 2: 验证 stockpile_db 委托可用**

Run: `python -c "from app.repositories import stockpile_db; from app import db; db.reset_engine(); print(stockpile_db._engine() is db.get_engine())"`
Expected: 打印 `True`

- [ ] **Step 3: 迁移 stockpile 侧测试（逐文件改完即跑）**

各文件的 DB 重定向夹具（形如 `monkeypatch.setattr(stockpile_db, "DB_PATH", x)` + `_engine_cache.clear()` + `ensure_db()`）现已失效（属性删除）。变换：

```python
# 删除：
monkeypatch.setattr(stockpile_db, "DB_PATH", some_tmp)
stockpile_db._engine_cache.clear()
stockpile_db.ensure_db()
# 改为：依赖 conftest autouse（已隔离 engine + ensure_db）。
# 裸 sqlite3 写入 / 自算路径 → 统一用 conftest 的 db_path fixture。
```

把每个文件里"自算 tmp db 路径"的局部变量替换为 `db_path` fixture 参数。逐文件命令：

```bash
for f in test_analytics_service test_backtest_service test_categorizer test_data_freshness \
  test_data_quality_service test_fetch_rows_dedup test_forecast_data test_forecast_service \
  test_foreign_customer_routes test_foreign_customer_service test_inventory_routes \
  test_models_smoke test_recent_changes_routes test_recent_changes_service test_restock_decisions \
  test_routes_analytics test_sku_summary test_stockpile_db test_stockpile_locations test_stockpile_routes; do
  python -m pytest tests/$f.py -q || break
done
```
Expected: 每个文件全绿（`|| break` 在首个失败处停，便于定位）。

- [ ] **Step 4: ruff hook 测试不受 DB 影响确认**

`tests/test_guard_hooks.py` 不依赖 DB，但确认 autouse `_isolate_db`（只动 DB engine）不干扰。

Run: `python -m pytest tests/test_guard_hooks.py -q`
Expected: 20 passed

- [ ] **Step 5: 全量套件**

Run: `python -m pytest tests/ -q`
Expected: ≥1002 passed, 0 failed

- [ ] **Step 6: ruff + 提交**

```bash
python -m ruff check app/repositories/stockpile_db.py tests/
python -m ruff format app/repositories/stockpile_db.py tests/
git add app/repositories/stockpile_db.py tests/
git commit -m "refactor(stockpile_db): 基础设施委托 app.db + 迁移 stockpile 侧测试到 conftest 隔离"
```

---

## Task 5: alembic/env.py 改走 app.db

**Files:**
- Modify: `alembic/env.py`

- [ ] **Step 1: 改 import**

把 `alembic/env.py:7` 的：

```python
from app.models import Base, get_engine
```

改为：

```python
from app.db import get_engine
from app.models import Base
```

`run_migrations_online()` 里 `get_engine()`（line 74）与 `LABEL_SYNC_DB_PATH` 覆盖逻辑（`_env_db_url` + line 70-72 自建 NullPool engine）保持不变。

- [ ] **Step 2: 验证 env.py 的 engine 接线**

⚠️ **不要用"空库 `alembic upgrade head` 成功"作为验收**：既有迁移 `2385c879eb58_add_stockpile_locations_subtable` 在 `upgrade()` 里做数据迁移 `SELECT id, stockpile_location FROM stockpile`，**假设 stockpile 表已存在**——空库从头 upgrade 时该表尚未建，offline `--sql` 渲染时 `op.get_bind()` 为 None，两者都会失败。这是**与本任务无关的既有迁移 bug**（本重构 Non-goals: 不改 alembic 迁移），记 backlog，不在此修。

本任务只改了 `get_engine` 的来源（models → app.db），验收限于接线正确：

```
.venv/Scripts/python.exe -c "from app.db import get_engine; from app.models import Base; print('imports ok')"
```
Expected: 打印 `imports ok`（env.py 的两个 import 均可解析；`get_engine` 来自 app.db）。

注：env.py 的 `LABEL_SYNC_DB_PATH` 覆盖块（online mode 自建 NullPool sqlite engine）保持不变；`migration-temp-db-guard` hook 仍要求 online alembic 必带 `LABEL_SYNC_DB_PATH`。真正跑迁移要在**已有 schema 的库**上增量执行，而非空库 from-scratch。

- [ ] **Step 3: ruff + 提交**

```bash
python -m ruff check alembic/env.py
git add alembic/env.py
git commit -m "refactor(alembic): env.py get_engine 改从 app.db 取"
```

---

## Task 6: reset_engine 全链路残留回归测试（4 层断言）

所有层已委托 db，补 spec 要求的 `test_db_reset_engine` 验证无旧 engine/factory 残留。

**Files:**
- Modify: `tests/test_db.py`

- [ ] **Step 1: 追加 4 层断言测试**

在 `tests/test_db.py` 末尾追加：

```python
def test_db_reset_engine_no_stale_across_layers(monkeypatch, tmp_path):
    """reset 到 A 写 user → reset 到 B：db / stockpile_db / models 三层都查 B，看不到 A。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app import db
    from app.models import User, get_session
    from app.repositories import stockpile_db

    # A 库：建 schema + 插一个 user
    db.reset_engine(tmp_path / "A.db")
    db.ensure_db()
    with db.get_session() as s:
        s.add(
            User(
                username="alice",
                password_hash="x",
                display_name="A",
                theme="light",
                role="admin",
            )
        )

    # 切到 B 库
    url_b = db.reset_engine(tmp_path / "B.db")
    db.ensure_db()
    assert url_b.endswith("B.db")

    # ① db.get_engine() 反映新 URL
    assert str(db.get_engine().url).endswith("B.db")
    # ② db.get_session() 查 B（无 alice）
    with db.get_session() as s:
        assert s.query(User).count() == 0
    # ③ stockpile_db._session() 也查 B
    with stockpile_db._session() as s:
        assert s.query(User).count() == 0
    # ④ models.get_session() lazy wrapper 也查 B
    with get_session() as s:
        assert s.query(User).count() == 0
```

- [ ] **Step 2: 跑测试**

Run: `python -m pytest tests/test_db.py -v`
Expected: 全绿（含新 `test_db_reset_engine_no_stale_across_layers`）

- [ ] **Step 3: 全量 + ruff 终验**

```bash
python -m pytest tests/ -q
python -m ruff check .
python -m ruff format --check .
```
Expected: pytest ≥1003 passed, 0 failed；ruff check All checks passed；format all formatted。

- [ ] **Step 4: 提交**

```bash
git add tests/test_db.py
git commit -m "test(db): reset_engine 跨 db/stockpile_db/models 三层无残留回归"
```

---

## Self-Review

- **Spec 覆盖**：§1 app/db.py(Task1) / models 瘦身(Task3) / stockpile_db 委托(Task4) / alembic(Task5)；§2 conftest autouse + db_path(Task2) + 测试迁移(Task3/4)；effective-URL 缓存(Task1 Step3)；get_session 无 _SessionFactory(Task1)；reset dispose-all(Task1)；delenv DATABASE_URL 硬性(Task2/conftest)；test_db_reset_engine 4 层(Task6)。全覆盖。
- **迁移顺序**：models 侧(Task3) 与 stockpile 侧(Task4) 分批，删旧 seam 与迁对应测试同任务，组内逐文件改完即跑——每任务结束全绿。
- **循环 import**：db→models 顶层；models→db 仅函数内 lazy；stockpile_db/alembic→db 单向。Task3 Step4 显式验证。
- **类型/命名一致**：`get_engine`/`get_session`/`ensure_db`/`reset_engine`/`_effective_url`/`DB_PATH`/`_engine_cache` 全任务一致。
- **ruff 可复现**：`ruff==0.15.12` 已在 requirements-dev.txt（勘误见 spec）。
- **残留风险**：Task6 4 层断言专守 reset 后 engine/factory 残留（spec 标注的最大风险）。
