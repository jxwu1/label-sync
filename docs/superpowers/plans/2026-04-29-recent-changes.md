# 货号历史 - 最近改动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在货号历史页加二级 tab "📊 最近改动"，按 import 批次审计变更，默认折叠净效应、可切 raw 视图、点行下钻到货号查询。

**Architecture:** `stockpile_snapshots WHERE trigger='import'` 作批次锚，`stockpile_changes` 用窗口 `(prev_taken_at, current_taken_at]` 关联到批次。后端 `recent_changes_service.py` + `routes_recent_changes.py`，前端 `static/js/index-recent-changes.js` vanilla module，跟 `history.js` 同级。

**Tech Stack:** Python 3.14 / Flask / SQLAlchemy 2.x / pytest / vanilla JS module / 无前端构建。

**分支：** `feature/recent-changes`（已基于 main 并含 spec commit）

---

## File Structure

| 文件 | 状态 | 责任 |
|---|---|---|
| `recent_changes_service.py` | Create | 4 公共函数 + `_batch_window` 私有；只读，不写 DB |
| `routes_recent_changes.py` | Create | 3 GET endpoint，Blueprint 注册到 `/recent_changes` |
| `routes.py` | Modify | 注册新 blueprint |
| `tests/test_recent_changes_service.py` | Create | service 单测，覆盖 collapse/raw/filter/window |
| `static/js/index-recent-changes.js` | Create | 前端 module，状态闭包 + 渲染 + 事件 |
| `templates/index.html` | Modify | pageHistory 内加二级 tab 结构 + 最近改动 panel |
| `static/css/page-history.css` | Modify | 二级 tab、批次下拉、summary 卡片、chip 样式 |
| `static/js/history.js` | Modify | 暴露 `searchHistory(q)` 给最近改动模块下钻调用 |
| `static/js/index.js` | Modify | 引入新 module（如需） |
| `docs/superpowers/plans/2026-04-28-roadmap.md` | Modify | 收尾时记录本次工作 |

---

## Task 1: 后端 service skeleton

**Files:**
- Create: `recent_changes_service.py`
- Create: `tests/test_recent_changes_service.py`

- [ ] **Step 1.1: 写最小 service 文件**

```python
# recent_changes_service.py
"""货号历史 - 最近改动 service。

按 stockpile_snapshots(trigger='import') 切批次，关联到落在
窗口 (prev_taken_at, current_taken_at] 内的 stockpile_changes。
"""
from typing import Literal, Optional

from sqlalchemy import and_, func, select

import stockpile_db
from models import Stockpile, StockpileChange, StockpileSnapshot

_RECENT_IMPORTS_LIMIT = 10
_EPOCH = "1970-01-01 00:00:00"


def _batch_window(session, batch_id: int) -> tuple[str, str]:
    """返回 (window_start, window_end) 字符串。

    window_end = snapshot[batch_id].taken_at
    window_start = 上一个 trigger='import' snapshot 的 taken_at；不存在时取 _EPOCH
    """
    current = session.execute(
        select(StockpileSnapshot.taken_at)
        .where(StockpileSnapshot.id == batch_id)
    ).scalar_one()

    prev = session.execute(
        select(StockpileSnapshot.taken_at)
        .where(and_(
            StockpileSnapshot.trigger == "import",
            StockpileSnapshot.id < batch_id,
        ))
        .order_by(StockpileSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    return (prev or _EPOCH, current)
```

- [ ] **Step 1.2: 写测试 fixture（复用 data_quality 测试模式）**

