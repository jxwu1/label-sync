# 阶段 3：扫描历史浏览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在货号历史 tab 内加第 3 个二级 tab `📂 扫描批次`，浏览 `output/{员工}价格标{时间戳}/` 文件夹，提供"按员工×时间查询 + 重下载 CSV/xlsx"两大场景。

**Architecture:** 纯文件系统读取（无 DB 改动）。后端 service 扫描 `output/` 目录、解析文件夹名（regex 抽员工+时间戳）、聚合 CSV/xlsx 元信息；3 个 GET endpoint（list / download CSV / download xlsx，含 path traversal 防护）。前端 vanilla JS module 跟 history.js / index-recent-changes.js 同级，行内展开详情。

**Tech Stack:** Python 3.14 / Flask / pytest / vanilla JS module / 无前端构建。无 DB schema 改动、无 Alembic migration。

**Spec:** `docs/superpowers/specs/2026-04-29-scan-history-design.md`

**分支：** `feature/scan-history`（基于 main）

---

## File Structure

**新增**

- `scan_history_service.py` (~150 行) — 文件系统扫描 + 解析 + 聚合
- `routes_scan_history.py` (~50 行) — 3 个 GET endpoint
- `static/js/index-scan-history.js` (~150 行) — 前端 module，仿 index-recent-changes 风格
- `static/css/page-scan-history.css` (~80 行) — sub-tab 内的样式
- `tests/test_scan_history_service.py` (~180 行) — service 单测
- `tests/test_scan_history_routes.py` (~80 行) — routes 单测

**修改**

- `routes.py` — 注册 blueprint（约 +2 行）
- `templates/index.html` — 在 historyTabs / 二级 panel 区追加第 3 个 sub-tab（约 +20 行）
- `templates/index.html` — `<head>` 内追加新 CSS link 与新 JS module script
- `docs/verify-checklist.md` — 追加阶段 3 段
- `docs/superpowers/plans/2026-04-28-roadmap.md` — 阶段 3 完成时打勾

**不动**

- 现有 history.js / index-recent-changes.js / 其它 tab 模块
- DB schema / models / Alembic
- `output/` 目录本身

---

## Task 1: Branch setup + scaffold + folder name parser (TDD)

**Files:**
- Create: `scan_history_service.py`
- Create: `tests/test_scan_history_service.py`

- [ ] **Step 1: 切分支**

```bash
git checkout main
git pull
git checkout -b feature/scan-history
```

- [ ] **Step 2: 写第一条失败测试**

创建 `tests/test_scan_history_service.py`：

```python
"""scan_history_service 单测。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

import scan_history_service

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_scan_history"


class ScanHistoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch = mock.patch.object(scan_history_service, "OUTPUT_DIR", self.test_dir)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_batch(self, folder_name: str, csv_rows: int = 0, xlsx_files: list[str] | None = None) -> Path:
        """在 test_dir 下造一个 batch 目录。"""
        batch = self.test_dir / folder_name
        batch.mkdir()
        if csv_rows >= 0:
            csv = batch / "1产品信息导入模板.csv"
            lines = ["型号,唯一码"]  # header
            lines.extend(f"M{i},B{i}" for i in range(csv_rows))
            csv.write_text("\n".join(lines), encoding="utf-8-sig")
        for xlsx_name in xlsx_files or []:
            (batch / xlsx_name).write_bytes(b"FAKE XLSX CONTENT" * 10)
        return batch

    def test_parse_folder_name_extracts_employee_and_timestamp(self):
        result = scan_history_service._parse_folder_name("ALI价格标20260423155137")
        self.assertEqual(result, {"employee": "ALI", "timestamp": "20260423155137"})

    def test_parse_folder_name_returns_none_for_unrecognized(self):
        self.assertIsNone(scan_history_service._parse_folder_name("random_folder"))
        self.assertIsNone(scan_history_service._parse_folder_name("ALI价格标"))  # 缺时间戳
        self.assertIsNone(scan_history_service._parse_folder_name("价格标20260423155137"))  # 缺员工
```

- [ ] **Step 3: 跑测试确认 ImportError 失败**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：`ModuleNotFoundError: No module named 'scan_history_service'`

- [ ] **Step 4: 写最小实现**

创建 `scan_history_service.py`：

```python
"""扫描历史 service — 浏览 output/{员工}价格标{时间戳}/ 文件夹。

仅文件系统操作，不写 DB、不缓存（51 个 batch 的扫描 < 100ms）。
"""

import re
from pathlib import Path

from config import CONFIG

OUTPUT_DIR = CONFIG.output_dir

_FOLDER_PATTERN = re.compile(r"^(?P<employee>.+?)价格标(?P<timestamp>\d{14})$")


def _parse_folder_name(name: str) -> dict | None:
    """从文件夹名抽员工 + 14 位时间戳。不匹配返回 None。"""
    m = _FOLDER_PATTERN.match(name)
    if not m:
        return None
    return {"employee": m.group("employee"), "timestamp": m.group("timestamp")}
```

- [ ] **Step 5: 跑测试确认通过**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：2 passed。

