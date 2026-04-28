# 货号历史页 + admin 清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 端新增第 5 个 tab "📜 货号历史"，输入条码或型号（精确）→ 显示当前主表状态 + 5 秒窗口聚合的变更时间线；同时删除已成死代码的 `/admin` 页面与 `/stats` 路由。

**Architecture:** 后端只读访问已有的 `stockpile` 与 `stockpile_changes` 两张表（无 schema 变更），加 1 个 blueprint + 1 个 service。前端复用 filing-cabinet 主题（Solarized + tokens.css），新增独立 page section / css / js 三件套。Admin 清理与新功能在同一分支完成。

**Tech Stack:** Flask Blueprint, sqlite3, vanilla JS (ESM), pytest。

**Spec：** `docs/superpowers/specs/2026-04-28-model-history-design.md`

---

## File Structure

| 文件 | 操作 | 说明 |
|---|---|---|
| `history_service.py` | 新建 | DB 查询（`find_record(q)`）+ 5 秒窗口聚合（`aggregate_events(barcode)`）+ 顶层 `build_response(q)` |
| `routes_history.py` | 新建 | Blueprint，1 个端点 `GET /history?q=` |
| `tests/test_history_service.py` | 新建 | 单元测试：搜索 / 找不到 / 聚合 / 5s 边界 |
| `routes.py` | 改 | 注册 `routes_history.bp` |
| `templates/index.html` | 改 | nav 加第 5 项 + page section + css/js link |
| `static/js/history.js` | 新建 | 搜索调用 + 渲染时间线 |
| `static/css/page-history.css` | 新建 | 页面样式（沿用 tokens） |
| `static/js/index.js` | 改 | tab 切换包含 history |
| `templates/admin.html` | 删 | 已成死代码 |
| `static/css/admin.css` | 删 | 同上 |
| `static/js/admin.js` | 删 | 同上 |
| `static/js/admin-messaging.js` | 删 | 同上（A 端有 messaging.js） |
| `static/js/admin-transfer.js` | 删 | 同上（A 端有 transfer.js） |
| `routes_pages_tasks.py` | 改 | 删 `/admin` 路由 3 行 |
| `routes_query.py` | 改 | 删 `/stats` 路由 |
| `query_service.py` | 改 | 删 `read_monthly_stats()` + `_YYYYMMDD_LEN` 等相关常量 + `re` / `datetime` / `defaultdict` import（如不再被用） |
| `使用文档.md` | 改 | 删 `/admin` 段落 |
| `README.md` | 改 | 删 `/admin` URL 提及 |

---

## Verification Strategy

1. **单元测试必过**：`pytest tests/test_history_service.py -v`
2. **回归测试必过**：`pytest tests/ -v`（其它现有 tests 不能因 admin/stats 删除而退化）
3. **standards / encoding**：`scripts/check-standards.ps1` 与 `scripts/check-encoding.ps1` 退出码 0
4. **手测**（最后 Task）：起服务，5 个 tab + 已知 barcode/model 搜索 + 不存在搜索 + 互传 + 采购页月度采购总结 + `/admin` 与 `/stats` 404

---

## Task 1：建分支 + 占位测试文件 + 探明 stockpile 测试样本

**Files:**
- Branch: `feature/model-history`
- Create: `tests/test_history_service.py`

- [ ] **Step 1：创建分支**

```bash
git checkout -b feature/model-history
git status
```
Expected: `On branch feature/model-history` / `nothing to commit, working tree clean`

- [ ] **Step 2：选两条真实样本作为后续单测参考（不入测试，只记下）+ 校验单货号变更上限**

```bash
python -c "
import sqlite3
c = sqlite3.connect('stockpile.db')
print('--- 一个有多次变更的 barcode ---')
r = c.execute('SELECT product_barcode, product_model FROM stockpile_changes GROUP BY product_barcode HAVING COUNT(*) >= 4 LIMIT 1').fetchone()
print(r)
print('--- 一个 barcode != model 的活跃货号 ---')
r = c.execute(\"SELECT product_barcode, product_model FROM stockpile WHERE product_barcode != product_model AND is_active = 1 LIMIT 1\").fetchone()
print(r)
print('--- 单货号变更上限（spec 风险点核验）---')
r = c.execute('SELECT product_barcode, COUNT(*) AS n FROM stockpile_changes GROUP BY product_barcode ORDER BY n DESC LIMIT 5').fetchall()
for row in r: print(f'  {row[0]}: {row[1]} 条')
"
```
记下输出的两组 barcode/model（后续 Task 11 手测会用到）。

