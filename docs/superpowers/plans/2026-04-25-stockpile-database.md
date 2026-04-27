# Stockpile 本地数据库化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 stockpile 从每次手动上传 CSV 改为本地 SQLite 持久化数据库，处理过程中的修改自动积累，过渡期内支持月度比对校验。

**Architecture:** 新增 `stockpile_db.py` 封装所有 SQLite CRUD + 比对逻辑。Phase 2 改从 DB 读代替 CSV 文件读。`barcode_service.py` 纠错时自动写 DB。`task_service.py` Phase 3 完成后将新品条码入库。

**Tech Stack:** Python 3.10+ sqlite3（内置）、Flask、pandas、unittest

---

### Task 1: 项目配置与 gitignore

**Files:**
- Modify: `config.py:20-72`
- Modify: `.gitignore:22-23`
- Modify: `state.py:1-15`

- [ ] **Step 1: 在 config.py 添加 stockpile_db 路径属性**

编辑 `config.py`，在 `AppConfig` 类的属性区域（`temp_results_file` 之后）添加：

```python
    @property
    def stockpile_db(self) -> Path:
        return self.base_dir / "stockpile.db"
```

- [ ] **Step 2: 在 state.py 暴露 CONFIG 属性**

编辑 `state.py`，在 `TEMP_RESULTS_FILE = CONFIG.temp_results_file` 之后添加：

```python
STOCKPILE_DB = CONFIG.stockpile_db
```

- [ ] **Step 3: 在 .gitignore 添加 stockpile.db**

编辑 `.gitignore`，在 `_temp_results.json` 行后添加：

```
stockpile.db
```

- [ ] **Step 4: 验证 import 不报错**

```powershell
python -c "from config import CONFIG; print(CONFIG.stockpile_db)"
```

- [ ] **Step 5: Commit**

```bash
git add config.py state.py .gitignore
git commit -m "chore: add stockpile_db path to config and gitignore"
```

---

### Task 2: 创建 stockpile_db.py 核心模块

**Files:**
- Create: `stockpile_db.py`

- [ ] **Step 1: 写 stockpile_db.py（含建表、导入、查询、增改、比对全功能）**