- [ ] **Step 6: Commit**

```bash
git add scan_history_service.py tests/test_scan_history_service.py
git commit -m "feat(scan-history): 文件夹名解析 (员工 + 时间戳)"
```

---

## Task 2: `list_batches` — 排序 + 截断 + 跳过无效目录

**Files:**
- Modify: `scan_history_service.py`
- Modify: `tests/test_scan_history_service.py`

- [ ] **Step 1: 在 test 文件加新测试**

追加到 `tests/test_scan_history_service.py` 的 `ScanHistoryServiceTests` 类内：

```python
    def test_list_batches_returns_sorted_descending_by_timestamp(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=3)
        self._make_batch("ALI价格标20260425100000", csv_rows=5)
        self._make_batch("ABDUL价格标20260423100000", csv_rows=1)

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 3)
        self.assertEqual([b["batch_id"] for b in result], [
            "ALI价格标20260425100000",
            "ABDUL价格标20260423100000",
            "ALI价格标20260420100000",
        ])

    def test_list_batches_skips_unrecognized_folder_names(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1)
        (self.test_dir / "random_folder").mkdir()
        (self.test_dir / ".DS_Store").mkdir()  # 隐藏文件夹也忽略

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["batch_id"], "ALI价格标20260420100000")

    def test_list_batches_truncates_to_limit(self):
        for i in range(5):
            self._make_batch(f"ALI价格标2026042010{i:04d}0", csv_rows=1)

        result = scan_history_service.list_batches(limit=3)

        self.assertEqual(len(result), 3)

    def test_list_batches_returns_empty_when_output_dir_missing(self):
        # 删除整个 OUTPUT_DIR
        shutil.rmtree(self.test_dir, ignore_errors=True)
        result = scan_history_service.list_batches()
        self.assertEqual(result, [])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_scan_history_service.py::ScanHistoryServiceTests::test_list_batches_returns_sorted_descending_by_timestamp -v
```

期望：`AttributeError: module 'scan_history_service' has no attribute 'list_batches'`

- [ ] **Step 3: 加 `list_batches` 实现**

在 `scan_history_service.py` 末尾追加：

```python
def list_batches(limit: int = 100) -> list[dict]:
    """扫 OUTPUT_DIR，按时间倒序返回最近 limit 个 batch 概览。

    每条 dict 字段：
        batch_id, employee, scanned_at (ISO),
        csv_filename, csv_rows, csv_size_bytes,
        xlsx_files: [{name, size_bytes}]

    员工筛选由前端做（dropdown），服务端不过滤。
    """
    if not OUTPUT_DIR.exists():
        return []

    parsed = []
    for entry in OUTPUT_DIR.iterdir():
        if not entry.is_dir():
            continue
        info = _parse_folder_name(entry.name)
        if info is None:
            continue
        parsed.append((entry, info))

    # 按时间戳字符串倒序（同位数字符串可直接字典序）
    parsed.sort(key=lambda x: x[1]["timestamp"], reverse=True)
    parsed = parsed[:limit]

    return [_build_batch_dict(entry, info) for entry, info in parsed]


def _build_batch_dict(batch_dir: Path, info: dict) -> dict:
    """组装一条 batch 概览。CSV 缺失或不可读时 csv_* 字段为 None。"""
    return {
        "batch_id": batch_dir.name,
        "employee": info["employee"],
        "scanned_at": _format_timestamp(info["timestamp"]),
        "csv_filename": None,
        "csv_rows": None,
        "csv_size_bytes": None,
        "xlsx_files": [],
    }


def _format_timestamp(ts: str) -> str:
    """20260423155137 → 2026-04-23 15:51:37 (ISO-ish)."""
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
```

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：6 passed。

- [ ] **Step 5: Commit**

```bash
git add scan_history_service.py tests/test_scan_history_service.py
git commit -m "feat(scan-history): list_batches 排序+截断+跳过无效目录"
```

---

## Task 3: CSV/xlsx 元信息聚合（行数 / 大小 / 文件清单）

**Files:**
- Modify: `scan_history_service.py`
- Modify: `tests/test_scan_history_service.py`

- [ ] **Step 1: 加测试**

追加到测试类：