**Spec 风险点判定**：spec §9 假设单货号变更 < 100。看上面"单货号变更上限"输出：
- 如果最大值 < 100：通过，继续
- 如果最大值 100-500：通过但需在最终手测时用这条 barcode 验证页面渲染不卡顿
- 如果最大值 > 500：暂停，告知用户考虑加分页或限流，等用户决策再续

- [ ] **Step 3：创建空的测试文件占位**

```python
# tests/test_history_service.py
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
```

- [ ] **Step 4：commit**

```bash
git add tests/test_history_service.py
git commit -m "test(history): 占位测试文件 + 分支起步"
```

---

## Task 2：history_service.find_record — TDD 双列搜索

**Files:**
- Modify: `tests/test_history_service.py`
- Create: `history_service.py`

- [ ] **Step 1：写第一个失败的测试 — 搜索接受 barcode 命中**

在 `tests/test_history_service.py` 末尾追加 fixture + 测试：

```python
@pytest.fixture
def memdb(tmp_path, monkeypatch):
    """提供一个内存级别的 stockpile.db，独立于真实数据库。"""
    import config
    db_path = tmp_path / "stockpile.db"
    monkeypatch.setattr(config.CONFIG, "stockpile_db", db_path, raising=False)
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
```

- [ ] **Step 2：运行验证失败**

```bash
pytest tests/test_history_service.py::test_find_record_by_barcode -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'history_service'`

- [ ] **Step 3：实现 find_record（最小版本）**

创建 `history_service.py`：

```python
"""货号历史 service。

只读访问 stockpile / stockpile_changes 表。
"""
import sqlite3
from datetime import datetime
from typing import Optional

import stockpile_db


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(stockpile_db.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def find_record(query: str) -> Optional[dict]:
    """精确匹配 product_model 或 product_barcode（两列均 UNIQUE）。

    返回当前主表行的 dict，或 None。
    """
    q = (query or "").strip()
    if not q:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT product_barcode, product_model, stockpile_location, is_active, "
            "       source, created_at, updated_at "
            "FROM stockpile "
            "WHERE product_barcode = ? OR product_model = ? "
            "LIMIT 1",
            (q, q),
        ).fetchone()
    if row is None:
        return None
    return {
        "barcode": row["product_barcode"],
        "model": row["product_model"],
        "location": row["stockpile_location"],
        "is_active": bool(row["is_active"]),
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
```

- [ ] **Step 4：再写两个测试 — 搜 model 命中 / 搜不到返回 None**

在 `test_find_record_by_barcode` 后追加：

```python
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
```

- [ ] **Step 5：跑全部 4 个测试，应全部通过**

```bash
pytest tests/test_history_service.py -v
```
Expected: 4 passed.

- [ ] **Step 6：commit**

```bash
git add history_service.py tests/test_history_service.py
git commit -m "feat(history): find_record 双列精确搜索 + 单测"
```

---

## Task 3：history_service.aggregate_events — TDD 5 秒聚合

**Files:**
- Modify: `tests/test_history_service.py`
- Modify: `history_service.py`

- [ ] **Step 1：写"同秒 4 条折叠为 1 个事件"测试**

在测试文件追加：

```python
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
```

- [ ] **Step 2：运行验证失败**

```bash
pytest tests/test_history_service.py::test_aggregate_same_second_into_one_event -v
```
Expected: FAIL — `aggregate_events` 不存在。

- [ ] **Step 3：实现 aggregate_events**

在 `history_service.py` 追加：