```python
# tests/test_recent_changes_service.py
"""recent_changes_service 单测。"""
import shutil
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd
from sqlalchemy import insert

import recent_changes_service
import stockpile_db
from models import StockpileChange, StockpileSnapshot

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_recent_changes"


class RecentChangesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_snapshot(self, taken_at: str, trigger: str = "import", **kwargs) -> int:
        """直接 INSERT snapshot 返回 id。便于测试控制 taken_at。"""
        with stockpile_db._session() as session:
            result = session.execute(
                insert(StockpileSnapshot).values(
                    taken_at=taken_at,
                    trigger=trigger,
                    total_local=kwargs.get("total_local", 0),
                )
            )
            session.commit()
            return result.inserted_primary_key[0]

    def _insert_change(self, barcode: str, field: str, old: str, new: str,
                       change_type: str = "update", created_at: str | None = None) -> None:
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.3: 跑测试确认 setUp 工作**

Run: `python -m pytest tests/test_recent_changes_service.py -v`
Expected: 0 tests (no test methods yet), exit 0

- [ ] **Step 1.4: 提交**

```bash
git add recent_changes_service.py tests/test_recent_changes_service.py
git commit -m "feat(recent-changes): service 骨架 + 测试 fixture"
```

---

## Task 2: `_batch_window` 实现 + 测试

**Files:**
- Modify: `tests/test_recent_changes_service.py`
- Already implemented in Task 1: `recent_changes_service._batch_window`

- [ ] **Step 2.1: 写失败测试（3 case）**

加到 `RecentChangesTests` 类内：

```python
def test_batch_window_first_snapshot_uses_epoch_start(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 10:00:00")
    with stockpile_db._session() as session:
        start, end = recent_changes_service._batch_window(session, snap_id)
    self.assertEqual(start, "1970-01-01 00:00:00")
    self.assertEqual(end, "2026-04-29 10:00:00")

def test_batch_window_uses_previous_import_taken_at(self) -> None:
    self._insert_snapshot("2026-04-29 10:00:00")
    snap2 = self._insert_snapshot("2026-04-29 14:30:00")
    with stockpile_db._session() as session:
        start, end = recent_changes_service._batch_window(session, snap2)
    self.assertEqual(start, "2026-04-29 10:00:00")
    self.assertEqual(end, "2026-04-29 14:30:00")

def test_batch_window_skips_non_import_snapshots(self) -> None:
    """compare snapshot 不算批次锚，不能当 prev。"""
    self._insert_snapshot("2026-04-29 10:00:00", trigger="import")
    self._insert_snapshot("2026-04-29 12:00:00", trigger="compare")
    snap3 = self._insert_snapshot("2026-04-29 14:30:00", trigger="import")
    with stockpile_db._session() as session:
        start, end = recent_changes_service._batch_window(session, snap3)
    self.assertEqual(start, "2026-04-29 10:00:00")  # skip compare
```

- [ ] **Step 2.2: 跑测试，应全过（实现已在 Task 1）**

Run: `python -m pytest tests/test_recent_changes_service.py -v`
Expected: 3 passed

- [ ] **Step 2.3: 提交**

```bash
git add tests/test_recent_changes_service.py
git commit -m "test(recent-changes): _batch_window 3 个 case"
```

---

## Task 3: `list_recent_imports`

**Files:**
- Modify: `recent_changes_service.py` (append)
- Modify: `tests/test_recent_changes_service.py`

- [ ] **Step 3.1: 写失败测试**

```python
def test_list_recent_imports_returns_only_import_trigger_desc(self) -> None:
    self._insert_snapshot("2026-04-29 10:00:00", trigger="import", total_local=100)
    self._insert_snapshot("2026-04-29 11:00:00", trigger="compare")
    self._insert_snapshot("2026-04-29 14:00:00", trigger="import", total_local=120)
    result = recent_changes_service.list_recent_imports()
    self.assertEqual(len(result), 2)
    self.assertEqual(result[0]["taken_at"], "2026-04-29 14:00:00")  # 最新在前
    self.assertEqual(result[0]["total_local"], 120)
    self.assertEqual(result[1]["total_local"], 100)

def test_list_recent_imports_counts_changes_in_window(self) -> None:
    snap1 = self._insert_snapshot("2026-04-29 10:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:30:00")
    self._insert_change("B2", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:45:00")
    snap2 = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B3", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

    result = recent_changes_service.list_recent_imports()
    by_id = {r["batch_id"]: r for r in result}
    self.assertEqual(by_id[snap1]["change_count"], 2)
    self.assertEqual(by_id[snap1]["affected_barcodes"], 2)
    self.assertEqual(by_id[snap2]["change_count"], 1)
    self.assertEqual(by_id[snap2]["affected_barcodes"], 1)
```

- [ ] **Step 3.2: 跑测试确认 RED**

Run: `python -m pytest tests/test_recent_changes_service.py::RecentChangesTests::test_list_recent_imports_returns_only_import_trigger_desc -v`
Expected: FAIL with `AttributeError: module 'recent_changes_service' has no attribute 'list_recent_imports'`

- [ ] **Step 3.3: 实现**

加到 `recent_changes_service.py`：

```python
def list_recent_imports(limit: int = _RECENT_IMPORTS_LIMIT) -> list[dict]:
    """返回最近 N 次 import snapshot 概览。

    每条 dict 字段：batch_id / taken_at / total_local / change_count / affected_barcodes
    """
    with stockpile_db._session() as session:
        snapshots = session.execute(
            select(StockpileSnapshot)
            .where(StockpileSnapshot.trigger == "import")
            .order_by(StockpileSnapshot.id.desc())
            .limit(limit)
        ).scalars().all()

        result = []
        for snap in snapshots:
            start, end = _batch_window(session, snap.id)
            stats = session.execute(
                select(
                    func.count().label("n"),
                    func.count(func.distinct(StockpileChange.product_barcode)).label("bc"),
                ).where(and_(
                    StockpileChange.created_at > start,
                    StockpileChange.created_at <= end,
                ))
            ).one()
            result.append({
                "batch_id": snap.id,
                "taken_at": snap.taken_at,
                "total_local": snap.total_local,
                "change_count": stats.n,
                "affected_barcodes": stats.bc,
            })
        return result
```

- [ ] **Step 3.4: 跑测试，应 GREEN**

Run: `python -m pytest tests/test_recent_changes_service.py -v`
Expected: 5 passed

- [ ] **Step 3.5: 提交**

```bash
git add recent_changes_service.py tests/test_recent_changes_service.py
git commit -m "feat(recent-changes): list_recent_imports 列出最近 N 次 import 批次"
```

---

## Task 4: `get_batch_summary`

**Files:**
- Modify: `recent_changes_service.py`
- Modify: `tests/test_recent_changes_service.py`

- [ ] **Step 4.1: 写失败测试**

```python
def test_get_batch_summary_counts_by_field_and_change_type(self) -> None:
    """5 个数字 + roundtrip count。所有按 (barcode, field) 维度。"""
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    base = "2026-04-29 13:"
    # B1 location 单变 → location_changes +1
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at=base+"01:00")
    # B2 location 来回（A→B→A）→ roundtrip
    self._insert_change("B2", "stockpile_location", "A1", "A2", created_at=base+"02:00")
    self._insert_change("B2", "stockpile_location", "A2", "A1", created_at=base+"02:30")
    # B3 model 变 → model_changes +1
    self._insert_change("B3", "product_model", "M1", "M2", created_at=base+"03:00")
    # B4 insert → inserts +1
    self._insert_change("B4", "product_barcode", None, "B4", "insert", created_at=base+"04:00")
    # B5 deactivate
    self._insert_change("B5", "is_active", "1", "0", "deactivate", created_at=base+"05:00")
    # B6 reactivate
    self._insert_change("B6", "is_active", "0", "1", "reactivate", created_at=base+"06:00")

    s = recent_changes_service.get_batch_summary(snap_id)
    self.assertEqual(s["location_changes"], 1)
    self.assertEqual(s["model_changes"], 1)
    self.assertEqual(s["inserts"], 1)
    self.assertEqual(s["deactivates"], 1)
    self.assertEqual(s["reactivates"], 1)
    self.assertEqual(s["roundtrip_count"], 1)  # B2 location

def test_get_batch_summary_excludes_changes_outside_window(self) -> None:
    self._insert_snapshot("2026-04-29 10:00:00")  # prev import
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    # 这条在 prev 之前，不该算
    self._insert_change("B0", "stockpile_location", "A1", "A2", created_at="2026-04-29 09:00:00")
    # 这条在窗口内
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")

    s = recent_changes_service.get_batch_summary(snap_id)
    self.assertEqual(s["location_changes"], 1)
```

- [ ] **Step 4.2: 跑测试确认 RED**

Run: `python -m pytest tests/test_recent_changes_service.py::RecentChangesTests::test_get_batch_summary_counts_by_field_and_change_type -v`
Expected: FAIL with `AttributeError: ... 'get_batch_summary'`

- [ ] **Step 4.3: 实现**

加到 `recent_changes_service.py`：

```python
def get_batch_summary(batch_id: int) -> dict:
    """返回该批次 5 个统计 + roundtrip count。

    全部按 (barcode, field_name) 维度去重；同 barcode+field 多次变更
    若终态==起始态则计入 roundtrip_count，不进 5 个数字。
    """
    with stockpile_db._session() as session:
        start, end = _batch_window(session, batch_id)
        rows = session.execute(
            select(
                StockpileChange.product_barcode,
                StockpileChange.field_name,
                StockpileChange.old_value,
                StockpileChange.new_value,
                StockpileChange.change_type,
                StockpileChange.created_at,
            ).where(and_(
                StockpileChange.created_at > start,
                StockpileChange.created_at <= end,
            ))
            .order_by(StockpileChange.created_at)
        ).all()

    return _summarize(rows)


def _summarize(rows: list) -> dict:
    """把原始 changes 行折叠为 5 个统计 + roundtrip。"""
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r.product_barcode, r.field_name), []).append(r)

    counts = {
        "location_changes": 0,
        "model_changes": 0,
        "inserts": 0,
        "deactivates": 0,
        "reactivates": 0,
        "roundtrip_count": 0,
    }
    for (barcode, field), group in grouped.items():
        first_old = group[0].old_value
        last_new = group[-1].new_value
        last_type = group[-1].change_type
        # roundtrip：终态==起始态（仅 update 类型有意义）
        if first_old == last_new and last_type == "update":
            counts["roundtrip_count"] += 1
            continue
        if last_type == "insert":
            counts["inserts"] += 1
        elif last_type == "deactivate":
            counts["deactivates"] += 1
        elif last_type == "reactivate":
            counts["reactivates"] += 1
        elif field == "stockpile_location":
            counts["location_changes"] += 1
        elif field == "product_model":
            counts["model_changes"] += 1
    return counts