```python
    def test_list_batches_includes_csv_metadata(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=10)

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 1)
        b = result[0]
        self.assertEqual(b["csv_filename"], "1产品信息导入模板.csv")
        self.assertEqual(b["csv_rows"], 10)
        self.assertGreater(b["csv_size_bytes"], 0)

    def test_list_batches_includes_xlsx_files(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=2,
            xlsx_files=["ALI.xlsx", "ALI_2.xlsx"],
        )

        result = scan_history_service.list_batches()

        b = result[0]
        names = sorted(f["name"] for f in b["xlsx_files"])
        self.assertEqual(names, ["ALI.xlsx", "ALI_2.xlsx"])
        self.assertGreater(b["xlsx_files"][0]["size_bytes"], 0)

    def test_list_batches_handles_missing_csv(self):
        # 创建 batch 但不写 CSV
        batch = self.test_dir / "ALI价格标20260420100000"
        batch.mkdir()

        result = scan_history_service.list_batches()

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["csv_filename"])
        self.assertIsNone(result[0]["csv_rows"])

    def test_list_batches_handles_unreadable_csv(self):
        # CSV 存在但是是空文件 (0 行)
        batch = self.test_dir / "ALI价格标20260420100000"
        batch.mkdir()
        (batch / "1产品信息导入模板.csv").write_bytes(b"")

        result = scan_history_service.list_batches()

        # 空 CSV: rows = 0（不算 header），size = 0
        b = result[0]
        self.assertEqual(b["csv_rows"], 0)
        self.assertEqual(b["csv_size_bytes"], 0)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：4 个新 test FAIL（csv_filename 为 None；xlsx_files 为空），原 6 个 pass。

- [ ] **Step 3: 实现 `_build_batch_dict` 完整版**

替换 `_build_batch_dict` 函数：

```python
_CSV_FILENAME = "1产品信息导入模板.csv"


def _build_batch_dict(batch_dir: Path, info: dict) -> dict:
    """组装一条 batch 概览。CSV 缺失或不可读时 csv_* 字段为 None。"""
    csv_path = batch_dir / _CSV_FILENAME
    csv_filename: str | None = None
    csv_rows: int | None = None
    csv_size_bytes: int | None = None
    if csv_path.exists() and csv_path.is_file():
        csv_filename = _CSV_FILENAME
        try:
            csv_size_bytes = csv_path.stat().st_size
            csv_rows = _count_csv_rows(csv_path)
        except OSError:
            csv_size_bytes = None
            csv_rows = None

    xlsx_files: list[dict] = []
    for entry in batch_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".xlsx":
            try:
                xlsx_files.append({
                    "name": entry.name,
                    "size_bytes": entry.stat().st_size,
                })
            except OSError:
                continue
    xlsx_files.sort(key=lambda f: f["name"])

    return {
        "batch_id": batch_dir.name,
        "employee": info["employee"],
        "scanned_at": _format_timestamp(info["timestamp"]),
        "csv_filename": csv_filename,
        "csv_rows": csv_rows,
        "csv_size_bytes": csv_size_bytes,
        "xlsx_files": xlsx_files,
    }


def _count_csv_rows(csv_path: Path) -> int:
    """数 CSV 数据行（不含 header）。空文件返回 0。"""
    with csv_path.open("r", encoding="utf-8-sig") as f:
        line_count = sum(1 for _ in f)
    return max(0, line_count - 1)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：10 passed。

- [ ] **Step 5: Commit**

```bash
git add scan_history_service.py tests/test_scan_history_service.py
git commit -m "feat(scan-history): CSV/xlsx 元信息 (行数/大小/文件清单)"
```

---

## Task 4: `list_employees` — 抽 unique 员工名

**Files:**
- Modify: `scan_history_service.py`
- Modify: `tests/test_scan_history_service.py`

- [ ] **Step 1: 加测试**

```python
    def test_list_employees_returns_unique_sorted(self):
        self._make_batch("ALI价格标20260420100000")
        self._make_batch("ALI价格标20260425100000")
        self._make_batch("ABDUL价格标20260423100000")
        self._make_batch("ZHANG价格标20260424100000")

        result = scan_history_service.list_employees()

        self.assertEqual(result, ["ABDUL", "ALI", "ZHANG"])

    def test_list_employees_returns_empty_when_no_batches(self):
        result = scan_history_service.list_employees()
        self.assertEqual(result, [])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_scan_history_service.py::ScanHistoryServiceTests::test_list_employees_returns_unique_sorted -v
```

期望：`AttributeError: ... no attribute 'list_employees'`

- [ ] **Step 3: 加实现**

`scan_history_service.py` 末尾：

```python
def list_employees() -> list[str]:
    """从现有 batch 中抽出 unique 员工名，按字母序。"""
    if not OUTPUT_DIR.exists():
        return []
    seen = set()
    for entry in OUTPUT_DIR.iterdir():
        if not entry.is_dir():
            continue
        info = _parse_folder_name(entry.name)
        if info:
            seen.add(info["employee"])
    return sorted(seen)
```

- [ ] **Step 4: 跑测试通过**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：12 passed。

- [ ] **Step 5: Commit**

```bash
git add scan_history_service.py tests/test_scan_history_service.py
git commit -m "feat(scan-history): list_employees"
```

---

## Task 5: `get_batch_csv_path` + path traversal 防护

**Files:**
- Modify: `scan_history_service.py`
- Modify: `tests/test_scan_history_service.py`

- [ ] **Step 1: 加测试**