```python
_AGGREGATE_WINDOW_SECONDS = 5


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def aggregate_events(barcode: str) -> list[dict]:
    """按 barcode 拉所有 changes，按 created_at 倒序，
    相邻条目时间差 ≤ 5 秒则合并为同一事件。

    每个事件结构：
        {
            "at": "<created_at 字符串，取组内最新一条>",
            "source": None,  # changes 表不存 source（来自 stockpile.source），后期填充
            "change_type": "<组内最新一条的 change_type>",
            "changes": [{ "field": ..., "old": ..., "new": ... }, ...]
        }
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT field_name, old_value, new_value, change_type, created_at "
            "FROM stockpile_changes "
            "WHERE product_barcode = ? "
            "ORDER BY created_at DESC",
            (barcode,),
        ).fetchall()

    events: list[dict] = []
    current: Optional[dict] = None

    for row in rows:
        change = {
            "field": row["field_name"],
            "old": row["old_value"],
            "new": row["new_value"],
        }
        if current is None:
            current = {
                "at": row["created_at"],
                "change_type": row["change_type"],
                "changes": [change],
            }
            continue
        prev_dt = _parse_dt(current["at"])
        cur_dt = _parse_dt(row["created_at"])
        delta = (prev_dt - cur_dt).total_seconds()
        if 0 <= delta <= _AGGREGATE_WINDOW_SECONDS:
            current["changes"].append(change)
        else:
            events.append(current)
            current = {
                "at": row["created_at"],
                "change_type": row["change_type"],
                "changes": [change],
            }
    if current is not None:
        events.append(current)
    return events
```

- [ ] **Step 4：跑测试**

```bash
pytest tests/test_history_service.py::test_aggregate_same_second_into_one_event -v
```
Expected: PASS.

- [ ] **Step 5：写边界测试 — 4s 合并 / 6s 拆开**

追加：

```python
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
```

- [ ] **Step 6：跑全部测试**

```bash
pytest tests/test_history_service.py -v
```
Expected: 8 passed.

- [ ] **Step 7：commit**

```bash
git add history_service.py tests/test_history_service.py
git commit -m "feat(history): aggregate_events 5s 窗口聚合 + 边界测试"
```

---

## Task 4：history_service.build_response — 顶层组装

**Files:**
- Modify: `tests/test_history_service.py`
- Modify: `history_service.py`

- [ ] **Step 1：写测试**

```python
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
```

- [ ] **Step 2：跑测试看失败**

```bash
pytest tests/test_history_service.py::test_build_response_found tests/test_history_service.py::test_build_response_not_found -v
```
Expected: FAIL — `build_response` 未定义。

- [ ] **Step 3：实现 build_response**

在 `history_service.py` 追加：

```python
def build_response(query: str) -> dict:
    """供 routes_history.py 直接 jsonify 的顶层结构。

    found=False  →  { "found": False }
    found=True   →  { "found": True, "current": {...}, "events": [...] }
    """
    record = find_record(query)
    if record is None:
        return {"found": False}
    events = aggregate_events(record["barcode"])
    # source 来自主表，注入到每个事件方便前端显示
    for e in events:
        e["source"] = record["source"]
    return {"found": True, "current": record, "events": events}
```

- [ ] **Step 4：跑全部测试**

```bash
pytest tests/test_history_service.py -v
```
Expected: 10 passed.

- [ ] **Step 5：commit**

```bash
git add history_service.py tests/test_history_service.py
git commit -m "feat(history): build_response 顶层组装 + 注入 source"
```

---

## Task 5：routes_history.py + 注册 blueprint

**Files:**
- Create: `routes_history.py`
- Modify: `routes.py`

- [ ] **Step 1：先看一下 routes.py 现有结构**

```bash
cat routes.py
```
确认 register_routes 函数里其他 blueprint 是怎么注册的。

- [ ] **Step 2：创建 routes_history.py**

```python
# routes_history.py
from flask import Blueprint, jsonify, request

import history_service

bp = Blueprint("history", __name__, url_prefix="/history")


@bp.get("")
def query():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "msg": "缺少查询参数"}), 400
    try:
        result = history_service.build_response(q)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"查询失败：{exc}"}), 500
    return jsonify({"ok": True, **result})
```

- [ ] **Step 3：在 routes.py 注册**

打开 `routes.py`，在已有 import / register 段对应位置加：

```python
import routes_history
```

并在 `register_routes` 里加：

```python
app.register_blueprint(routes_history.bp)
```

具体放在哪一行参考 routes.py 现有的 register 顺序，紧跟在 `routes_query` 之后即可。

- [ ] **Step 4：用 Flask test client 验证一下端点**

新增测试到 `tests/test_history_service.py` 末尾：

```python
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
```

- [ ] **Step 5：跑测试**