```python
import json
import sqlite3
from pathlib import Path

import pandas as pd

from config import CONFIG

DB_PATH = CONFIG.stockpile_db


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_db() -> None:
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stockpile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_barcode TEXT NOT NULL UNIQUE,
            product_model TEXT NOT NULL,
            stockpile_location TEXT NOT NULL,
            extra TEXT DEFAULT '{}',
            source TEXT DEFAULT 'system_export',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS stockpile_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_barcode TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            change_type TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_stockpile_barcode ON stockpile(product_barcode);
        CREATE INDEX IF NOT EXISTS idx_changes_barcode ON stockpile_changes(product_barcode);
    """)
    conn.commit()
    conn.close()


def is_initialized() -> bool:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT COUNT(*) FROM stockpile")
    count = cur.fetchone()[0]
    conn.close()
    return count > 0


def import_from_dataframe(df: pd.DataFrame) -> int:
    ensure_db()
    columns = [str(c).strip() for c in df.columns]
    known_cols = {"product_barcode", "product_model", "stockpile_location"}
    extra_cols = [c for c in columns if c not in known_cols]

    conn = _connect()
    inserted = 0
    for _, row in df.iterrows():
        barcode = str(row.get("product_barcode", "")).strip()
        if not barcode or barcode == "nan":
            continue
        model = str(row.get("product_model", "")).strip()
        if model == "nan":
            model = ""
        location = str(row.get("stockpile_location", "")).strip()
        if location == "nan":
            location = ""
        extra = {c: str(row.get(c, "")) for c in extra_cols}
        conn.execute(
            "INSERT OR REPLACE INTO stockpile (product_barcode, product_model, stockpile_location, extra, source, updated_at) "
            "VALUES (?, ?, ?, ?, 'system_export', datetime('now','localtime'))",
            (barcode, model, location, json.dumps(extra, ensure_ascii=False)),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def query_by_barcode(barcode: str) -> dict | None:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def query_all_as_system_records() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT product_barcode, product_model, stockpile_location FROM stockpile")
    barcode_model_map: dict[str, str] = {}
    system_records: dict[str, dict[str, str]] = {}
    for row in cur:
        barcode = row["product_barcode"]
        model = row["product_model"]
        location = row["stockpile_location"]
        barcode_model_map[barcode] = model
        system_records[barcode] = {"model": model, "stockpile_location": location}
    conn.close()
    return barcode_model_map, system_records


def query_all_barcodes_set() -> set[str]:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT product_barcode FROM stockpile")
    result = {row["product_barcode"] for row in cur}
    conn.close()
    return result


def _log_change(conn: sqlite3.Connection, barcode: str, field: str, old_val: str | None, new_val: str | None, change_type: str) -> None:
    conn.execute(
        "INSERT INTO stockpile_changes (product_barcode, field_name, old_value, new_value, change_type) VALUES (?, ?, ?, ?, ?)",
        (barcode, field, old_val, new_val, change_type),
    )


def insert_or_update(barcode: str, model: str, location: str, source: str = "user_correction", extra: dict | None = None) -> None:
    ensure_db()
    conn = _connect()
    existing = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()

    if existing:
        for field_key, field_name in [("product_model", "product_model"), ("stockpile_location", "stockpile_location")]:
            new_value = model if field_key == "product_model" else location
            old_value = existing[field_key]
            if old_value != new_value:
                _log_change(conn, barcode, field_name, old_value, new_value, "update")
        conn.execute(
            "UPDATE stockpile SET product_model=?, stockpile_location=?, source=?, extra=?, updated_at=datetime('now','localtime') WHERE product_barcode=?",
            (model, location, source, json.dumps(extra or {}, ensure_ascii=False), barcode),
        )
    else:
        conn.execute(
            "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, extra, source) VALUES (?, ?, ?, ?, ?)",
            (barcode, model, location, json.dumps(extra or {}, ensure_ascii=False), source),
        )
        _log_change(conn, barcode, "product_barcode", None, barcode, "insert")

    conn.commit()
    conn.close()


def update_location(barcode: str, new_location: str) -> None:
    ensure_db()
    conn = _connect()
    existing = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
    if not existing:
        conn.close()
        return
    old_location = existing["stockpile_location"]
    if old_location != new_location:
        _log_change(conn, barcode, "stockpile_location", old_location, new_location, "update")
        conn.execute(
            "UPDATE stockpile SET stockpile_location=?, source='user_correction', updated_at=datetime('now','localtime') WHERE product_barcode=?",
            (new_location, barcode),
        )
        conn.commit()
    conn.close()


def count_records() -> int:
    ensure_db()
    conn = _connect()
    cur = conn.execute("SELECT COUNT(*) FROM stockpile")
    count = cur.fetchone()[0]
    conn.close()
    return count


def compare_with_dataframe(df: pd.DataFrame) -> dict:
    ensure_db()
    local_barcodes = query_all_barcodes_set()
    columns = [str(c).strip() for c in df.columns]

    export_records: dict[str, dict[str, str]] = {}
    extra_cols = [c for c in columns if c not in {"product_barcode", "product_model", "stockpile_location"}]
    for _, row in df.iterrows():
        barcode = str(row.get("product_barcode", "")).strip()
        if not barcode or barcode == "nan":
            continue
        export_records[barcode] = {
            "product_model": str(row.get("product_model", "")).strip(),
            "stockpile_location": str(row.get("stockpile_location", "")).strip(),
        }

    export_barcodes = set(export_records.keys())

    only_local = sorted(barcode for barcode in local_barcodes if barcode not in export_barcodes)
    only_export = sorted(barcode for barcode in export_barcodes if barcode not in local_barcodes)

    mismatches: list[dict] = []
    conn = _connect()
    for barcode in local_barcodes & export_barcodes:
        local = conn.execute("SELECT product_model, stockpile_location FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
        if local is None:
            continue
        export = export_records[barcode]
        if local["product_model"] != export["product_model"] or local["stockpile_location"] != export["stockpile_location"]:
            mismatches.append({
                "barcode": barcode,
                "local_model": local["product_model"],
                "export_model": export["product_model"],
                "local_location": local["stockpile_location"],
                "export_location": export["stockpile_location"],
            })
    conn.close()

    return {
        "total_local": len(local_barcodes),
        "total_export": len(export_barcodes),
        "only_in_local": only_local,
        "only_in_export": only_export,
        "mismatches": mismatches,
        "consistent": len(local_barcodes & export_barcodes) - len(mismatches),
    }


def apply_export_updates(df: pd.DataFrame) -> int:
    ensure_db()
    columns = [str(c).strip() for c in df.columns]
    extra_cols = [c for c in columns if c not in {"product_barcode", "product_model", "stockpile_location"}]
    conn = _connect()
    updated = 0
    for _, row in df.iterrows():
        barcode = str(row.get("product_barcode", "")).strip()
        if not barcode or barcode == "nan":
            continue
        model = str(row.get("product_model", "")).strip()
        location = str(row.get("stockpile_location", "")).strip()
        extra = {c: str(row.get(c, "")) for c in extra_cols}
        existing = conn.execute("SELECT * FROM stockpile WHERE product_barcode = ?", (barcode,)).fetchone()
        if existing:
            if existing["product_model"] != model or existing["stockpile_location"] != location:
                _log_change(conn, barcode, "product_model", existing["product_model"], model, "update")
                _log_change(conn, barcode, "stockpile_location", existing["stockpile_location"], location, "update")
            conn.execute(
                "UPDATE stockpile SET product_model=?, stockpile_location=?, extra=?, source='system_export', updated_at=datetime('now','localtime') WHERE product_barcode=?",
                (model, location, json.dumps(extra, ensure_ascii=False), barcode),
            )
        else:
            conn.execute(
                "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, extra, source) VALUES (?, ?, ?, ?, 'system_export')",
                (barcode, model, location, json.dumps(extra, ensure_ascii=False)),
            )
            _log_change(conn, barcode, "product_barcode", None, barcode, "insert")
        updated += 1
    conn.commit()
    conn.close()
    return updated
```