```python
    def test_get_batch_csv_path_returns_path_for_existing_batch(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=3)

        result = scan_history_service.get_batch_csv_path("ALI价格标20260420100000")

        self.assertIsNotNone(result)
        self.assertTrue(result.exists())
        self.assertEqual(result.name, "1产品信息导入模板.csv")

    def test_get_batch_csv_path_returns_none_for_missing_batch(self):
        result = scan_history_service.get_batch_csv_path("NOPE价格标20260420100000")
        self.assertIsNone(result)

    def test_get_batch_csv_path_returns_none_when_csv_missing(self):
        batch = self.test_dir / "ALI价格标20260420100000"
        batch.mkdir()  # 没 CSV
        result = scan_history_service.get_batch_csv_path("ALI价格标20260420100000")
        self.assertIsNone(result)

    def test_get_batch_csv_path_rejects_path_traversal(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1)

        # 各种 traversal 尝试
        self.assertIsNone(scan_history_service.get_batch_csv_path("../etc/passwd"))
        self.assertIsNone(scan_history_service.get_batch_csv_path("ALI价格标20260420100000/../"))
        self.assertIsNone(scan_history_service.get_batch_csv_path("/absolute/path"))

    def test_get_batch_csv_path_rejects_unrecognized_pattern(self):
        # 即使文件夹真存在但名字不匹配 _FOLDER_PATTERN，也拒绝
        (self.test_dir / "random_folder").mkdir()
        result = scan_history_service.get_batch_csv_path("random_folder")
        self.assertIsNone(result)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_scan_history_service.py -v -k get_batch_csv_path
```

期望：5 个 FAIL（函数不存在）。

- [ ] **Step 3: 加实现**

`scan_history_service.py` 末尾：

```python
def get_batch_csv_path(batch_id: str) -> Path | None:
    """返回 batch 内主 CSV 的 Path；不存在/不安全返回 None。"""
    batch_dir = _safe_resolve_batch(batch_id)
    if batch_dir is None:
        return None
    csv_path = batch_dir / _CSV_FILENAME
    if not csv_path.exists() or not csv_path.is_file():
        return None
    return csv_path


def _safe_resolve_batch(batch_id: str) -> Path | None:
    """把 batch_id 解析为绝对路径，确认在 OUTPUT_DIR 下且匹配命名规则。"""
    if _parse_folder_name(batch_id) is None:
        return None
    candidate = (OUTPUT_DIR / batch_id).resolve()
    try:
        # is_relative_to 在 Python 3.9+ 可用；3.10 后稳定
        if not candidate.is_relative_to(OUTPUT_DIR.resolve()):
            return None
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_dir():
        return None
    return candidate
```

- [ ] **Step 4: 跑测试通过**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：17 passed。

- [ ] **Step 5: Commit**

```bash
git add scan_history_service.py tests/test_scan_history_service.py
git commit -m "feat(scan-history): get_batch_csv_path + path traversal 防护"
```

---

## Task 6: `get_batch_xlsx_path` + filename 防护

**Files:**
- Modify: `scan_history_service.py`
- Modify: `tests/test_scan_history_service.py`

- [ ] **Step 1: 加测试**

```python
    def test_get_batch_xlsx_path_returns_path_for_existing_file(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=1,
            xlsx_files=["ALI.xlsx"],
        )

        result = scan_history_service.get_batch_xlsx_path(
            "ALI价格标20260420100000", "ALI.xlsx"
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.exists())

    def test_get_batch_xlsx_path_returns_none_for_missing_file(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1, xlsx_files=["ALI.xlsx"])

        result = scan_history_service.get_batch_xlsx_path(
            "ALI价格标20260420100000", "NOPE.xlsx"
        )
        self.assertIsNone(result)

    def test_get_batch_xlsx_path_rejects_path_traversal_in_filename(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1, xlsx_files=["ALI.xlsx"])

        # 路径穿越尝试
        for bad_name in ["../other.xlsx", "..\\other.xlsx", "/etc/passwd", "subdir/foo.xlsx"]:
            self.assertIsNone(
                scan_history_service.get_batch_xlsx_path(
                    "ALI价格标20260420100000", bad_name
                ),
                f"should reject {bad_name!r}",
            )

    def test_get_batch_xlsx_path_only_serves_xlsx_extension(self):
        batch = self._make_batch("ALI价格标20260420100000", csv_rows=1)
        # 同 batch 内放一个非 xlsx 文件
        (batch / "secret.txt").write_text("nope")

        result = scan_history_service.get_batch_xlsx_path(
            "ALI价格标20260420100000", "secret.txt"
        )
        self.assertIsNone(result)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_scan_history_service.py -v -k get_batch_xlsx
```

期望：4 FAIL（函数不存在）。

- [ ] **Step 3: 加实现**

`scan_history_service.py` 末尾：

```python
def get_batch_xlsx_path(batch_id: str, filename: str) -> Path | None:
    """返回指定 xlsx 文件 Path；越界/不存在/非 xlsx 后缀返回 None。"""
    batch_dir = _safe_resolve_batch(batch_id)
    if batch_dir is None:
        return None

    # 拒绝任何路径分隔符或父目录引用
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    if not filename.lower().endswith(".xlsx"):
        return None

    candidate = (batch_dir / filename).resolve()
    try:
        if not candidate.is_relative_to(batch_dir):
            return None
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate
```

- [ ] **Step 4: 跑测试通过**

```bash
python -m pytest tests/test_scan_history_service.py -v
```