```bash
pytest tests/test_history_service.py -v
```
Expected: 13 passed.

- [ ] **Step 6：commit**

```bash
git add routes_history.py routes.py tests/test_history_service.py
git commit -m "feat(history): GET /history?q= 端点 + 路由注册 + 测试"
```

---

## Task 6：前端 — index.html 加 nav + page section

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1：在 nav 区追加第 5 项**

打开 `templates/index.html`，找到现有 4 个 nav 项（`navMain` / `navDup` / `navPurchase` / `navAttendance`）所在区块（约 24-37 行）。在 `navAttendance` 那一项的**下面、`<span style="flex:1"></span>` 的上面**，追加：

```html
    <div class="app-nav__item" id="navHistory" onclick="switchPage('history')">
      <span class="app-nav__icon">📜</span>货号历史
    </div>
```

- [ ] **Step 2：在 head 段追加 css 引用**

找到现有 `page-attendance.css` 的 link 行，紧跟其后追加：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-history.css') }}">
```

- [ ] **Step 3：在 `<div class="app-pages">` 区域末尾、所有现有 page section 之后追加新 page**

```html
<div class="page" id="pageHistory">
  <div class="panel" id="historySearchPanel">
    <div class="panel-hd">货号查询</div>
    <div class="panel-bd">
      <div class="history-search-row">
        <input type="text" id="historyInput" placeholder="输入条码或型号" autocomplete="off">
        <button class="btn btn-primary" id="historySearch">查询</button>
        <button class="btn btn-ghost" id="historyClear">清空</button>
      </div>
      <div class="history-hint" id="historyHint">输入条码或型号后查询历史</div>
    </div>
  </div>

  <div class="panel" id="historyCurrentPanel" hidden>
    <div class="panel-hd">当前状态</div>
    <div class="panel-bd" id="historyCurrent"></div>
  </div>

  <div class="panel" id="historyTimelinePanel" hidden>
    <div class="panel-hd">历史时间线</div>
    <div class="panel-bd" id="historyTimeline"></div>
  </div>
</div>
```

- [ ] **Step 4：在 body 末尾、现有 `<script>` 引入处之前追加 history.js（暂时空文件占位）**

先创建空文件以避免页面 404：

```bash
touch static/js/history.js static/css/page-history.css
```

确认在 index.html 末尾的脚本引入里，找到 attendance.js 那一行（`<script type="module" src="{{ url_for('static', filename='js/attendance.js') }}"></script>` 之类），紧跟其后加：

```html
<script type="module" src="{{ url_for('static', filename='js/history.js') }}"></script>
```

- [ ] **Step 5：起服务确认无 404 / 无报错**

```bash
python server.py
```
浏览器访问 `http://127.0.0.1:5000`，点击 "📜 货号历史" tab。预期：页面切换，能看到搜索框和"输入条码或型号后查询历史"提示文字（样式可能丑无所谓）。Ctrl+C 关闭服务。

- [ ] **Step 6：commit**

```bash
git add templates/index.html static/js/history.js static/css/page-history.css
git commit -m "feat(history): index.html 加第 5 个 tab 与 page section（占位）"
```

---

## Task 7：static/js/history.js — 搜索 + 渲染

**Files:**
- Modify: `static/js/history.js`

- [ ] **Step 1：写完整的 history.js**

替换 `static/js/history.js` 内容为：