- [ ] **Step 2: 验证模块可导入**

```powershell
python -c "import stockpile_db; stockpile_db.ensure_db(); print('DB created at:', stockpile_db.DB_PATH); print('initialized:', stockpile_db.is_initialized())"
```

Expected output: `DB created at: .../stockpile.db` `initialized: False`

- [ ] **Step 3: Commit**

```bash
git add stockpile_db.py
git commit -m "feat: add stockpile_db core module with CRUD and compare"
```

---

### Task 3: 为 stockpile_db.py 写单元测试

**Files:**
- Create: `tests/test_stockpile_db.py`

- [ ] **Step 1: 写测试文件**

```python
import json
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import stockpile_db

TEST_TMP_DIR = Path(__file__).resolve().parent / "_tmp"
TEST_DB = TEST_TMP_DIR / "test_stockpile.db"


class StockpileDbTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_DIR.mkdir(exist_ok=True)
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", TEST_DB)
        self.patch.start()
        if TEST_DB.exists():
            TEST_DB.unlink()

    def tearDown(self) -> None:
        self.patch.stop()
        if TEST_DB.exists():
            TEST_DB.unlink()

    def test_ensure_db_creates_tables(self) -> None:
        stockpile_db.ensure_db()
        self.assertTrue(TEST_DB.exists())

    def test_is_initialized_returns_false_for_empty_db(self) -> None:
        stockpile_db.ensure_db()
        self.assertFalse(stockpile_db.is_initialized())

    def test_is_initialized_returns_true_after_import(self) -> None:
        df = pd.DataFrame([{"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"}])
        stockpile_db.import_from_dataframe(df)
        self.assertTrue(stockpile_db.is_initialized())

    def test_import_from_dataframe_inserts_records(self) -> None:
        df = pd.DataFrame([
            {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "L1"},
            {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "L2"},
        ])
        count = stockpile_db.import_from_dataframe(df)
        self.assertEqual(count, 2)
        self.assertEqual(stockpile_db.count_records(), 2)

    def test_import_handles_extra_columns_in_json(self) -> None:
        df = pd.DataFrame([{
            "product_barcode": "A1", "product_model": "M1",
            "stockpile_location": "L1", "price": "100", "stock": "50"
        }])
        stockpile_db.import_from_dataframe(df)
        record = stockpile_db.query_by_barcode("A1")
        self.assertIsNotNone(record)
        extra = json.loads(record["extra"])
        self.assertEqual(extra["price"], "100")
        self.assertEqual(extra["stock"], "50")

    def test_import_skip_nan_barcode(self) -> None:
        df = pd.DataFrame([{"product_barcode": None, "product_model": "M1", "stockpile_location": "L1"}])
        count = stockpile_db.import_from_dataframe(df)
        self.assertEqual(count, 0)

    def test_query_by_barcode_returns_none_for_missing(self) -> None:
        self.assertIsNone(stockpile_db.query_by_barcode("NOPE"))

    def test_query_by_barcode_returns_record(self) -> None:
        df = pd.DataFrame([{"product_barcode": "X99", "product_model": "MX", "stockpile_location": "LX"}])
        stockpile_db.import_from_dataframe(df)
        record = stockpile_db.query_by_barcode("X99")
        self.assertIsNotNone(record)
        self.assertEqual(record["product_model"], "MX")

    def test_query_all_as_system_records_returns_maps(self) -> None:
        df = pd.DataFrame([
            {"product_barcode": "111", "product_model": "M-111", "stockpile_location": "A-01-01/X-01-01"},
            {"product_barcode": "222", "product_model": "M-222", "stockpile_location": "B-02-02"},
        ])
        stockpile_db.import_from_dataframe(df)
        barcode_model_map, system_records = stockpile_db.query_all_as_system_records()
        self.assertEqual(barcode_model_map["111"], "M-111")
        self.assertEqual(system_records["111"]["stockpile_location"], "A-01-01/X-01-01")
        self.assertEqual(system_records["222"]["model"], "M-222")
        self.assertNotIn("333", system_records)

    def test_insert_or_update_inserts_new(self) -> None:
        stockpile_db.insert_or_update("NEW1", "ModelNew", "LocNew", source="scan_new")
        record = stockpile_db.query_by_barcode("NEW1")
        self.assertEqual(record["product_model"], "ModelNew")
        self.assertEqual(record["source"], "scan_new")

    def test_insert_or_update_updates_existing(self) -> None:
        df = pd.DataFrame([{"product_barcode": "U1", "product_model": "Old", "stockpile_location": "OldLoc"}])
        stockpile_db.import_from_dataframe(df)
        stockpile_db.insert_or_update("U1", "New", "NewLoc", source="user_correction")
        record = stockpile_db.query_by_barcode("U1")
        self.assertEqual(record["product_model"], "New")
        self.assertEqual(record["source"], "user_correction")

    def test_changes_logged_on_update(self) -> None:
        df = pd.DataFrame([{"product_barcode": "C1", "product_model": "Old", "stockpile_location": "OldLoc"}])
        stockpile_db.import_from_dataframe(df)
        stockpile_db.insert_or_update("C1", "New", "NewLoc")

        conn = stockpile_db._connect()
        cur = conn.execute("SELECT * FROM stockpile_changes WHERE product_barcode = ?", ("C1",))
        changes = cur.fetchall()
        conn.close()
        self.assertGreaterEqual(len(changes), 1)

    def test_update_location_changes_location(self) -> None:
        df = pd.DataFrame([{"product_barcode": "L1", "product_model": "M1", "stockpile_location": "OldLoc"}])
        stockpile_db.import_from_dataframe(df)
        stockpile_db.update_location("L1", "NewLoc")
        record = stockpile_db.query_by_barcode("L1")
        self.assertEqual(record["stockpile_location"], "NewLoc")

    def test_update_location_noop_for_unknown_barcode(self) -> None:
        stockpile_db.update_location("NOBODY", "Loc")
        self.assertTrue(True)

    def test_query_all_barcodes_set(self) -> None:
        df = pd.DataFrame([
            {"product_barcode": "B1", "product_model": "M1", "stockpile_location": "L1"},
            {"product_barcode": "B2", "product_model": "M2", "stockpile_location": "L2"},
        ])
        stockpile_db.import_from_dataframe(df)
        result = stockpile_db.query_all_barcodes_set()
        self.assertEqual(result, {"B1", "B2"})

    def test_compare_with_dataframe_finds_matches_and_mismatches(self) -> None:
        df_local = pd.DataFrame([
            {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "A/X"},
            {"product_barcode": "A2", "product_model": "M2", "stockpile_location": "B/Y"},
        ])
        stockpile_db.import_from_dataframe(df_local)

        df_export = pd.DataFrame([
            {"product_barcode": "A1", "product_model": "M1", "stockpile_location": "A/X"},
            {"product_barcode": "A2", "product_model": "M2_CHANGED", "stockpile_location": "B/Y"},
            {"product_barcode": "A3", "product_model": "M3", "stockpile_location": "C/Z"},
        ])
        result = stockpile_db.compare_with_dataframe(df_export)
        self.assertEqual(result["total_local"], 2)
        self.assertEqual(result["total_export"], 3)
        self.assertEqual(result["only_in_local"], [])
        self.assertEqual(result["only_in_export"], ["A3"])
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertEqual(result["mismatches"][0]["barcode"], "A2")
        self.assertEqual(result["consistent"], 1)

    def test_apply_export_updates_overwrites_local(self) -> None:
        df_local = pd.DataFrame([
            {"product_barcode": "X1", "product_model": "Old", "stockpile_location": "OldLoc"},
        ])
        stockpile_db.import_from_dataframe(df_local)

        df_export = pd.DataFrame([
            {"product_barcode": "X1", "product_model": "New", "stockpile_location": "NewLoc"},
            {"product_barcode": "X2", "product_model": "Fresh", "stockpile_location": "F/Loc"},
        ])
        updated = stockpile_db.apply_export_updates(df_export)
        self.assertEqual(updated, 2)

        r1 = stockpile_db.query_by_barcode("X1")
        self.assertEqual(r1["product_model"], "New")
        self.assertEqual(r1["source"], "system_export")

        r2 = stockpile_db.query_by_barcode("X2")
        self.assertIsNotNone(r2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认全部通过**

```powershell
python -m pytest tests/test_stockpile_db.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_stockpile_db.py
git commit -m "test: add stockpile_db unit tests"
```

---

### Task 4: 修改 Phase 2 从 stockpile_db 读取

**Files:**
- Modify: `update_location_phase2.py:1-167`
- Modify: `storage_service.py:49-51`

- [ ] **Step 1: 修改 update_location_phase2.py 的 main() 函数**

编辑 `update_location_phase2.py`，将 `main()` 函数中读取 stockpile CSV 的部分替换为从 DB 读取。

找到 `main()` 函数中的这段代码（约 133-139 行）：

```python
    stockpile_path = find_latest_stockpile_file(INPUT_DIR)
    if stockpile_path is None:
        print("ERROR: missing stockpile csv")
        return 1
    print(f"STOCKPILE {stockpile_path.name}")

    barcode_model_map, system_records = build_system_records(read_csv(stockpile_path))