```

- [ ] **Step 4.4: 跑测试，应 GREEN**

Run: `python -m pytest tests/test_recent_changes_service.py -v`
Expected: 7 passed

- [ ] **Step 4.5: 提交**

```bash
git add recent_changes_service.py tests/test_recent_changes_service.py
git commit -m "feat(recent-changes): get_batch_summary 5 数字 + roundtrip"
```

---

## Task 5: `get_batch_changes(collapsed)`

**Files:**
- Modify: `recent_changes_service.py`
- Modify: `tests/test_recent_changes_service.py`

- [ ] **Step 5.1: 写失败测试（4 个 collapse 场景）**

```python
def test_get_batch_changes_collapsed_single_change(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["barcode"], "B1")
    self.assertEqual(rows[0]["field"], "stockpile_location")
    self.assertEqual(rows[0]["from_value"], "A1")
    self.assertEqual(rows[0]["to_value"], "A2")

def test_get_batch_changes_collapsed_roundtrip_excluded(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    self._insert_change("B1", "stockpile_location", "A2", "A1", created_at="2026-04-29 13:30:00")
    rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
    self.assertEqual(rows, [])

def test_get_batch_changes_collapsed_multi_step_keeps_endpoints(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    self._insert_change("B1", "stockpile_location", "A2", "A3", created_at="2026-04-29 13:30:00")
    rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["from_value"], "A1")
    self.assertEqual(rows[0]["to_value"], "A3")

def test_get_batch_changes_collapsed_multi_field_split_rows(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    self._insert_change("B1", "product_model", "M1", "M2", created_at="2026-04-29 13:01:00")
    rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
    self.assertEqual(len(rows), 2)
    fields = sorted(r["field"] for r in rows)
    self.assertEqual(fields, ["product_model", "stockpile_location"])

def test_get_batch_changes_collapsed_sorted_by_latest_event_desc(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    self._insert_change("B2", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:30:00")
    rows = recent_changes_service.get_batch_changes(snap_id, mode="collapsed")
    self.assertEqual([r["barcode"] for r in rows], ["B2", "B1"])  # B2 更晚
```

- [ ] **Step 5.2: 跑测试确认 RED**

Run: `python -m pytest tests/test_recent_changes_service.py::RecentChangesTests::test_get_batch_changes_collapsed_single_change -v`
Expected: FAIL `AttributeError: ... 'get_batch_changes'`

- [ ] **Step 5.3: 实现 collapsed mode**

加到 `recent_changes_service.py`：

```python
def get_batch_changes(
    batch_id: int,
    mode: Literal["collapsed", "raw"] = "collapsed",
    filter_field: Optional[str] = None,
    filter_change_type: Optional[str] = None,
) -> list[dict]:
    """返回批次明细。

    collapsed：按 (barcode, field) 折叠，roundtrip 剔除，多字段同 barcode 拆多行
    raw：原 stockpile_changes 行
    filter_field / filter_change_type：可选过滤
    """
    with stockpile_db._session() as session:
        start, end = _batch_window(session, batch_id)
        conds = [
            StockpileChange.created_at > start,
            StockpileChange.created_at <= end,
        ]
        if filter_field:
            conds.append(StockpileChange.field_name == filter_field)
        if filter_change_type:
            conds.append(StockpileChange.change_type == filter_change_type)

        rows = session.execute(
            select(
                StockpileChange.product_barcode,
                StockpileChange.field_name,
                StockpileChange.old_value,
                StockpileChange.new_value,
                StockpileChange.change_type,
                StockpileChange.created_at,
            ).where(and_(*conds))
            .order_by(StockpileChange.created_at)
        ).all()

        # 关联 model（一次查询，避免 N+1）
        barcodes = {r.product_barcode for r in rows}
        models = {}
        if barcodes:
            for bc, m in session.execute(
                select(Stockpile.product_barcode, Stockpile.product_model)
                .where(Stockpile.product_barcode.in_(barcodes))
            ).all():
                models[bc] = m

    if mode == "raw":
        return [
            {
                "barcode": r.product_barcode,
                "model": models.get(r.product_barcode, ""),
                "field": r.field_name,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "change_type": r.change_type,
                "created_at": r.created_at,
            }
            for r in reversed(rows)  # 倒序展示
        ]

    # collapsed
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r.product_barcode, r.field_name), []).append(r)

    result = []
    for (barcode, field), group in grouped.items():
        first_old = group[0].old_value
        last_new = group[-1].new_value
        last_type = group[-1].change_type
        # roundtrip 剔除（仅对 update 类型有意义）
        if first_old == last_new and last_type == "update":
            continue
        result.append({
            "barcode": barcode,
            "model": models.get(barcode, ""),
            "field": field,
            "from_value": first_old,
            "to_value": last_new,
            "change_type": last_type,
            "latest_at": group[-1].created_at,
        })
    result.sort(key=lambda r: r["latest_at"], reverse=True)
    return result
```

- [ ] **Step 5.4: 跑测试，应 GREEN**

Run: `python -m pytest tests/test_recent_changes_service.py -v`
Expected: 12 passed

- [ ] **Step 5.5: 提交**

```bash
git add recent_changes_service.py tests/test_recent_changes_service.py
git commit -m "feat(recent-changes): get_batch_changes collapsed 模式 + 折叠算法"
```

---

## Task 6: `get_batch_changes(raw)` + filters

**Files:**
- Modify: `tests/test_recent_changes_service.py` (raw 路径已在 Task 5 实现，补测试)

- [ ] **Step 6.1: 写测试**

```python
def test_get_batch_changes_raw_returns_all_rows_with_intermediate_steps(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    self._insert_change("B1", "stockpile_location", "A2", "A1", created_at="2026-04-29 13:30:00")
    rows = recent_changes_service.get_batch_changes(snap_id, mode="raw")
    self.assertEqual(len(rows), 2)  # raw 不剔除 roundtrip
    # 倒序：最新在前
    self.assertEqual(rows[0]["new_value"], "A1")
    self.assertEqual(rows[1]["new_value"], "A2")

def test_get_batch_changes_filter_by_field(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    self._insert_change("B2", "product_model", "M1", "M2", created_at="2026-04-29 13:01:00")
    rows = recent_changes_service.get_batch_changes(
        snap_id, mode="collapsed", filter_field="stockpile_location"
    )
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["barcode"], "B1")

def test_get_batch_changes_filter_by_change_type(self) -> None:
    snap_id = self._insert_snapshot("2026-04-29 14:00:00")
    self._insert_change("B1", "stockpile_location", "A1", "A2", created_at="2026-04-29 13:00:00")
    self._insert_change("B2", "product_barcode", None, "B2", "insert", created_at="2026-04-29 13:01:00")
    rows = recent_changes_service.get_batch_changes(
        snap_id, mode="raw", filter_change_type="insert"
    )
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["barcode"], "B2")
```

- [ ] **Step 6.2: 跑测试，应 GREEN（实现已在 Task 5）**

Run: `python -m pytest tests/test_recent_changes_service.py -v`
Expected: 15 passed

- [ ] **Step 6.3: 提交**

```bash
git add tests/test_recent_changes_service.py
git commit -m "test(recent-changes): raw 模式 + filter 测试"
```

---

## Task 7: Routes + 注册 blueprint

**Files:**
- Create: `routes_recent_changes.py`
- Modify: `routes.py`
- Create: `tests/test_recent_changes_routes.py`

- [ ] **Step 7.1: 写 routes 文件**

```python
# routes_recent_changes.py
from flask import Blueprint, jsonify, request

import recent_changes_service

bp = Blueprint("recent_changes", __name__, url_prefix="/recent_changes")


@bp.get("/imports")
def list_imports():
    try:
        result = recent_changes_service.list_recent_imports()
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "imports": result})