```javascript
// 货号历史 tab：精确搜索 + 渲染当前状态 + 聚合时间线
"use strict";

const $ = (id) => document.getElementById(id);

const SOURCE_CN = {
  scan_import: "扫描导入",
  user_correction: "手动修正",
  system_export: "系统导出",
};

const FIELD_CN = {
  stockpile_location: "库位",
  product_model: "型号",
  product_barcode: "条码",
  is_active: "上下架",
};

const CHANGE_TYPE_CN = {
  update: "更新",
  insert: "新增",
  deactivate: "下架",
  reactivate: "上架",
};

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderEmpty(msg) {
  $("historyHint").textContent = msg;
  $("historyHint").style.display = "";
  $("historyCurrentPanel").hidden = true;
  $("historyTimelinePanel").hidden = true;
}

function renderResult(data) {
  $("historyHint").style.display = "none";
  $("historyCurrentPanel").hidden = false;
  $("historyTimelinePanel").hidden = false;

  const c = data.current;
  $("historyCurrent").innerHTML = `
    <div class="kv-grid">
      <div><span class="k">型号</span><span class="v">${escapeHtml(c.model)}</span></div>
      <div><span class="k">条码</span><span class="v">${escapeHtml(c.barcode)}</span></div>
      <div><span class="k">库位</span><span class="v">${escapeHtml(c.location) || '<span class="empty-val">空</span>'}</span></div>
      <div><span class="k">状态</span><span class="v">${c.is_active ? "在架" : "下架"}</span></div>
      <div><span class="k">来源</span><span class="v">${escapeHtml(SOURCE_CN[c.source] || c.source)}</span></div>
      <div><span class="k">最后更新</span><span class="v">${escapeHtml(c.updated_at)}</span></div>
    </div>
  `;

  const events = data.events || [];
  if (events.length === 0) {
    $("historyTimeline").innerHTML = '<div class="empty">暂无历史变更</div>';
    return;
  }

  const items = events.map((ev) => {
    const changes = ev.changes
      .map((ch) => {
        const fieldCn = FIELD_CN[ch.field] || ch.field;
        const oldVal = ch.old || '<span class="empty-val">空</span>';
        const newVal = ch.new || '<span class="empty-val">空</span>';
        return `<div class="change-row"><span class="change-field">${escapeHtml(fieldCn)}</span><span class="change-arrow">${oldVal === '<span class="empty-val">空</span>' ? oldVal : escapeHtml(ch.old)} → ${newVal === '<span class="empty-val">空</span>' ? newVal : escapeHtml(ch.new)}</span></div>`;
      })
      .join("");
    return `
      <div class="event-item">
        <div class="event-head">
          <span class="event-time">${escapeHtml(ev.at)}</span>
          <span class="event-source">${escapeHtml(SOURCE_CN[ev.source] || ev.source || "")}</span>
          <span class="event-type">[${escapeHtml(CHANGE_TYPE_CN[ev.change_type] || ev.change_type)}]</span>
        </div>
        <div class="event-body">${changes}</div>
      </div>
    `;
  });
  $("historyTimeline").innerHTML = `
    <div class="event-count">共 ${events.length} 次操作</div>
    ${items.join("")}
  `;
}

async function doSearch() {
  const q = $("historyInput").value.trim();
  if (!q) {
    renderEmpty("请输入条码或型号");
    return;
  }
  try {
    const resp = await fetch(`/history?q=${encodeURIComponent(q)}`);
    const data = await resp.json();
    if (!data.ok) {
      renderEmpty(`查询失败：${data.msg || "未知错误"}`);
      return;
    }
    if (!data.found) {
      renderEmpty(`未找到 "${q}"，请检查型号或条码是否正确`);
      return;
    }
    renderResult(data);
  } catch (err) {
    renderEmpty(`网络错误：${err.message}`);
  }
}

function init() {
  const input = $("historyInput");
  if (!input) return; // 当前不在 history tab
  $("historySearch").addEventListener("click", doSearch);
  $("historyClear").addEventListener("click", () => {
    input.value = "";
    renderEmpty("输入条码或型号后查询历史");
    input.focus();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
  });
}

init();
```

- [ ] **Step 2：手测**

```bash
python server.py
```
浏览器访问 `http://127.0.0.1:5000`，切到 "📜 货号历史" tab：
- 用 Task 1 Step 2 记下的 barcode 搜索 → 应显示当前状态 + 时间线
- 用 model 搜同一货号 → 应显示同一结果
- 输入 `does_not_exist` → 显示"未找到"
- 点"清空" → 回到初始状态

样式可能很丑（CSS 还没写），但布局/逻辑要对。Ctrl+C 关闭服务。

- [ ] **Step 3：commit**

```bash
git add static/js/history.js
git commit -m "feat(history): history.js 搜索调用 + 时间线渲染"
```

---

## Task 8：page-history.css — filing-cabinet 主题样式

**Files:**
- Modify: `static/css/page-history.css`

- [ ] **Step 1：先看 tokens.css 与现有 page-xxx.css 的命名习惯**

```bash
head -40 static/css/tokens.css
head -30 static/css/page-attendance.css
```
熟悉现有的 `--color-*` / `--space-*` / `--radius-*` 变量。