```

替换为：

```python
    from stockpile_db import query_all_as_system_records

    if not INPUT_DIR.exists():
        print("ERROR: input directory not found")
        return 1

    barcode_model_map, system_records = query_all_as_system_records()
    if not system_records:
        print("ERROR: stockpile database is empty, please initialize it first")
        return 1
    print(f"STOCKPILE_DB {len(system_records)} records")
```

同时，修改 `write_phase2_results` 调用中的 `stockpile_path` 参数，因为在没有 CSV 文件时只需要一个标记：

```python
    write_phase2_results(
        TEMP_RESULTS_FILE, results, new_barcodes, exceptions, unmatched_barcodes,
        employee_name, scan_files, barcode_model_map, Path("stockpile.db"),
    )
```

并且移除顶部不再需要的 import：删除 `from file_io import find_latest_stockpile_file, read_csv` 中的 `find_latest_stockpile_file, read_csv`，只保留 `write_phase2_results`。

最终 import 行变为：

```python
from file_io import write_phase2_results
```

- [ ] **Step 2: 修改 update_location.py Phase 3 不再移动 stockpile CSV**

编辑 `update_location.py`，修改 `main()` 中移动 stockpile 文件的代码。找到约 148-155 行：

```python
    system_trash_path = TRASH_DIR / f"{stockpile_path.stem}_{trash_suffix}.csv"
    shutil.move(stockpile_path, system_trash_path)
    print(f"TRASH_STOCKPILE {system_trash_path.name}")