@bp.get("/<int:batch_id>/summary")
def batch_summary(batch_id: int):
    try:
        result = recent_changes_service.get_batch_summary(batch_id)
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "summary": result})


@bp.get("/<int:batch_id>/changes")
def batch_changes(batch_id: int):
    mode = request.args.get("mode", "collapsed")
    if mode not in ("collapsed", "raw"):
        return jsonify({"ok": False, "msg": f"非法 mode: {mode}"}), 400
    field = request.args.get("field") or None
    change_type = request.args.get("change_type") or None
    try:
        rows = recent_changes_service.get_batch_changes(
            batch_id, mode=mode,
            filter_field=field, filter_change_type=change_type,
        )
    except Exception as exc:
        return jsonify({"ok": False, "msg": f"加载失败：{exc}"}), 500
    return jsonify({"ok": True, "changes": rows})
```

- [ ] **Step 7.2: 注册到 routes.py**

```python
# routes.py 顶部 import 加：
from routes_recent_changes import bp as recent_changes_bp

# register_routes 函数体内（history_bp 注册之后）加：
    app.register_blueprint(recent_changes_bp)
```

- [ ] **Step 7.3: 写 routes 单测**

```python
# tests/test_recent_changes_routes.py
"""recent_changes routes 单测：HTTP 层薄包装，重点覆盖参数解析与错误。"""
import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask
from sqlalchemy import insert