- [ ] **Step 2：写 page-history.css**

```css
/* static/css/page-history.css — 货号历史页样式（沿用 tokens） */

#pageHistory {
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 16px);
  padding: var(--space-5, 20px) var(--space-7, 28px);
  height: 100%;
  overflow-y: auto;
}

.history-search-row {
  display: flex;
  gap: var(--space-2, 8px);
  align-items: center;
}

.history-search-row input {
  flex: 1;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--color-border, #d6d3c7);
  border-radius: var(--radius-md, 6px);
  font-size: 14px;
  background: var(--color-bg, #fdf6e3);
  color: var(--color-text, #073642);
  font-family: inherit;
}

.history-search-row input:focus {
  outline: none;
  border-color: var(--color-accent, #268bd2);
}

.history-hint {
  margin-top: var(--space-3, 12px);
  color: var(--color-text-muted, #93a1a1);
  font-size: 13px;
}

#pageHistory .kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-2, 8px) var(--space-5, 20px);
}

#pageHistory .kv-grid .k {
  color: var(--color-text-muted, #93a1a1);
  margin-right: var(--space-2, 8px);
  display: inline-block;
  min-width: 60px;
}

#pageHistory .kv-grid .v {
  color: var(--color-text, #073642);
  font-weight: 500;
}

#pageHistory .empty-val {
  color: var(--color-text-muted, #93a1a1);
  font-style: italic;
}

#pageHistory .event-count {
  color: var(--color-text-muted, #93a1a1);
  font-size: 13px;
  margin-bottom: var(--space-3, 12px);
}

#pageHistory .event-item {
  border-left: 2px solid var(--color-accent, #268bd2);
  padding: var(--space-3, 12px) var(--space-4, 16px);
  margin-bottom: var(--space-3, 12px);
  background: var(--color-bg-elevated, #eee8d5);
  border-radius: 0 var(--radius-md, 6px) var(--radius-md, 6px) 0;
}

#pageHistory .event-head {
  display: flex;
  gap: var(--space-3, 12px);
  align-items: center;
  margin-bottom: var(--space-2, 8px);
  font-size: 13px;
}

#pageHistory .event-time {
  font-weight: 600;
  color: var(--color-text, #073642);
}

#pageHistory .event-source {
  color: var(--color-accent, #268bd2);
}

#pageHistory .event-type {
  color: var(--color-text-muted, #93a1a1);
  font-size: 12px;
}

#pageHistory .change-row {
  display: flex;
  gap: var(--space-3, 12px);
  padding: 2px 0;
  font-size: 13px;
  color: var(--color-text, #073642);
}

#pageHistory .change-field {
  color: var(--color-text-muted, #93a1a1);
  min-width: 50px;
}

#pageHistory .change-arrow {
  font-family: ui-monospace, "Cascadia Code", "Consolas", monospace;
  font-size: 12px;
}
```

注：上面用了 `var(--color-bg, fallback)` 双保险。如果 tokens.css 没有这些变量名（命名不同），fallback 会兜住，外观仍可用。

- [ ] **Step 3：手测对比**

```bash
python server.py
```
切到货号历史 tab 重新搜索。预期：
- 输入框 / 按钮风格与其它页一致
- 时间线左侧蓝条 + 浅底卡片
- "空"用斜体灰色显示
- 整体能与"考勤" / "采购" tab 视觉协调

如颜色不调和，逐项对照 `tokens.css` 实际变量名调整。

- [ ] **Step 4：commit**

```bash
git add static/css/page-history.css
git commit -m "style(history): page-history.css 沿用 filing-cabinet 主题"
```

---

## Task 9：删除 admin 页面 + /stats 路由

**Files:**
- Delete: `templates/admin.html`
- Delete: `static/css/admin.css`
- Delete: `static/js/admin.js`
- Delete: `static/js/admin-messaging.js`
- Delete: `static/js/admin-transfer.js`
- Modify: `routes_pages_tasks.py`
- Modify: `routes_query.py`
- Modify: `query_service.py`

- [ ] **Step 1：先确认这些文件没有被新代码反向引用**