```

替换为（现在 stockpile 不再是一个物理 CSV 文件，而是数据库记录）：

```python
    # stockpile is now in local database, no CSV file to archive
    print(f"TRASH_STOCKPILE (database, skipped)")
```

同时移除顶部不再需要的 import：

```python
from file_io import find_latest_stockpile_file, read_csv
```

改为：

```python
from file_io import read_csv
```

- [ ] **Step 3: 修改 storage_service.py 的 validate_stockpile_is_today()**

编辑 `storage_service.py`，将 `validate_stockpile_is_today()` 替换为检查 stockpile_db 是否已初始化：

```python
def validate_stockpile_is_ready() -> tuple[bool, str | None]:
    from stockpile_db import is_initialized

    if not is_initialized():
        return False, "stockpile 数据库尚未初始化，请先通过"初始化 stockpile 数据库"上传系统导出文件"
    return True, None
```

保留原 `validate_stockpile_is_today()` 和 `find_stockpile_file()` 不做删除（它们可能仍被其他地方引用），但不再用于主流程。

- [ ] **Step 4: 修改 routes_pages_tasks.py 的 /run 路由校验**

编辑 `routes_pages_tasks.py`，找到 `/run` 路由约 37 行：

```python
    is_valid, error_message = storage_service.validate_stockpile_is_today()
```

替换为：

```python
    is_valid, error_message = storage_service.validate_stockpile_is_ready()
```

- [ ] **Step 5: 运行现有 Phase 2 测试确认不改坏**

```powershell
python -m pytest tests/test_scripts.py -v
```

- [ ] **Step 6: Commit**

```bash
git add update_location_phase2.py update_location.py storage_service.py routes_pages_tasks.py
git commit -m "refactor: switch Phase 2 stockpile read from CSV file to stockpile_db"
```

---

### Task 5: 修改 barcode_service.py 自动写入 stockpile_db

**Files:**
- Modify: `barcode_service.py:52-111`

- [ ] **Step 1: 添加 auto-save 导入**

编辑 `barcode_service.py`，在文件顶部 import 区域（`from state import ...` 之后）添加：

```python
import stockpile_db
```

- [ ] **Step 2: 修改 _load_stockpile_records 从 DB 读取**

编辑 `barcode_service.py`，找到 `_load_stockpile_records` 函数（约 45-49 行）：

```python
def _load_stockpile_records(stockpile_path: str) -> dict[str, dict[str, str]]:
    from file_io import read_csv
    from update_location_phase2 import build_system_records
    _, records = build_system_records(read_csv(Path(stockpile_path)))
    return records
```

替换为：

```python
def _load_stockpile_records(stockpile_path: str) -> dict[str, dict[str, str]]:
    _, records = stockpile_db.query_all_as_system_records()
    return records
```

- [ ] **Step 3: 在 _correct_new_barcode 中添加 auto-save**

编辑 `barcode_service.py`，在 `_correct_new_barcode` 函数的 `_modifier` 内部末尾添加 stockpile_db 写入。

找到 `_modifier` 函数中（约 102 行）的：

```python
        data["new_barcodes"] = new_list
```

替换为：

```python
        data["new_barcodes"] = new_list
        if not mismatch:
            if entry_idx is not None:
                location = data["results"][entry_idx]["location"]
                model = data["results"][entry_idx]["model"]
            else:
                location = ""
                model = new_barcode
            stockpile_db.insert_or_update(new_barcode, model, location, source="user_correction")
