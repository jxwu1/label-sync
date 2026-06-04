# DB engine/session 单一真源统一 + 测试 DB 隔离 Design

**Date:** 2026-06-04
**Status:** Approved (待转 writing-plans)

## Goal

- **action:** 统一 DB engine/session 真源到 `app/db.py`，并建立 autouse 测试 DB 隔离。
- **verify:** `tests/test_db_reset_engine` 通过 + 全量 `pytest tests/`(≥1002) 通过 + `python -m ruff check .` 通过。

## 背景 / 根因

当前两套独立的 engine/session 基础设施：

- `app/models.py`：`DB_URL`/`_engine`/`_SessionFactory` 在**导入时**冻结绑定；`get_session`/`get_engine` 用它。auth、scan_session、多路由/服务依赖。**无法被测试重定向**。
- `app/repositories/stockpile_db.py`：自有 `DB_PATH` + `_engine()`(按路径缓存) + `_build_engine` + `ensure_db` + `_session` + `_connect`。动态读 `DB_PATH` → 测试可 monkeypatch。

两者都从 `DATABASE_URL or sqlite:///{CONFIG.stockpile_db}` 取源，正常指向同库，但 models 那套改不动。后果（2026-06-04 实测）：`test_history_service` 3 个 route 测试 `from server import app` → `init_auth`→`_seed_admin` 经 models engine 撞上退役本地 `stockpile.db`(缺 `role` 列) → `no such column: users.role`。测试只重定向了 stockpile_db 一侧，models 一侧分裂。

第三个入口：`alembic/env.py` 走 `app.models.get_engine`。

## Non-goals (YAGNI)

- 不删除退役的 502MB 本地 `stockpile.db`（单独确认后处理）。
- 不改业务查询/导入逻辑，不动 ORM schema，不加 alembic 迁移。
- 不引入连接池调优以外的性能改造。

## §1 架构

新建 **`app/db.py`——唯一 engine/session 真源**：

| db.py 提供 | 说明 |
|---|---|
| `DB_PATH` 模块全局 | 默认 `CONFIG.stockpile_db`，测试可重定向 |
| effective URL 解析 | `DATABASE_URL` 存在用它，否则 `sqlite:///{DB_PATH}` |
| `get_engine()` | 懒加载，**按 effective URL 缓存**（非仅 DB_PATH）；WAL 监听器；pool 按方言：sqlite→`NullPool`，其它→默认 `QueuePool` |
| `get_session()` | contextmanager，**每次 `Session(bind=get_engine(), expire_on_commit=False)`**，不留全局 `_SessionFactory` |
| `ensure_db()` | `create_all` + `schema_version` bootstrap |
| `reset_engine(db_path=None)` | dispose **全部**缓存 engine + 清 cache + 重设 DB_PATH；返回新 effective URL 供断言 |

模块职责收敛后：

- **`models.py`**：只放 `Base` + ORM classes + **compatibility wrappers**。`get_session`/`get_engine` 为薄壳，**函数体内 lazy import `app.db`**（避免循环：db.py 顶层 `from app.models import Base, SchemaMeta`，models 顶层绝不 import app.db）。WAL 监听器移入 db.py。
- **`stockpile_db.py`**：纯 repository（查询/导入逻辑）。删除自己的 `_build_engine`/`_engine_cache`/`_bootstrap_schema_version`；`_engine`/`_session`/`ensure_db`/`_connect` 委托 `app.db`。**不再保留独立 `DB_PATH` 变量**；若有残留只读引用，动态读 `app.db.DB_PATH`。
- **`alembic/env.py`**：`from app.db import get_engine` + `from app.models import Base`；保留 `LABEL_SYNC_DB_PATH` 覆盖（online mode 自建 NullPool sqlite engine）。

### 设计约束（硬性）