```bash
grep -rn "admin\.html\|admin\.css\|admin\.js\|admin-messaging\|admin-transfer" --include="*.py" --include="*.html" --include="*.js" --include="*.css" | grep -v "^docs/" | grep -v "^垃圾桶/"
```
预期只看到这些被删文件之间的相互引用（admin.js 引 admin-messaging / admin-transfer，admin.html 引 admin.js）。如果出现其它源文件（比如 index.html、index.js）引用，停下分析。

- [ ] **Step 2：再确认 read_monthly_stats / _YYYYMMDD_LEN 仅在 query_service / routes_query 中使用**

```bash
grep -rn "read_monthly_stats\|_YYYYMMDD_LEN" --include="*.py" | grep -v "^docs/" | grep -v "^垃圾桶/"
```
预期：`query_service.py` 定义 + `routes_query.py` 引用，仅此而已。

- [ ] **Step 3：删除 5 个文件**

```bash
rm templates/admin.html
rm static/css/admin.css
rm static/js/admin.js
rm static/js/admin-messaging.js
rm static/js/admin-transfer.js
```

- [ ] **Step 4：删除 routes_pages_tasks.py 中 /admin 路由**

打开 `routes_pages_tasks.py`，定位约 19-21 行：

```python
@bp.get("/admin")
def admin():
    return render_template("admin.html")
```

整段（含上面的空行）删掉。

- [ ] **Step 5：删除 routes_query.py 中 /stats 路由**

打开 `routes_query.py`，定位约 30-33 行：

```python
@bp.get("/stats")
def stats():
    return jsonify(query_service.read_monthly_stats())
```

整段删掉。

- [ ] **Step 6：删除 query_service.py 中 read_monthly_stats + 其专属常量/import**

打开 `query_service.py`：
- 删 `def read_monthly_stats() -> list[dict]:` 整个函数
- 删 `_YYYYMMDD_LEN = 8` 常量
- 检查 `re` / `datetime` / `defaultdict` 这些 import：如果除了 read_monthly_stats 之外没人用，一并删除（用 grep 确认）

```bash
grep -n "re\.\|datetime\|defaultdict" query_service.py
```
看剩余引用判断哪些 import 还要保留。

- [ ] **Step 7：跑全部测试 + 启服务确认**

```bash
pytest tests/ -v
```
Expected: 所有测试通过（包括之前 13 个 history 测试 + 现有所有测试）。

```bash
python server.py
```
浏览器：
- `http://127.0.0.1:5000/admin` → 应是 404
- `http://127.0.0.1:5000/stats` → 应是 404
- `http://127.0.0.1:5000/` → 5 个 tab 全部正常

Ctrl+C 关闭。

- [ ] **Step 8：commit**

```bash
git add -A
git commit -m "refactor: 删除已成死代码的 /admin 页面与 /stats 路由

A 端从未实际使用 /admin（用户在两台机器上各开 A 端，互传通过 FAB 抽屉
完成）。/stats 月度扫描柱状图功能用户已确认无意义。

删除文件：admin.html / admin.css / admin.js / admin-messaging.js /
admin-transfer.js。删除路由：/admin / /stats。删除函数：
query_service.read_monthly_stats() 与其专属常量。

保留：routes_collab / routes_transfer（A 端互传）、routes_monthly_summary
（采购页月度采购总结）、dual_mode 配置（transfer 目录依赖）。"
```

---

## Task 10：更新 README + 使用文档

**Files:**
- Modify: `README.md`
- Modify: `使用文档.md`

- [ ] **Step 1：定位并删除 README.md 中 /admin 提及**

```bash
grep -n "/admin\|admin" README.md
```
找到第 99 行附近 `http://127.0.0.1:5000/admin：控制台页面` 这一行，删除。

- [ ] **Step 2：定位并删除 使用文档.md 中 /admin 段落**

```bash
grep -n "/admin\|控制台\|B 端" 使用文档.md
```
预期看到第 8 行（B 端说明）、第 27 行（控制台端访问 URL）、第 156 行（`/admin` 段落起头）。

按段落整体删除：
- 第 27 行 `控制台端访问：...` 一行删
- 第 8 行整段提及"控制台端（B 端）"的列表项删除（保留其余双端说明，因为 A↔A 互传仍在用）
- 第 156 行起，"控制台端功能"小节整段删除（一直删到下一个 `##` 或 `---` 之前）

互传段落（约第 140-148 行）保留，但把"A 端 ↔ 控制台端"改写为"A 端 ↔ A 端（双机协作）"。