```

- [ ] **Step 4: correct_location 不需要修改（操作的是扫描库位，非 stockpile）**

- [ ] **Step 5: 运行 barcode service 测试确认不改坏**

```powershell
python -m pytest tests/test_barcode_service.py -v
```

测试可能因为 stockpile_db 内部逻辑而需要调整。如果测试用了 mock `TEMP_RESULTS_FILE`，但 `stockpile_db` 未被 mock，就需要在 setUp 中 mock `stockpile_db.insert_or_update`。

如果测试失败（因为真实的 stockpile_db 调用），在测试文件的 `setUp` 中添加：

```python
self.patch_db = mock.patch.object(barcode_service.stockpile_db, "insert_or_update")
self.patch_db.start()
```

并在 `tearDown` 中添加：

```python
self.patch_db.stop()
```

- [ ] **Step 6: Commit**

```bash
git add barcode_service.py
git commit -m "feat: auto-save barcode corrections to stockpile_db"
```

---

### Task 6: 添加初始化与比对路由

**Files:**
- Create: `routes_stockpile.py`

- [ ] **Step 1: 写 routes_stockpile.py**

```python
import os

from flask import Blueprint, jsonify, request, send_file

import stockpile_db
from file_io import read_input_file
from path_safety import safe_filename
from schemas import ServiceResult
from state import INPUT_DIR

bp = Blueprint("stockpile", __name__)


@bp.post("/stockpile/init")
def init_stockpile():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400

    file_storage = files[0]
    if not file_storage.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    filename = safe_filename(file_storage.filename)
    file_path = INPUT_DIR / filename
    file_storage.save(file_path)

    dataframe = read_input_file(file_path)
    if dataframe is None:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"ok": False, "msg": "无法读取文件，支持 .xlsx/.xls/.csv"}), 400

    count = stockpile_db.import_from_dataframe(dataframe)

    try:
        os.remove(file_path)
    except OSError:
        pass

    return jsonify({"ok": True, "count": count})


@bp.post("/stockpile/compare")
def compare_stockpile():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400

    file_storage = files[0]
    if not file_storage.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    filename = safe_filename(file_storage.filename)
    file_path = INPUT_DIR / filename
    file_storage.save(file_path)

    dataframe = read_input_file(file_path)
    if dataframe is None:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"ok": False, "msg": "无法读取文件，支持 .xlsx/.xls/.csv"}), 400

    diff = stockpile_db.compare_with_dataframe(dataframe)

    try:
        os.remove(file_path)
    except OSError:
        pass

    return jsonify({"ok": True, "diff": diff})


@bp.post("/stockpile/apply-export")
def apply_export():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "msg": "没有收到文件"}), 400

    file_storage = files[0]
    if not file_storage.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    filename = safe_filename(file_storage.filename)
    file_path = INPUT_DIR / filename
    file_storage.save(file_path)

    dataframe = read_input_file(file_path)
    if dataframe is None:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"ok": False, "msg": "无法读取文件，支持 .xlsx/.xls/.csv"}), 400

    updated = stockpile_db.apply_export_updates(dataframe)

    try:
        os.remove(file_path)
    except OSError:
        pass

    return jsonify({"ok": True, "updated": updated})


@bp.get("/stockpile/status")
def stockpile_status():
    initialized = stockpile_db.is_initialized()
    count = stockpile_db.count_records() if initialized else 0
    return jsonify({"ok": True, "initialized": initialized, "count": count})
```

- [ ] **Step 2: 验证路由可导入**

```powershell
python -c "from routes_stockpile import bp; print(bp.name)"
```

Expected: `stockpile`

- [ ] **Step 3: Commit**

```bash
git add routes_stockpile.py
git commit -m "feat: add stockpile init, compare, and apply-export routes"
```

---

### Task 7: 注册新路由和更新 server.py

**Files:**
- Modify: `routes.py:1-20`
- Modify: `server.py:1-37`

- [ ] **Step 1: 在 routes.py 注册 stockpile 蓝图**

编辑 `routes.py`，添加 import 和注册：

在文件顶部现有 import 之后添加：

```python
from routes_stockpile import bp as stockpile_bp
```

在 `register_routes` 函数中，于其他蓝图注册后添加：

```python
    app.register_blueprint(stockpile_bp)
```

- [ ] **Step 2: 在 server.py 的 create_app 中调用 stockpile_db.ensure_db()**

编辑 `server.py`，在 `import` 区域中添加：

```python
import stockpile_db
```

在 `create_app()` 函数中，`storage_service.startup_cleanup()` 之后添加：

```python
    stockpile_db.ensure_db()
```

- [ ] **Step 3: 验证应用能启动**

```powershell
python -c "from server import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add routes.py server.py
git commit -m "feat: register stockpile routes and auto-init DB on startup"
```

---

### Task 8: 修改前端模板添加初始化与比对 UI

**Files:**
- Modify: `templates/index.html:17-34`

- [ ] **Step 1: 在 index.html 的 "文件上传与处理" panel 中添加 UI**

编辑 `templates/index.html`，在 `pageMain` 的 panel 区域内添加初始化区和比对区。

在现有文件上传面板下方（`处理` 按钮之后，`</div></div>` 结束之前）添加新的 HTML 块。

找到约 33 行：

```html
           <div class="status" id="status">请先上传文件</div>
         </div></div>