import stockpile_db
from models import StockpileChange, StockpileSnapshot
from routes_recent_changes import bp

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_recent_changes_routes"


class RecentChangesRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()

        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _seed(self) -> int:
        with stockpile_db._session() as session:
            r = session.execute(insert(StockpileSnapshot).values(
                taken_at="2026-04-29 14:00:00", trigger="import", total_local=10,
            ))
            sid = r.inserted_primary_key[0]
            session.execute(insert(StockpileChange).values(
                product_barcode="B1", field_name="stockpile_location",
                old_value="A1", new_value="A2", change_type="update",
                created_at="2026-04-29 13:00:00",
            ))
            session.commit()
        return sid

    def test_imports_endpoint(self) -> None:
        self._seed()
        resp = self.client.get("/recent_changes/imports")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["imports"]), 1)

    def test_summary_endpoint(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/summary")
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["location_changes"], 1)

    def test_changes_endpoint_collapsed_default(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/changes")
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["changes"]), 1)
        self.assertEqual(data["changes"][0]["from_value"], "A1")

    def test_changes_endpoint_raw_mode(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/changes?mode=raw")
        data = resp.get_json()
        self.assertEqual(len(data["changes"]), 1)
        self.assertEqual(data["changes"][0]["new_value"], "A2")

    def test_changes_endpoint_invalid_mode_returns_400(self) -> None:
        sid = self._seed()
        resp = self.client.get(f"/recent_changes/{sid}/changes?mode=garbage")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7.4: 跑全套测试**

Run: `python -m pytest`
Expected: 230 + 5 routes + 15 service - 已有 = 都 PASS（具体数 240 左右）

- [ ] **Step 7.5: 提交**

```bash
git add routes_recent_changes.py routes.py tests/test_recent_changes_routes.py
git commit -m "feat(recent-changes): 3 个 GET endpoint + 注册 blueprint + routes 单测"
```

---

## Task 8: HTML 加二级 tab 结构

**Files:**
- Modify: `templates/index.html` 的 `<div class="page" id="pageHistory">` 块

- [ ] **Step 8.1: 替换 pageHistory 整块**

把：

```html
<div class="page" id="pageHistory">
  <div class="panel" id="historySearchPanel">
    ...
  </div>
  <div class="panel" id="historyCurrentPanel" hidden>
    ...
  </div>
  <div class="panel" id="historyTimelinePanel" hidden>
    ...
  </div>
</div>
```

改成：

```html
<div class="page" id="pageHistory">
  <div class="tabs" id="historyTabs">
    <button class="tabs__tab active" data-history-tab="search" type="button">🔎 货号查询</button>
    <button class="tabs__tab" data-history-tab="recent" type="button">📊 最近改动</button>
  </div>

  <div class="tabs__panel active" data-history-tab-panel="search">
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

  <div class="tabs__panel" data-history-tab-panel="recent">
    <div class="panel">
      <div class="panel-hd">
        最近改动
        <div class="rc-actions">
          <select id="rcBatchSelect"></select>
          <button class="pur-btn-copy" id="rcModeToggle" data-mode="collapsed">展开 raw 事件</button>
        </div>
      </div>
      <div class="panel-bd">
        <div class="rc-summary" id="rcSummary"></div>
        <div class="rc-chips" id="rcChips"></div>
        <div class="rc-list" id="rcList"></div>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 8.2: 末尾追加新 module 的 script 标签**

找到 `<script type="module" src=".../js/data-quality.js"></script>`，**之前**或**之后**加一行：

```html
<script type="module" src="{{ url_for('static', filename='js/index-recent-changes.js') }}"></script>
```

- [ ] **Step 8.3: 启动 server 手测**

Run server，浏览器开 货号历史 tab，点二级 tab 切换：因尚未写 JS，这一步只确认 HTML 结构没破现有"货号查询"功能（输入条码、查询、显示结果仍 OK）。

- [ ] **Step 8.4: 提交**

```bash
git add templates/index.html
git commit -m "feat(recent-changes): pageHistory 加二级 tab + 最近改动占位结构"
```

---

## Task 9: 前端 module skeleton + sub-tab 切换

**Files:**
- Create: `static/js/index-recent-changes.js`
- Modify: `static/js/history.js` (暴露 search 给下钻调用)

- [ ] **Step 9.1: history.js 暴露 search 函数**

在 history.js 的 `init()` 函数最后加：

```javascript
// 暴露给最近改动模块下钻调用
window.historySearch = (q) => {
  $("historyInput").value = q;
  doSearch();
};
```

- [ ] **Step 9.2: 写 index-recent-changes.js**

```javascript
// 货号历史 - 最近改动 module
"use strict";

const $ = (id) => document.getElementById(id);

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

let _currentBatchId = null;
let _currentMode = "collapsed";
let _currentFilter = { field: null, change_type: null };
let _lastSummary = null;
let _isInitialized = false;

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

async function fetchJson(url) {
  const resp = await fetch(url);
  const data = await resp.json();
  if (!data.ok) throw new Error(data.msg || "未知错误");
  return data;
}

// === sub-tab 切换 ===
function setupTabs() {
  document.querySelectorAll('#historyTabs [data-history-tab]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.historyTab;
      document.querySelectorAll('#historyTabs [data-history-tab]').forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
      document.querySelectorAll('[data-history-tab-panel]').forEach((p) => {
        p.classList.toggle("active", p.dataset.historyTabPanel === target);
      });
      if (target === "recent" && !_isInitialized) {
        loadInitial();
        _isInitialized = true;
      }
    });
  });
}