- [ ] **Step 3：在 README 与 使用文档 中适当位置增加货号历史页的说明**

README.md（在功能列表附近）追加一行：

```
- 货号历史页（A 端"📜 货号历史" tab）：输入条码或型号查询当前状态与历史变更时间线
```

使用文档.md（在 A 端 tab 介绍部分）追加一段：

```
### 📜 货号历史

输入条码或型号（精确匹配），查询当前主表中的库位、状态、来源等信息，以及
所有历史变更（按时间倒序，5 秒内的多次变更聚合为一次操作）。

只读，不可编辑。需要纠错请走现有的 import / 手动修正流程。
```

- [ ] **Step 4：commit**

```bash
git add README.md 使用文档.md
git commit -m "docs: 删除 /admin 控制台说明 + 增补货号历史页用法"
```

---

## Task 11：standards / encoding 校验 + 最终回归手测

**Files:** （无新增改动）

- [ ] **Step 1：跑 standards 检查**

```bash
pwsh scripts/check-standards.ps1
```
Expected: 退出码 0。如果报新文件长度/命名问题，按提示修复后再跑。

- [ ] **Step 2：跑 encoding 检查**

```bash
pwsh scripts/check-encoding.ps1
```
Expected: 退出码 0。如出现 mojibake，定位到具体文件用 UTF-8 (no BOM) 重写。

- [ ] **Step 3：最终回归手测清单**

```bash
python server.py
```

逐项验证：

- [ ] 5 个 tab 切换正常（标签 / 查重 / 采购 / 考勤 / 货号历史）
- [ ] 标签 tab：上传文件 + 开始处理 流程不退化
- [ ] 查重 tab：能正常打开
- [ ] 采购 tab：月度采购总结（保存 / 历史月份列表 / PDF 导出）正常
- [ ] 考勤 tab：能加载、滚动正常
- [ ] 货号历史 tab：
  - 用 Task 1 Step 2 记下的 barcode 搜索 → 显示当前 + 时间线
  - 同货号用 model 搜 → 同一结果
  - 搜不存在 → "未找到"
  - 清空 → 回到提示
  - 切走再切回 → 不报错
- [ ] FAB（右下角汉堡）抽屉：文件互传 + 文本互传仍正常
- [ ] 终端日志抽屉：仍正常
- [ ] `http://127.0.0.1:5000/admin` → 404
- [ ] `http://127.0.0.1:5000/stats` → 404
- [ ] 浏览器 DevTools Console 无报错
- [ ] DevTools Network：货号历史 → `/history?q=...` 返回 200

如有任何问题：修复 → 跑测试 → 重新手测。

- [ ] **Step 4：最终 commit（如手测期间有修复）**

```bash
git status
git add -A
git commit -m "fix(history): 手测发现的 xxx"
```
（无修复则跳过）

- [ ] **Step 5：合并到 main 前的 sanity check**

```bash
git log --oneline main..feature/model-history
```
预期看到 ~10 个清晰的 commit。读一遍 commit messages，确认每条都言之有物。

---

## Task 12：finishing — 合并选项

实现完成。按用户偏好选合并方式：

- [ ] **Option A：直接合 main**（适合个人项目）

```bash
git checkout main
git merge --no-ff feature/model-history -m "Merge branch 'feature/model-history'"
git branch -d feature/model-history
git status
```

- [ ] **Option B：开 PR 走 GitHub review**

```bash
git push -u origin feature/model-history
gh pr create --title "feat: 货号历史页 + 删除 /admin 控制台" --body "$(cat <<'EOF'
## Summary
- A 端新增第 5 个 tab "📜 货号历史"，输入条码或型号查询当前状态与变更时间线
- 5 秒窗口聚合（基于实际数据时间分布）
- 删除已成死代码的 /admin 页面与 /stats 路由

## Spec / Plan
- spec: docs/superpowers/specs/2026-04-28-model-history-design.md
- plan: docs/superpowers/plans/2026-04-28-model-history.md

## Test plan
- [ ] pytest tests/test_history_service.py -v 全过
- [ ] 5 个 tab 全部回归正常
- [ ] FAB 互传 + 采购页月度采购总结仍工作
- [ ] /admin / /stats 返回 404

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