```

替换为：

```html
           <div class="status" id="status">请先上传文件</div>
         </div></div>

         <div class="panel"><div class="panel-hd">stockpile 数据库管理</div><div class="panel-bd">
           <div class="stockpile-status" id="spStatus" style="margin-bottom:8px;color:#666">检查中...</div>
           <div style="display:flex;gap:8px;flex-wrap:wrap">
             <div class="drop" id="spInitDrop" style="flex:1;min-width:200px"><input type="file" id="spInitInput" accept=".xlsx,.csv"><div>拖入系统导出文件初始化数据库</div></div>
             <button class="btn u" id="spInitBtn" disabled>初始化</button>
           </div>
           <div id="spInitMsg" style="margin-top:4px;font-size:12px;color:#999"></div>
           <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
             <div class="drop" id="spCmpDrop" style="flex:1;min-width:200px"><input type="file" id="spCmpInput" accept=".xlsx,.csv"><div>拖入系统导出文件进行月度比对</div></div>
             <button class="btn u" id="spCmpBtn" disabled>比对</button>
           </div>
           <div id="spCmpRes" style="margin-top:8px;font-size:12px"></div>
         </div></div>
```

- [ ] **Step 2: 在 index.js 添加对应的 JS 逻辑**

编辑 `static/js/index.js`，在文件末尾添加 stockpile 管理 JS：

```javascript
// --- stockpile database management ---
const spStatus = document.getElementById('spStatus');
const spInitDrop = document.getElementById('spInitDrop');
const spInitInput = document.getElementById('spInitInput');
const spInitBtn = document.getElementById('spInitBtn');
const spInitMsg = document.getElementById('spInitMsg');
const spCmpDrop = document.getElementById('spCmpDrop');
const spCmpInput = document.getElementById('spCmpInput');
const spCmpBtn = document.getElementById('spCmpBtn');
const spCmpRes = document.getElementById('spCmpRes');

let spInitFile = null;
let spCmpFile = null;

spInitDrop.addEventListener('click', () => spInitInput.click());
spCmpDrop.addEventListener('click', () => spCmpInput.click());

spInitDrop.addEventListener('dragover', e => { e.preventDefault(); spInitDrop.classList.add('drag'); });
spInitDrop.addEventListener('dragleave', () => spInitDrop.classList.remove('drag'));
spInitDrop.addEventListener('drop', e => {
    e.preventDefault();
    spInitDrop.classList.remove('drag');
    if (e.dataTransfer.files.length) {
        spInitInput.files = e.dataTransfer.files;
        spInitFile = e.dataTransfer.files[0];
        spInitBtn.disabled = false;
        spInitDrop.querySelector('div').textContent = spInitFile.name;
    }
});

spCmpDrop.addEventListener('dragover', e => { e.preventDefault(); spCmpDrop.classList.add('drag'); });
spCmpDrop.addEventListener('dragleave', () => spCmpDrop.classList.remove('drag'));
spCmpDrop.addEventListener('drop', e => {
    e.preventDefault();
    spCmpDrop.classList.remove('drag');
    if (e.dataTransfer.files.length) {
        spCmpInput.files = e.dataTransfer.files;
        spCmpFile = e.dataTransfer.files[0];
        spCmpBtn.disabled = false;
        spCmpDrop.querySelector('div').textContent = spCmpFile.name;
    }
});

spInitInput.addEventListener('change', () => {
    if (spInitInput.files.length) {
        spInitFile = spInitInput.files[0];
        spInitBtn.disabled = false;
        spInitDrop.querySelector('div').textContent = spInitFile.name;
    }
});

spCmpInput.addEventListener('change', () => {
    if (spCmpInput.files.length) {
        spCmpFile = spCmpInput.files[0];
        spCmpBtn.disabled = false;
        spCmpDrop.querySelector('div').textContent = spCmpFile.name;
    }
});

spInitBtn.addEventListener('click', async () => {
    if (!spInitFile) return;
    spInitBtn.disabled = true;
    spInitBtn.textContent = '导入中...';
    spInitMsg.textContent = '';

    const form = new FormData();
    form.append('files', spInitFile);

    try {
        const res = await fetch('/stockpile/init', { method: 'POST', body: form });
        const data = await res.json();
        if (data.ok) {
            spInitMsg.textContent = '导入成功，共 ' + data.count + ' 条记录';
            spInitMsg.style.color = '#2e7d32';
            refreshSpStatus();
        } else {
            spInitMsg.textContent = '导入失败：' + data.msg;
            spInitMsg.style.color = '#c62828';
        }
    } catch (e) {
        spInitMsg.textContent = '网络错误';
        spInitMsg.style.color = '#c62828';
    }
    spInitBtn.disabled = false;
    spInitBtn.textContent = '初始化';
});