期望：21 passed。

- [ ] **Step 5: Commit**

```bash
git add scan_history_service.py tests/test_scan_history_service.py
git commit -m "feat(scan-history): get_batch_xlsx_path + filename 防护"
```

---

## Task 7: Routes blueprint + 注册

**Files:**
- Create: `routes_scan_history.py`
- Create: `tests/test_scan_history_routes.py`
- Modify: `routes.py`

- [ ] **Step 1: 写 routes 测试**

创建 `tests/test_scan_history_routes.py`：

```python
"""routes_scan_history 单测。"""

import io
import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import scan_history_service
from routes_scan_history import bp

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_scan_history_routes"


class ScanHistoryRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.patch = mock.patch.object(scan_history_service, "OUTPUT_DIR", self.test_dir)
        self.patch.start()
        self.addCleanup(self.patch.stop)

        app = Flask(__name__)
        app.register_blueprint(bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_batch(self, folder_name: str, csv_rows: int = 0, xlsx_files: list[str] | None = None) -> Path:
        batch = self.test_dir / folder_name
        batch.mkdir()
        if csv_rows >= 0:
            csv = batch / "1产品信息导入模板.csv"
            lines = ["型号,唯一码"]
            lines.extend(f"M{i},B{i}" for i in range(csv_rows))
            csv.write_text("\n".join(lines), encoding="utf-8-sig")
        for x in xlsx_files or []:
            (batch / x).write_bytes(b"FAKE" * 100)
        return batch

    def test_batches_endpoint_returns_list_and_employees(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=3, xlsx_files=["ALI.xlsx"])
        self._make_batch("ABDUL价格标20260421100000", csv_rows=5)

        resp = self.client.get("/scan_history/batches")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(sorted(data["employees"]), ["ABDUL", "ALI"])
        self.assertEqual(len(data["batches"]), 2)
        # 时间倒序：ABDUL 4-21 在前
        self.assertEqual(data["batches"][0]["employee"], "ABDUL")

    def test_download_csv_returns_file(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=2)

        resp = self.client.get("/scan_history/batches/ALI价格标20260420100000/download/csv")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("型号,唯一码", resp.data.decode("utf-8-sig"))
        # 以 attachment 下载（文件名在 Content-Disposition 里）
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))

    def test_download_csv_returns_404_for_missing_batch(self):
        resp = self.client.get("/scan_history/batches/NOPE价格标20260420100000/download/csv")
        self.assertEqual(resp.status_code, 404)

    def test_download_csv_returns_404_for_path_traversal(self):
        self._make_batch("ALI价格标20260420100000", csv_rows=1)
        # URL 中尝试穿越（注：werkzeug 会先 normalize URL 路径，所以纯 ../ 命中 routing 层而非 endpoint）
        # 这里测试一个语法上合法但语义上恶意的 batch_id
        resp = self.client.get("/scan_history/batches/random_unrelated/download/csv")
        self.assertEqual(resp.status_code, 404)

    def test_download_xlsx_returns_file(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=1,
            xlsx_files=["ALI.xlsx"],
        )

        resp = self.client.get(
            "/scan_history/batches/ALI价格标20260420100000/files/ALI.xlsx"
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))

    def test_download_xlsx_returns_404_for_path_traversal_filename(self):
        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=1,
            xlsx_files=["ALI.xlsx"],
        )

        # filename 含 .. 应当 404
        resp = self.client.get(
            "/scan_history/batches/ALI价格标20260420100000/files/..%2Fevil.xlsx"
        )
        self.assertEqual(resp.status_code, 404)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_scan_history_routes.py -v
```

期望：`ImportError: cannot import name 'bp' from 'routes_scan_history'`

- [ ] **Step 3: 写 routes 实现**

创建 `routes_scan_history.py`：

```python
"""扫描历史浏览 endpoints。"""

from flask import Blueprint, abort, jsonify, send_file

import scan_history_service

bp = Blueprint("scan_history", __name__, url_prefix="/scan_history")


@bp.get("/batches")
def list_batches():
    """返回最近 100 个 batch 概览 + 全部员工列表。"""
    batches = scan_history_service.list_batches()
    employees = scan_history_service.list_employees()
    return jsonify({"ok": True, "employees": employees, "batches": batches})


@bp.get("/batches/<path:batch_id>/download/csv")
def download_csv(batch_id: str):
    """重下载 batch 内主 CSV。"""
    csv_path = scan_history_service.get_batch_csv_path(batch_id)
    if csv_path is None:
        abort(404)
    return send_file(
        csv_path,
        as_attachment=True,
        download_name=csv_path.name,
        mimetype="text/csv",
    )


@bp.get("/batches/<path:batch_id>/files/<filename>")
def download_xlsx(batch_id: str, filename: str):
    """下载 batch 内某个 xlsx 文件。"""
    xlsx_path = scan_history_service.get_batch_xlsx_path(batch_id, filename)
    if xlsx_path is None:
        abort(404)
    return send_file(
        xlsx_path,
        as_attachment=True,
        download_name=xlsx_path.name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
```