1. engine 缓存 key = effective URL，不只 DB_PATH（否则改 `DATABASE_URL`/`DB_PATH` 后复用旧 engine）。
2. `get_session()` 不用全局 `_SessionFactory`（否则 `reset_engine()` 后旧 factory 绑旧 engine）。
3. `reset_engine()` 必须 dispose 全部旧 engine 并清 cache，保证后续 `get_engine()` 重建。
4. `ensure_db()` 在 db.py top-level import `Base, SchemaMeta`；models wrapper 必须函数内 lazy import。
5. 不保留分裂的 `stockpile_db.DB_PATH`；测试统一迁到 `db.reset_engine(...)`。

## §2 测试隔离

新建 **`tests/conftest.py`（autouse 全局隔离）**：

- autouse fixture `_isolate_db(tmp_path, monkeypatch)`：
  1. **`monkeypatch.delenv("DATABASE_URL", raising=False)`** —— 硬性验收点。否则本地 dev.ps1 设了 `DATABASE_URL=PG`，测试会直连 PG 而非 tmp。
  2. `db.reset_engine(tmp_path / "stockpile.db")` + `db.ensure_db()` 建全新 schema（自带 `role`，stale 问题根除）。
  3. **只负责隔离默认 DB，不做任何 seed**——每个测试自己 seed，避免隐式状态。
- `db_path` fixture：返回该 tmp 路径，是**唯一裸 sqlite3 写入入口**。旧测试里自算 tmp db path 的，统一迁到 `db_path`，杜绝「SQLAlchemy 走 A、sqlite3 写 B」。

### 测试迁移（逐文件，改完即跑，绝不 big-bang）

顺序：

1. `test_history_service.py`（当前失败源；已临时改最小 app，本次再迁到 conftest）。
2. 用 `models._SessionFactory` monkeypatch 的 10 个：`test_attendance_import` / `_attendance_import_routes` / `_attendance_report_service` / `_attendance_routes` / `_attendance_service` / `test_pda_routes` / `test_pda_seed` / `test_purchase_orders` / `test_scan_session_repository` / `test_scan_session_service`。**注意**：删 `models._SessionFactory` 会打断这 10 个 → 迁移与删除同步（或留临时 shim 过渡后再删），保持每步可跑。
3. 只碰 `stockpile_db.DB_PATH`/`_engine_cache` 的约 11 个。

## 构建顺序

1. 建 `app/db.py`（effective-URL 缓存 / get_engine / get_session 每次 new Session / ensure_db / reset_engine dispose-all）。
2. `models.py` 瘦身 → Base+ORM + lazy wrapper；WAL 移走。
3. `stockpile_db.py` 基础设施委托 db，留 repository 逻辑。
4. `alembic/env.py` → app.db。
5. `tests/conftest.py` autouse + db_path。
6. 逐文件迁移 ~21 测试（顺序见上）。
7. 全量绿（≥1002）+ ruff 干净。

## 验证与验收

- **硬性**：autouse fixture 清掉 `DATABASE_URL`，测试绝不连 PG。
- **`tests/test_db_reset_engine`**（覆盖 session factory 残留——最大风险）：
  - reset 到 A 写数据 → reset 到 B：`get_engine()` after reset 是新对象/至少新 effective URL；
  - `get_session()` after reset 查 B、看不到 A 的数据；
  - `stockpile_db._session()` 也查 B；
  - `models.get_session()` lazy wrapper 也查 B。
- 全量 `pytest tests/` ≥1002 passed, 0 failed。
- `python -m ruff check .` 通过（`ruff==0.15.12` 已在 `requirements-dev.txt`，可复现；勘误：原担心 dev 依赖缺 ruff 已不成立）。

## 风险

- **最大风险**：`reset_engine()` 后旧 engine/session factory 残留 → 由 `test_db_reset_engine` 4 项断言守住。
- 删 `models._SessionFactory` 打断 10 个测试 → 同步迁移或临时 shim。
- ~21 测试迁移面广 → 逐文件改、改完即跑兜底。
- 循环 import → db↔models 方向固定（db→models 顶层；models→db 仅函数内），alembic/stockpile_db→db 单向。