async function loadInitial() {
  try {
    const data = await fetchJson("/recent_changes/imports");
    populateBatchDropdown(data.imports);
    if (data.imports.length === 0) {
      $("rcSummary").innerHTML = '<div class="rc-empty">还没有 import 记录</div>';
      return;
    }
    _currentBatchId = data.imports[0].batch_id;
    await refreshBatch();
  } catch (e) {
    $("rcSummary").innerHTML = `<div class="rc-error">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function populateBatchDropdown(imports) {
  const sel = $("rcBatchSelect");
  sel.innerHTML = imports.map((b) =>
    `<option value="${b.batch_id}">${escapeHtml(b.taken_at)} （${b.total_local} 条 / 改动 ${b.affected_barcodes} 个货号）</option>`
  ).join("");
  sel.onchange = () => {
    _currentBatchId = parseInt(sel.value, 10);
    _currentFilter = { field: null, change_type: null };
    refreshBatch();
  };
}

async function refreshBatch() {
  if (!_currentBatchId) return;
  await Promise.all([loadSummary(), loadChanges()]);
}

document.addEventListener("DOMContentLoaded", setupTabs);
```

- [ ] **Step 9.3: 启动 server 手测**

切到货号历史 → 最近改动 tab，应看到下拉填充批次。Console 无报错。

- [ ] **Step 9.4: 提交**

```bash
git add static/js/index-recent-changes.js static/js/history.js
git commit -m "feat(recent-changes): 前端 module skeleton + sub-tab 切换 + 批次下拉"
```

---

## Task 10: Summary 卡片渲染

**Files:**
- Modify: `static/js/index-recent-changes.js`

- [ ] **Step 10.1: 加 loadSummary + render**

在 `refreshBatch` 之前加：

```javascript
async function loadSummary() {
  try {
    const data = await fetchJson(`/recent_changes/${_currentBatchId}/summary`);
    _lastSummary = data.summary;
    renderSummary(data.summary);
  } catch (e) {
    $("rcSummary").innerHTML = `<div class="rc-error">${escapeHtml(e.message)}</div>`;
  }
}

function renderSummary(s) {
  const card = (icon, label, n, filterKey, filterValue) => `
    <button class="rc-summary-cell" data-filter-key="${filterKey || ""}" data-filter-value="${filterValue || ""}">
      <div class="rc-summary-icon">${icon}</div>
      <div class="rc-summary-num">${n}</div>
      <div class="rc-summary-label">${label}</div>
    </button>`;
  $("rcSummary").innerHTML = `
    <div class="rc-summary-grid">
      ${card("📦", "库位变更", s.location_changes, "field", "stockpile_location")}
      ${card("🏷", "型号变更", s.model_changes, "field", "product_model")}
      ${card("➕", "新增", s.inserts, "change_type", "insert")}
      ${card("❌", "失效", s.deactivates, "change_type", "deactivate")}
      ${card("♻️", "重新上架", s.reactivates, "change_type", "reactivate")}
    </div>
    <div class="rc-summary-foot">
      🔁 来回波动 ${s.roundtrip_count} 组
      <span class="rc-tip">（同 barcode+字段终态==起始态的折叠剔除噪音）</span>
    </div>`;
  // 点 cell 设过滤
  document.querySelectorAll(".rc-summary-cell").forEach((cell) => {
    cell.addEventListener("click", () => {
      const k = cell.dataset.filterKey, v = cell.dataset.filterValue;
      if (!k || !v) return;
      _currentFilter = { field: null, change_type: null };
      _currentFilter[k] = v;
      loadChanges();
    });
  });
}
```

- [ ] **Step 10.2: 手测**

切到最近改动 tab，应看到 4 个数字 cell + 一行 roundtrip 提示。

- [ ] **Step 10.3: 提交**

```bash
git add static/js/index-recent-changes.js
git commit -m "feat(recent-changes): Summary 卡片 5 数字 + roundtrip 行 + 点击设 filter"
```

---

## Task 11: Collapsed 列表渲染 + 行点击下钻

**Files:**
- Modify: `static/js/index-recent-changes.js`

- [ ] **Step 11.1: 加 loadChanges + render**

```javascript
async function loadChanges() {
  if (!_currentBatchId) return;
  const params = new URLSearchParams({ mode: _currentMode });
  if (_currentFilter.field) params.set("field", _currentFilter.field);
  if (_currentFilter.change_type) params.set("change_type", _currentFilter.change_type);
  try {
    const data = await fetchJson(`/recent_changes/${_currentBatchId}/changes?${params}`);
    if (_currentMode === "collapsed") {
      renderCollapsedList(data.changes);
    } else {
      renderRawList(data.changes);
    }
  } catch (e) {
    $("rcList").innerHTML = `<div class="rc-error">${escapeHtml(e.message)}</div>`;
  }
}

function renderCollapsedList(rows) {
  if (rows.length === 0) {
    $("rcList").innerHTML = '<div class="rc-empty">该批次无实质变更</div>';
    return;
  }
  const body = rows.map((r) => {
    const changeText = renderChangeCell(r);
    return `
      <tr class="rc-row" data-barcode="${escapeHtml(r.barcode)}">
        <td>${escapeHtml(r.barcode)}</td>
        <td>${escapeHtml(r.model || "")}</td>
        <td>${changeText}</td>
        <td class="rc-time">${escapeHtml((r.latest_at || "").slice(11, 19))}</td>
      </tr>`;
  }).join("");
  $("rcList").innerHTML = `
    <table class="rc-table">
      <thead><tr><th>货号</th><th>型号</th><th>变化</th><th>时间</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;
  document.querySelectorAll(".rc-row").forEach((tr) => {
    tr.addEventListener("click", () => drillToBarcode(tr.dataset.barcode));
  });
}

function renderChangeCell(r) {
  const fieldCn = FIELD_CN[r.field] || r.field;
  if (r.change_type === "insert") {
    return `<span class="rc-tag rc-tag--insert">➕ 新货号</span>`;
  }
  if (r.change_type === "deactivate") {
    return `<span class="rc-tag rc-tag--del">❌ 失效</span>`;
  }
  if (r.change_type === "reactivate") {
    return `<span class="rc-tag rc-tag--ok">♻️ 重新上架</span>`;
  }
  return `${fieldCn} <code>${escapeHtml(r.from_value || "")}</code> → <code>${escapeHtml(r.to_value || "")}</code>`;
}

function drillToBarcode(barcode) {
  // 切到货号查询 sub-tab
  document.querySelector('[data-history-tab="search"]').click();
  // 复用 history.js 暴露的 search
  if (window.historySearch) {
    window.historySearch(barcode);
  }
}
```

- [ ] **Step 11.2: 手测**

切到最近改动，应看到列表。点任一行 → 自动切到货号查询 tab + 自动搜索该 barcode + 显示结果。

- [ ] **Step 11.3: 提交**

```bash
git add static/js/index-recent-changes.js
git commit -m "feat(recent-changes): collapsed 列表 + 行点击下钻到货号查询"
```

---

## Task 12: Raw 模式 toggle + raw 列表

**Files:**
- Modify: `static/js/index-recent-changes.js`

- [ ] **Step 12.1: 加 raw 渲染 + toggle 处理**

```javascript
function renderRawList(rows) {
  if (rows.length === 0) {
    $("rcList").innerHTML = '<div class="rc-empty">该批次无变更事件</div>';
    return;
  }
  const body = rows.map((r) => {
    const fieldCn = FIELD_CN[r.field] || r.field;
    const typeCn = CHANGE_TYPE_CN[r.change_type] || r.change_type;
    return `
      <tr class="rc-row" data-barcode="${escapeHtml(r.barcode)}">
        <td>${escapeHtml(r.barcode)}</td>
        <td>${escapeHtml(r.model || "")}</td>
        <td>${fieldCn}</td>
        <td><code>${escapeHtml(r.old_value ?? "")}</code></td>
        <td><code>${escapeHtml(r.new_value ?? "")}</code></td>
        <td><span class="rc-tag">${typeCn}</span></td>
        <td class="rc-time">${escapeHtml((r.created_at || "").slice(11, 19))}</td>
      </tr>`;
  }).join("");
  $("rcList").innerHTML = `
    <table class="rc-table">
      <thead><tr><th>货号</th><th>型号</th><th>字段</th><th>旧值</th><th>新值</th><th>类型</th><th>时间</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;
  document.querySelectorAll(".rc-row").forEach((tr) => {
    tr.addEventListener("click", () => drillToBarcode(tr.dataset.barcode));
  });
}

function setupModeToggle() {
  $("rcModeToggle").addEventListener("click", () => {
    _currentMode = _currentMode === "collapsed" ? "raw" : "collapsed";
    const btn = $("rcModeToggle");
    btn.dataset.mode = _currentMode;
    btn.textContent = _currentMode === "collapsed" ? "展开 raw 事件" : "折叠净效应";
    loadChanges();
  });
}
```

`setupTabs` 函数末尾追加：
```javascript
  setupModeToggle();
```

- [ ] **Step 12.2: 手测**

点 toggle 按钮，文字与列表都切换；roundtrip barcode 在 raw 下能看到中间步骤。

- [ ] **Step 12.3: 提交**

```bash
git add static/js/index-recent-changes.js
git commit -m "feat(recent-changes): raw 模式 toggle + 7 列详细列表"
```

---

## Task 13: Filter chips

**Files:**
- Modify: `static/js/index-recent-changes.js`

- [ ] **Step 13.1: 加 chip 渲染**

```javascript
function renderChips() {
  const chips = [
    { label: "全部", filter: { field: null, change_type: null } },
    { label: "仅库位", filter: { field: "stockpile_location", change_type: null } },
    { label: "仅型号", filter: { field: "product_model", change_type: null } },
    { label: "仅新增", filter: { field: null, change_type: "insert" } },
    { label: "仅失效", filter: { field: null, change_type: "deactivate" } },
  ];
  if (_currentMode === "raw") {
    chips.push({ label: "仅 update", filter: { field: null, change_type: "update" } });
    chips.push({ label: "仅 reactivate", filter: { field: null, change_type: "reactivate" } });
  }
  const html = chips.map((c) => {
    const active = c.filter.field === _currentFilter.field
                && c.filter.change_type === _currentFilter.change_type;
    return `<button class="rc-chip${active ? " rc-chip--active" : ""}"
              data-filter='${JSON.stringify(c.filter)}'>${escapeHtml(c.label)}</button>`;
  }).join("");
  $("rcChips").innerHTML = html;
  document.querySelectorAll(".rc-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      _currentFilter = JSON.parse(chip.dataset.filter);
      loadChanges();
      renderChips();  // 重渲染 active 状态
    });
  });
}
```

- [ ] **Step 13.2: 在 refreshBatch 和模式切换里调用 renderChips**

`refreshBatch`:
```javascript
async function refreshBatch() {
  if (!_currentBatchId) return;
  renderChips();
  await Promise.all([loadSummary(), loadChanges()]);
}
```

`setupModeToggle` 的点击 handler 末尾：
```javascript
    renderChips();
```

- [ ] **Step 13.3: 手测**

各 chip 切换；filter 后列表正确缩小；点 summary 卡片数字也能正确同步 chip active 状态（因为重新调 renderChips 即可，但目前 summary cell click 没调；下一步加）。

修补：summary cell click handler 末尾加 `renderChips()`：

```javascript
      _currentFilter[k] = v;
      loadChanges();
      renderChips();
```

- [ ] **Step 13.4: 提交**

```bash
git add static/js/index-recent-changes.js
git commit -m "feat(recent-changes): filter chips + summary/chip 状态同步"
```

---

## Task 14: CSS + roadmap 收尾

**Files:**
- Modify: `static/css/page-history.css`
- Modify: `docs/superpowers/plans/2026-04-28-roadmap.md`

- [ ] **Step 14.1: 追加 CSS**

`static/css/page-history.css` 末尾追加：

```css
/* === 最近改动 === */
#pageHistory .tabs { margin-bottom: 8px; }

.rc-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  align-items: center;
}
.rc-actions select {
  padding: 6px 10px;
  font-size: var(--fs-base);
  border-radius: var(--r-md);
  border: 1px solid var(--c-border);
}

.rc-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 8px;
}
.rc-summary-cell {
  padding: 12px;
  text-align: center;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background: transparent;
  cursor: pointer;
  font: inherit;
}
.rc-summary-cell:hover { background: var(--c-accent-soft); }
.rc-summary-icon { font-size: 18px; }
.rc-summary-num { font-size: 22px; font-weight: 700; line-height: 1.2; }
.rc-summary-label { font-size: var(--fs-md); color: var(--c-text-dim); }
.rc-summary-foot {
  font-size: var(--fs-md);
  color: var(--c-text-dim);
  padding: 6px 0 12px;
  border-bottom: 1px solid var(--c-border);
}
.rc-summary-foot .rc-tip { font-size: var(--fs-sm); }

.rc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 0;
}
.rc-chip {
  padding: 4px 12px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-pill);
  background: transparent;
  font-size: var(--fs-md);
  cursor: pointer;
}
.rc-chip:hover { background: var(--c-accent-soft); }
.rc-chip--active { background: #586e75; color: #fdf6e3; border-color: #586e75; }

.rc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.rc-table th, .rc-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--c-border);
  text-align: left;
}
.rc-table th { background: var(--color-surface-soft, #f6f1e7); font-weight: 600; }
.rc-row { cursor: pointer; }
.rc-row:hover { background: var(--color-surface-hover, #faf6ec); }
.rc-time { color: var(--c-text-dim); font-variant-numeric: tabular-nums; }

.rc-tag { padding: 1px 8px; border-radius: var(--r-pill); background: var(--c-accent-soft); font-size: 12px; }
.rc-tag--insert { background: #dcecc1; color: #2d4a1d; }
.rc-tag--del { background: #f5c1bf; color: #6a2222; }
.rc-tag--ok { background: #c1d8ec; color: #1e3a5a; }

.rc-empty, .rc-error {
  padding: 24px;
  text-align: center;
  color: var(--c-text-dim);
}
.rc-error { color: var(--c-danger); }
```

- [ ] **Step 14.2: 追加 roadmap 条目**

在 `docs/superpowers/plans/2026-04-28-roadmap.md` 的"阶段 1.5"下方插入新阶段：

```markdown
## 阶段 1.6：货号历史 - 最近改动

**前置依赖**：阶段 1.5（snapshots 表已稳定）

- [x] 主用例：import 后审计 / 收据。按批次（snapshots trigger='import'）切窗口
- [x] 默认折叠净效应（按 barcode+field 维度），剔除 round-trip 中间步骤
- [x] Raw 模式 toggle 切原始事件
- [x] Summary 4 数字 + roundtrip 数 + 点击数字设 filter
- [x] Filter chip：按字段 / 按 change_type
- [x] 行点击下钻到 "🔎 货号查询"（复用现有 search）
- [x] 后端 service+routes 单测 ~15 case
```

- [ ] **Step 14.3: 跑全套 pytest**

Run: `python -m pytest`
Expected: all PASS

- [ ] **Step 14.4: 启动 server 完整手测清单**

逐项验证：

- 货号历史 → 「📊 最近改动」tab 可切换
- 批次下拉默认选最新 import，切换 → 数据刷新
- Summary 4 个 cell + roundtrip 行显示
- 点 「📦 库位变更」cell → 列表只剩 location 变更
- 点 chip 切换 → 列表更新 + active 状态同步
- 点列表行 → 切回「🔎 货号查询」tab + 自动搜索该 barcode
- 点 「展开 raw 事件」toggle → 列表变 7 列含中间步骤；roundtrip barcode 出现两条
- 切回 collapsed → 那个 barcode 不再出现

- [ ] **Step 14.5: 提交并推送**

```bash
git add static/css/page-history.css docs/superpowers/plans/2026-04-28-roadmap.md
git commit -m "feat(recent-changes): CSS 美化 + 收尾文档"
git push
```

---

## 完成标准

- [ ] 全套 pytest 230 + 15 service + 5 routes ≈ 250 PASS
- [ ] 浏览器手测 8 项清单全过
- [ ] 分支 `feature/recent-changes` 推到 origin
- [ ] roadmap.md 更新阶段 1.6
- [ ] 准备合并到 main 时再开 PR