- [ ] **Step 4: 注册 blueprint**

修改 `routes.py`，按字母序在合适位置插入：

```python
from routes_scan_history import bp as scan_history_bp
```

到 import 列表（约第 10 行附近，在 `routes_recent_changes` 之后）。

`register_routes` 函数内追加：

```python
    app.register_blueprint(scan_history_bp)
```

放在 `app.register_blueprint(stockpile_bp)` 之前（与 import 顺序对齐）。

- [ ] **Step 5: 跑测试通过**

```bash
python -m pytest tests/test_scan_history_routes.py -v
python -m pytest -q
```

期望：6 个新 routes 测试 + 21 个 service 测试 + 旧 253 个 = 280 passed。

- [ ] **Step 6: Commit**

```bash
git add scan_history_service.py routes_scan_history.py tests/test_scan_history_routes.py routes.py
git commit -m "feat(scan-history): 3 个 GET endpoint + blueprint 注册"
```

---

## Task 8: 前端模板：第 3 个 sub-tab + CSS

**Files:**
- Create: `static/css/page-scan-history.css`
- Modify: `templates/index.html`

- [ ] **Step 1: 写 CSS 文件**

创建 `static/css/page-scan-history.css`：

```css
/* ========== 扫描批次 sub-tab ========== */

.sh-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--c-text-muted);
}

.sh-bar select {
  padding: 6px 10px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background: var(--c-surface);
  color: var(--c-text);
  font-family: inherit;
  font-size: var(--fs-md);
  cursor: pointer;
}

#scanHistoryList {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.sh-row {
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background: var(--c-surface-elev);
  overflow: hidden;
  transition: border-color var(--t-fast);
}

.sh-row:hover {
  border-color: var(--c-accent);
}

.sh-row__head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
}

.sh-row__time {
  font-family: var(--ff-mono);
  font-size: var(--fs-sm);
  color: var(--c-text-muted);
  min-width: 160px;
}

.sh-row__employee {
  font-weight: 600;
  min-width: 80px;
}

.sh-row__meta {
  font-size: var(--fs-sm);
  color: var(--c-text-muted);
  flex: 1;
}

.sh-row__chevron {
  font-size: var(--fs-md);
  color: var(--c-text-muted);
  transition: transform var(--t-fast);
}

.sh-row.is-open .sh-row__chevron {
  transform: rotate(90deg);
}

.sh-row__detail {
  display: none;
  padding: 8px 14px 14px 14px;
  border-top: 1px solid var(--c-border);
  background: var(--c-surface);
}

.sh-row.is-open .sh-row__detail {
  display: block;
}

.sh-file {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 6px 0;
  font-size: var(--fs-sm);
}

.sh-file__icon {
  width: 20px;
  text-align: center;
}

.sh-file__name {
  flex: 1;
  font-family: var(--ff-mono);
}

.sh-file__size {
  color: var(--c-text-muted);
  min-width: 80px;
  text-align: right;
}

.sh-empty {
  padding: 20px;
  text-align: center;
  color: var(--c-text-muted);
  font-size: var(--fs-sm);
}
```

- [ ] **Step 2: 模板加 CSS link**

在 `templates/index.html` 的 `<head>` 中（参考 `page-history.css` 的 link 行附近，约第 15 行）追加：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-scan-history.css') }}">
```

- [ ] **Step 3: 模板加第 3 个 sub-tab 按钮**

找到 `<div class="tabs" id="historyTabs">`（约第 137 行），在两个按钮后追加第 3 个：

```html
<div class="tabs" id="historyTabs">
  <button class="tabs__tab active" data-history-tab="search" type="button">🔎 货号查询</button>
  <button class="tabs__tab" data-history-tab="recent" type="button">📊 最近改动</button>
  <button class="tabs__tab" data-history-tab="scan" type="button">📂 扫描批次</button>
</div>
```

- [ ] **Step 4: 模板加第 3 个 sub-tab panel**

找到 `<div class="tabs__panel" data-history-tab-panel="recent">` 那块的结束 `</div>`（约第 195 行附近，紧挨着 `</div>` 关闭 pageHistory），在它之后插入：

```html
<div class="tabs__panel" data-history-tab-panel="scan">
  <div class="panel">
    <div class="panel-hd">
      扫描批次
      <div class="sh-bar" style="margin-left:auto;">
        <select id="scanHistoryEmployee">
          <option value="">全部员工</option>
        </select>
        <span>显示最近 100 条</span>
      </div>
    </div>
    <div class="panel-bd" id="scanHistoryList">
      <div class="sh-empty">加载中...</div>
    </div>
  </div>