spCmpBtn.addEventListener('click', async () => {
    if (!spCmpFile) return;
    spCmpBtn.disabled = true;
    spCmpBtn.textContent = '比对中...';
    spCmpRes.innerHTML = '';

    const form = new FormData();
    form.append('files', spCmpFile);

    try {
        const res = await fetch('/stockpile/compare', { method: 'POST', body: form });
        const data = await res.json();
        if (data.ok) {
            const d = data.diff;
            let html = '<b>比对结果：</b><br>';
            html += '本地记录：' + d.total_local + ' &nbsp; 导出记录：' + d.total_export + ' &nbsp; 一致：' + d.consistent + '<br>';
            if (d.only_in_local.length) html += '<span style="color:#e65100">仅本地有：' + d.only_in_local.join(', ') + '</span><br>';
            if (d.only_in_export.length) html += '<span style="color:#1565c0">仅导出有：' + d.only_in_export.join(', ') + '</span><br>';
            if (d.mismatches.length) {
                html += '<span style="color:#c62828">不一致条数：' + d.mismatches.length + '</span><br>';
                html += d.mismatches.slice(0, 5).map(m => m.barcode + ': 型号(' + m.local_model + '→' + m.export_model + ')').join('<br>');
                if (d.mismatches.length > 5) html += '<br>...等共' + d.mismatches.length + '条';
            }
            if (!d.only_in_local.length && !d.only_in_export.length && !d.mismatches.length) {
                html += '<b style="color:#2e7d32">完全一致</b>';
            }
            spCmpRes.innerHTML = html;
        } else {
            spCmpRes.innerHTML = '<span style="color:#c62828">比对失败：' + data.msg + '</span>';
        }
    } catch (e) {
        spCmpRes.innerHTML = '<span style="color:#c62828">网络错误</span>';
    }
    spCmpBtn.disabled = false;
    spCmpBtn.textContent = '比对';
});

async function refreshSpStatus() {
    try {
        const res = await fetch('/stockpile/status');
        const data = await res.json();
        if (data.initialized) {
            spStatus.textContent = '状态：已初始化，共 ' + data.count + ' 条记录';
            spStatus.style.color = '#2e7d32';
        } else {
            spStatus.textContent = '状态：未初始化，请先上传系统导出文件';
            spStatus.style.color = '#c62828';
        }
    } catch (e) {
        spStatus.textContent = '状态：检查失败';
        spStatus.style.color = '#999';
    }
}

refreshSpStatus();
```

- [ ] **Step 3: Commit**

```bash
git add templates/index.html static/js/index.js
git commit -m "feat: add stockpile DB init and compare UI to A-side"
```

---

### Task 9: 最终集成与端到端验证

- [ ] **Step 1: 启动 Flask 服务，确认无导入错误**

```powershell
python server.py
```

预期：服务正常启动，无 import 错误。

- [ ] **Step 2: 通过浏览器/curl 验证核心流程**

**2a. 检查 stockpile 状态：**
```powershell
curl http://127.0.0.1:5000/stockpile/status
```
Expected: `{"initialized":false,"count":0,"ok":true}`

**2b. 上传系统导出文件初始化：**
创建测试 CSV：
```powershell
echo "product_barcode,product_model,stockpile_location" > test_stockpile.csv
echo "11111111,Model-A,A-01-01/X-01-01" >> test_stockpile.csv
echo "22222222,Model-B,B-02-02" >> test_stockpile.csv
```

用 curl 或浏览器上传后检查状态，预期 count=2。

**2c. 再次检查状态：**
```powershell
curl http://127.0.0.1:5000/stockpile/status
```
Expected: `{"initialized":true,"count":2,"ok":true}`

- [ ] **Step 3: 运行全部现有测试确保无回归**

```powershell
python -m pytest tests/ -v
```

如果 barcode_service 测试因 stockpile_db 调用失败，在 `tests/test_barcode_service.py` 的 `setUp` 中添加 mock：

```python
from unittest import mock
self.patch_db = mock.patch.object(barcode_service, "stockpile_db")
self.mock_db = self.patch_db.start()
```

在 `tearDown` 中添加：

```python
self.patch_db.stop()
```

- [ ] **Step 4: 修复所有失败的测试后 Commit**

```bash
git add -A
git commit -m "chore: fix tests for stockpile_db integration, verify end-to-end"
```

---

### Task 10: 清理与文档

- [ ] **Step 1: 清理不再需要的 stockpile CSV 上传逻辑**

确认 `storage_service.py` 中 `find_stockpile_file()` 和 `validate_stockpile_is_today()` 保留但不作为强制校验，旧的 CSV 路径仍可兼容。

- [ ] **Step 2: 确保 stockpile.db 已在 .gitignore 中**

```powershell
python -c "with open('.gitignore') as f: content = f.read(); assert 'stockpile.db' in content, 'MISSING'"
```

- [ ] **Step 3: 最终全量测试**

```powershell
python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: finalize stockpile_db integration, run full test suite"
```