</div>
```

- [ ] **Step 5: 模板加 JS module 引用**

找到 `<script type="module" src=".../index-recent-changes.js">` 那行（约第 318 行），紧跟其后追加：

```html
<script type="module" src="{{ url_for('static', filename='js/index-scan-history.js') }}"></script>
```

- [ ] **Step 6: pytest sanity（仅验证模板未坏）**

```bash
python -m pytest -q
```

期望：280 passed（不应回归）。

- [ ] **Step 7: 浏览器手测加载**

启动 Flask，浏览器打开首页 → 切到货号历史 tab → 应看到 3 个 sub-tab 按钮（含"📂 扫描批次"），点第 3 个切到 panel，显示"加载中..."（JS 还没写，所以静态显示）。

- [ ] **Step 8: Commit**

```bash
git add static/css/page-scan-history.css templates/index.html
git commit -m "feat(scan-history): 模板加第 3 个 sub-tab + CSS"
```

---

## Task 9: 前端模块 `index-scan-history.js`

**Files:**
- Create: `static/js/index-scan-history.js`

- [ ] **Step 1: 写完整 module**

创建 `static/js/index-scan-history.js`：

```js
// 货号历史 - 扫描批次 module
"use strict";

const $ = (id) => document.getElementById(id);

let _allBatches = [];
let _isInitialized = false;

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function formatBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

async function fetchJson(url) {
  const resp = await fetch(url);
  const data = await resp.json();
  if (!data.ok) throw new Error(data.msg || "未知错误");
  return data;
}

function setupTabHook() {
  // 复用 history sub-tab 切换；进入 scan tab 时初始化一次
  document.querySelectorAll('#historyTabs [data-history-tab="scan"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!_isInitialized) {
        loadBatches();
        _isInitialized = true;
      }
    });
  });
}

async function loadBatches() {
  const list = $("scanHistoryList");
  list.innerHTML = '<div class="sh-empty">加载中...</div>';
  try {
    const data = await fetchJson("/scan_history/batches");
    _allBatches = data.batches;
    renderEmployeeOptions(data.employees);
    renderList();
  } catch (err) {
    list.innerHTML = `<div class="sh-empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

function renderEmployeeOptions(employees) {
  const sel = $("scanHistoryEmployee");
  // 保留首项"全部员工"，重建其余
  while (sel.options.length > 1) sel.remove(1);
  employees.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  sel.addEventListener("change", renderList);
}

function renderList() {
  const list = $("scanHistoryList");
  const filter = $("scanHistoryEmployee").value;
  const filtered = filter ? _allBatches.filter((b) => b.employee === filter) : _allBatches;

  if (filtered.length === 0) {
    list.innerHTML = '<div class="sh-empty">暂无批次</div>';
    return;
  }

  list.innerHTML = filtered.map(renderRow).join("");
  attachRowToggleHandlers();
}

function renderRow(b) {
  const csvLine = b.csv_filename
    ? `<div class="sh-file">
         <span class="sh-file__icon">📄</span>
         <span class="sh-file__name">${escapeHtml(b.csv_filename)}</span>
         <span class="sh-file__size">${b.csv_rows} 行 · ${formatBytes(b.csv_size_bytes)}</span>
         <a class="pur-btn-dl" href="/scan_history/batches/${encodeURIComponent(b.batch_id)}/download/csv">下载</a>
       </div>`
    : `<div class="sh-file"><span class="sh-file__icon">📄</span><span class="sh-file__name" style="color:var(--c-text-muted);">CSV 缺失</span></div>`;

  const xlsxLines = (b.xlsx_files || []).map((f) =>
    `<div class="sh-file">
       <span class="sh-file__icon">📊</span>
       <span class="sh-file__name">${escapeHtml(f.name)}</span>
       <span class="sh-file__size">${formatBytes(f.size_bytes)}</span>
       <a class="pur-btn-dl" href="/scan_history/batches/${encodeURIComponent(b.batch_id)}/files/${encodeURIComponent(f.name)}">下载</a>
     </div>`
  ).join("");

  const csvSummary = b.csv_rows !== null ? `${b.csv_rows} 行` : "无 CSV";
  const xlsxCount = (b.xlsx_files || []).length;
  const xlsxSummary = xlsxCount > 0 ? `${xlsxCount} 个 xlsx` : "";
  const meta = [csvSummary, xlsxSummary].filter(Boolean).join(" · ");

  return `
    <div class="sh-row" data-batch-id="${escapeHtml(b.batch_id)}">
      <div class="sh-row__head">
        <span class="sh-row__time">${escapeHtml(b.scanned_at)}</span>
        <span class="sh-row__employee">${escapeHtml(b.employee)}</span>
        <span class="sh-row__meta">${escapeHtml(meta)}</span>
        <span class="sh-row__chevron">▶</span>
      </div>
      <div class="sh-row__detail">
        ${csvLine}
        ${xlsxLines}
      </div>
    </div>
  `;
}

function attachRowToggleHandlers() {
  document.querySelectorAll("#scanHistoryList .sh-row__head").forEach((head) => {
    head.addEventListener("click", () => {
      head.parentElement.classList.toggle("is-open");
    });
  });
}

setupTabHook();
```

- [ ] **Step 2: 浏览器手测**

启动 Flask（已开就刷新 Ctrl+F5），打开首页 → 货号历史 → 点"📂 扫描批次"：

- 列表加载（最近最多 100 条）
- 员工 dropdown 填好（全部 + 实际员工名）
- 选某员工后列表过滤
- 点击某行 → 详情展开
- 点 CSV 下载链接 → 拿到原文件
- 点 xlsx 下载链接 → 拿到原文件

- [ ] **Step 3: pytest sanity**

```bash
python -m pytest -q
```

期望：280 passed。

- [ ] **Step 4: Commit**

```bash
git add static/js/index-scan-history.js
git commit -m "feat(scan-history): 前端 module (列表/筛选/展开/下载)"
```

---

## Task 10: verify checklist + roadmap + 收尾

**Files:**
- Modify: `docs/verify-checklist.md`
- Modify: `docs/superpowers/plans/2026-04-28-roadmap.md`

- [ ] **Step 1: 加 verify-checklist 段**

打开 `docs/verify-checklist.md`，在文件末尾追加：

```markdown

## 阶段 3: feature/scan-history
- [ ] 货号历史 tab 内出现 3 个二级 tab；点 📂 扫描批次切到列表
- [ ] 列表显示最近 N 条批次（按时间倒序）
- [ ] 员工 dropdown 含"全部"+ 实际扫描过的员工名
- [ ] 选员工后列表只剩该员工的批次
- [ ] 点击行展开 → 显示 CSV + xlsx 文件清单 + 下载按钮
- [ ] 点击 CSV 下载链接 → 浏览器拿到原始 CSV 文件，文件名正确
- [ ] 点击 xlsx 下载链接 → 拿到原始 xlsx 文件
- [ ] 控制台 0 console error
```

- [ ] **Step 2: 跑完整 verify-checklist 阶段 3 段**

启动 Flask，按上面 8 项一项项点过去。每过一项打勾。

- [ ] **Step 3: 加 verify 通过结果**

verify 全过后，在阶段 3 段末尾加：

```markdown

**阶段 3 验证结果**：[YYYY-MM-DD] 全部通过 by [user]
```

- [ ] **Step 4: 更新 roadmap**

打开 `docs/superpowers/plans/2026-04-28-roadmap.md`，找到"阶段 3：第 2 期 扫描历史"段，把 4 个 `- [ ]` 改成 `- [x]`，并在段末追加：

```markdown

**实施备忘**（YYYY-MM-DD 完成）：

1. 单 PR `feature/scan-history`，10 task
2. 纯文件系统读取，零 schema 改动
3. 3 个 GET endpoint：list / download CSV / download xlsx
4. 前端 vanilla JS module（沿用 history.js / index-recent-changes.js 风格，不上 Alpine 内部）
5. 路径穿越防护：所有用户传入的 batch_id / filename 经过 `_safe_resolve_batch` + suffix 校验
6. spec: docs/superpowers/specs/2026-04-29-scan-history-design.md
7. plan: docs/superpowers/plans/2026-04-29-scan-history.md

**未做（YAGNI 后续登记）**：

- DB 变更 → 源头扫描反查（用户出现具体调查需求时再加）
- CSV web 内浏览（用户反馈"每次下载太麻烦"时再加）
- 员工产出统计/图表（阶段 5 候选）
- filesystem 扫描结果缓存（batch 数 > 1000 时）
- 日期范围筛选（用户反馈需要时）
```

- [ ] **Step 5: pytest 最终全套**

```bash
python -m pytest -q
```

期望：280 passed。

- [ ] **Step 6: Commit + push**

```bash
git add docs/verify-checklist.md docs/superpowers/plans/2026-04-28-roadmap.md
git commit -m "docs: 阶段 3 verify 全过 + roadmap 打勾 + 实施备忘"
git push -u origin feature/scan-history
```

- [ ] **Step 7: 合并 main（用户授权后）**

```bash
git checkout main
git merge --no-ff feature/scan-history -m "Merge branch 'feature/scan-history': 阶段 3 扫描历史浏览"
git push origin main
```

---

## 执行顺序总览

```
Task 1  分支 + 文件夹名解析 (TDD)
Task 2  list_batches: 排序+截断
Task 3  CSV/xlsx 元信息聚合
Task 4  list_employees
Task 5  get_batch_csv_path + 路径防护
Task 6  get_batch_xlsx_path + filename 防护
Task 7  Routes blueprint + 注册
Task 8  模板加第 3 sub-tab + CSS
Task 9  前端 module
Task 10 verify + roadmap + push + merge
```

**预计**：service+routes 1 天 / 前端 0.5 天 / 集成手测 0.5 天 / 合计约 2 工作日（与 spec §8 一致）。

---

## 失败兜底

- 任何 task 测试不通过：本 task 内 revert + 重做，不要跨 task 累积修复
- service 单测全过但前端 fetch 报错：先看 routes blueprint 是否真注册（Task 7 Step 4 漏了？）
- 前端 dropdown 不显示员工名：检查 `/scan_history/batches` JSON 响应里 `employees` 字段是否非空

## 偏离 spec 时

如执行中发现 spec 决策需要调整，**停下来**回 spec 改决策再继续；不要在 plan 执行中静默偏离。改决策记录追加到 spec §9 决策日志。
