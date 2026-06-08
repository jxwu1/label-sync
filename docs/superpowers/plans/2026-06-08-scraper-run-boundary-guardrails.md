# scraper 周任务护栏 + staging 自清 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 阻断 scraper 周任务静默重传历史文件——遇历史响亮 abort（不打 heartbeat → 红条告警），并让 staging 上传后自清不再累积。

**Architecture:** 新增纯函数模块 `scraper/scrape_window.py`（文件名→日期判断单源 + `--check` CLI）。两层护栏复用它：第一层 `sanitize.py` 批量模式拒绝产出历史文件；第二层 `run_weekly.ps1` 上传前调 `scrape_window --check` manifest 闸、上传成功后把 staging 目标文件挪进 `uploaded/<ts>/staging/` 自清。

**Tech Stack:** Python 3.12（stdlib `datetime`/`re`/`argparse` + pandas/pyarrow 仅测试造 parquet）、pytest、PowerShell（run_weekly.ps1）。

**Spec:** `docs/superpowers/specs/2026-06-08-scraper-run-boundary-guardrails-design.md`

---

## File Structure

- **Create** `scraper/scrape_window.py` — 纯函数 `parse_window` / `weekly_violation` + `run_check` + `main()` CLI。日期判断单一真源。
- **Create** `tests/test_scrape_window.py` — 纯函数 + CLI 单测（固定 `today`，不依赖系统时钟）。
- **Modify** `scraper/sanitize.py` — batch 模式加 `weekly_violation` 闸 + `--allow-backfill` flag；复用 scrape_window（双路 import）。
- **Modify** `tests/test_scraper_sanitize.py` — 加 sanitize 闸的 subprocess 集成测试。
- **Modify** `scraper/run_weekly.ps1` — 上传前 manifest 闸 + 上传成功后 staging 自清。
- **一次性 ops** — 归档 `staging/`+`sanitized/` 现存目标文件到 `staging_archive/`（用 glob，不 hardcode 名单）。

---

## Task 1: scrape_window 纯函数 parse_window + weekly_violation

**Files:**
- Create: `scraper/scrape_window.py`
- Test: `tests/test_scrape_window.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_scrape_window.py
"""scraper/scrape_window.py 单元测试 (固定 today, 不依赖系统时钟)."""

from __future__ import annotations

from datetime import date

from scraper.scrape_window import parse_window, weekly_violation

TODAY = date(2026, 6, 8)


class TestParseWindow:
    def test_events_ok(self):
        assert parse_window("events_sale_2026-06-01_2026-06-08.parquet") == (
            "events",
            date(2026, 6, 1),
            date(2026, 6, 8),
        )

    def test_events_purchase_ok(self):
        kind, s, e = parse_window("events_purchase_2020-01-01_2023-12-31.parquet")
        assert kind == "events"
        assert s == date(2020, 1, 1)
        assert e == date(2023, 12, 31)

    def test_snapshot_ok(self):
        assert parse_window("inventory_snapshot_2026-06-08.parquet") == (
            "snapshot",
            date(2026, 6, 8),
            date(2026, 6, 8),
        )

    def test_master_ok(self):
        assert parse_window("product_master_2026-06-08.parquet") == (
            "master",
            date(2026, 6, 8),
            date(2026, 6, 8),
        )

    def test_events_bad_date_keeps_kind_none_dates(self):
        # 匹配前缀但日期坏 → kind 仍是 events, 日期 None (区分坏命名目标 vs 无关文件)
        assert parse_window("events_sale_xx_yy.parquet") == ("events", None, None)

    def test_events_invalid_calendar_date(self):
        assert parse_window("events_sale_2026-13-99_2026-06-08.parquet") == (
            "events",
            None,
            None,
        )

    def test_unrelated_file_is_unknown(self):
        assert parse_window("README.md") == ("unknown", None, None)
        assert parse_window("foo.parquet") == ("unknown", None, None)


class TestWeeklyViolation:
    def test_current_week_events_ok(self):
        assert (
            weekly_violation("events_sale_2026-06-01_2026-06-08.parquet", TODAY) is None
        )

    def test_span_too_wide_rejected(self):
        reason = weekly_violation(
            "events_sale_2015-01-01_2023-01-02.parquet", TODAY
        )
        assert reason is not None
        assert "跨度" in reason

    def test_old_start_short_span_rejected(self):
        # 短跨度但起始太旧 (2026-05-01→2026-05-08, start < today-14=2026-05-25)
        reason = weekly_violation(
            "events_sale_2026-05-01_2026-05-08.parquet", TODAY
        )
        assert reason is not None
        assert "太旧" in reason

    def test_stale_snapshot_rejected(self):
        reason = weekly_violation("inventory_snapshot_2023-01-02.parquet", TODAY)
        assert reason is not None

    def test_current_snapshot_ok(self):
        assert weekly_violation("inventory_snapshot_2026-06-08.parquet", TODAY) is None

    def test_master_any_date_ok(self):
        assert weekly_violation("product_master_2026-06-08.parquet", TODAY) is None
        assert weekly_violation("product_master_2020-01-01.parquet", TODAY) is None

    def test_bad_named_target_rejected(self):
        # events 前缀但日期坏 → 违规 (防绕过)
        reason = weekly_violation("events_sale_xx_yy.parquet", TODAY)
        assert reason is not None
        assert "解析" in reason

    def test_unrelated_file_passes(self):
        assert weekly_violation("README.md", TODAY) is None

    def test_boundary_span_exactly_14_ok(self):
        # span == 14 放行 (> 才拒); start 2026-05-25 == today-14 也放行 (< 才拒)
        assert (
            weekly_violation("events_sale_2026-05-25_2026-06-08.parquet", TODAY)
            is None
        )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_scrape_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.scrape_window'`

- [ ] **Step 3: 写最小实现（纯函数部分）**

```python
# scraper/scrape_window.py
"""scraper 文件名 → 抓取窗口判断 (单一真源).

两层护栏复用:
  - sanitize.py 第一层: weekly_violation 命中且无 --allow-backfill → 拒绝产出
  - run_weekly.ps1 第二层: scrape_window.py --check <dir> manifest 闸

纯函数 weekly_violation 接 today 参数 (测试传固定日期, 不依赖系统时钟).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

_DATE = r"\d{4}-\d{2}-\d{2}"
_EVENTS_RE = re.compile(rf"^events_[a-z]+_({_DATE})_({_DATE})\.")
_SNAPSHOT_RE = re.compile(rf"^inventory_snapshot_({_DATE})\.")
_MASTER_RE = re.compile(rf"^product_master_({_DATE})\.")


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_window(filename: str) -> tuple[str, date | None, date | None]:
    """(kind, start, end). kind 由前缀决定, 不是解析成功与否.

    匹配目标前缀但日期坏 → kind 保持前缀、日期 None (区分坏命名目标 vs 无关文件).
    """
    name = Path(filename).name
    if name.startswith("events_"):
        m = _EVENTS_RE.match(name)
        if m:
            return ("events", _parse_date(m.group(1)), _parse_date(m.group(2)))
        return ("events", None, None)
    if name.startswith("inventory_snapshot_"):
        m = _SNAPSHOT_RE.match(name)
        if m:
            d = _parse_date(m.group(1))
            return ("snapshot", d, d)
        return ("snapshot", None, None)
    if name.startswith("product_master_"):
        m = _MASTER_RE.match(name)
        if m:
            d = _parse_date(m.group(1))
            return ("master", d, d)
        return ("master", None, None)
    return ("unknown", None, None)


def weekly_violation(
    filename: str,
    today: date,
    max_span_days: int = 14,
    max_age_days: int = 14,
) -> str | None:
    """周任务护栏: 返回违规原因字符串, 合规返回 None.

    span > max_span_days 才拒 (== 放行); start < today-max_age_days 才拒 (== 放行).
    """
    name = Path(filename).name
    kind, start, end = parse_window(name)
    if kind == "unknown":
        return None
    if kind == "master":
        if start is None:
            return f"日期解析失败: {name}"
        return None
    if kind == "snapshot":
        if start is None:
            return f"日期解析失败: {name}"
        if start < today - timedelta(days=max_age_days):
            return f"陈旧快照 {start} (早于 {today}-{max_age_days}天)"
        return None
    # events
    if start is None or end is None:
        return f"日期解析失败: {name}"
    span = (end - start).days
    if span > max_span_days:
        return f"日期跨度 {span} 天 > {max_span_days} ({start}→{end})"
    if start < today - timedelta(days=max_age_days):
        return f"起始日 {start} 太旧 (早于 {today}-{max_age_days}天)"
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_scrape_window.py -v`
Expected: PASS（全部用例）

- [ ] **Step 5: 提交**

```bash
git add scraper/scrape_window.py tests/test_scrape_window.py
git commit -m "feat(scraper): scrape_window 纯函数 parse_window+weekly_violation (TDD)"
```

---

## Task 2: scrape_window CLI --check（manifest 闸）

**Files:**
- Modify: `scraper/scrape_window.py`（加 `run_check` + `main`）
- Test: `tests/test_scrape_window.py`（加 CLI 类）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_scrape_window.py 末尾追加

import pandas as pd

from scraper.scrape_window import run_check


def _write_parquet(path, n=10):
    # 造一个最小合法 parquet (内容无所谓, 护栏只看文件名)
    pd.DataFrame({"x": list(range(n))}).to_parquet(path, index=False)


class TestRunCheck:
    def test_all_compliant_returns_0(self, tmp_path):
        _write_parquet(tmp_path / "events_sale_2026-06-01_2026-06-08.parquet")
        _write_parquet(tmp_path / "inventory_snapshot_2026-06-08.parquet")
        rc = run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=False)
        assert rc == 0

    def test_historical_file_returns_1(self, tmp_path, capsys):
        _write_parquet(tmp_path / "events_sale_2015-01-01_2023-01-02.parquet")
        rc = run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=False)
        assert rc == 1
        out = capsys.readouterr().out
        assert "events_sale_2015-01-01_2023-01-02.parquet" in out

    def test_allow_backfill_passes_history(self, tmp_path):
        _write_parquet(tmp_path / "events_sale_2015-01-01_2023-01-02.parquet")
        rc = run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=True)
        assert rc == 0

    def test_total_size_over_limit_returns_1(self, tmp_path):
        _write_parquet(tmp_path / "events_sale_2026-06-01_2026-06-08.parquet")
        # 阈值设极小逼出大小闸
        rc = run_check(str(tmp_path), TODAY, max_total_mb=0.0001, allow_backfill=False)
        assert rc == 1

    def test_manifest_lists_master_by_kind(self, tmp_path, capsys):
        _write_parquet(tmp_path / "product_master_2026-06-08.parquet")
        run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=False)
        out = capsys.readouterr().out
        assert "[master]" in out
        assert "product_master_2026-06-08.parquet" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_scrape_window.py::TestRunCheck -v`
Expected: FAIL — `ImportError: cannot import name 'run_check'`

- [ ] **Step 3: 写最小实现（CLI 部分，追加到 scrape_window.py）**

```python
# scraper/scrape_window.py 末尾追加

import argparse
import sys

_GLOBS = (
    "events_*.parquet",
    "inventory_snapshot_*.parquet",
    "product_master_*.parquet",
)


def _iter_target_files(directory: str) -> list[Path]:
    p = Path(directory)
    found: list[Path] = []
    for pattern in _GLOBS:
        found.extend(p.glob(pattern))
    return sorted(set(found))


def run_check(
    directory: str,
    today: date,
    max_total_mb: float = 50.0,
    allow_backfill: bool = False,
) -> int:
    """扫描 directory 下目标文件, 打印 manifest (按 kind), 违规/超量返回 1."""
    files = _iter_target_files(directory)
    print(f"manifest: {directory} ({len(files)} 个目标文件)")
    total = 0
    for f in files:
        kind, _, _ = parse_window(f.name)
        size = f.stat().st_size
        total += size
        print(f"  [{kind}] {f.name}  ({size / 1024 / 1024:.2f} MB)")
    total_mb = total / 1024 / 1024
    print(f"  总大小: {total_mb:.2f} MB")

    if allow_backfill:
        print("✅ --allow-backfill: 跳过历史/大小闸")
        return 0

    failed: list[str] = []
    for f in files:
        reason = weekly_violation(f.name, today)
        if reason:
            failed.append(f"{f.name}: {reason}")
    if total_mb > max_total_mb:
        failed.append(f"<total>: 总大小 {total_mb:.1f}MB > {max_total_mb}MB")

    if failed:
        print("❌ manifest 闸拦截:")
        for line in failed:
            print(f"  - {line}")
        return 1
    print("✅ manifest 闸通过")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="scrape_window manifest 闸: 扫描目录, 历史/超量文件 → 退出码 1",
    )
    parser.add_argument("--check", metavar="DIR", required=True, help="待检查目录")
    parser.add_argument("--max-total-mb", type=float, default=50.0)
    parser.add_argument("--allow-backfill", action="store_true")
    args = parser.parse_args(argv)
    return run_check(
        args.check, date.today(), args.max_total_mb, args.allow_backfill
    )


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_scrape_window.py -v`
Expected: PASS（含 TestRunCheck 全部）

- [ ] **Step 5: 提交**

```bash
git add scraper/scrape_window.py tests/test_scrape_window.py
git commit -m "feat(scraper): scrape_window --check manifest 闸 CLI (TDD)"
```

---

## Task 3: sanitize.py 第一层闸 + --allow-backfill

**Files:**
- Modify: `scraper/sanitize.py`
- Test: `tests/test_scraper_sanitize.py`

- [ ] **Step 1: 写失败测试（subprocess 集成）**

```python
# tests/test_scraper_sanitize.py 末尾追加

import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SANITIZE = _REPO_ROOT / "scraper" / "sanitize.py"


def _run_sanitize(staging_dir, sanitized_dir, *extra):
    env = dict(os.environ)
    env["SCRAPE_OUTPUT_DIR"] = str(staging_dir)
    env["SCRAPE_SANITIZED_DIR"] = str(sanitized_dir)
    return subprocess.run(
        [sys.executable, str(_SANITIZE), *extra],
        env=env,
        capture_output=True,
        text=True,
    )


class SanitizeWeeklyGateTests(unittest.TestCase):
    def test_historical_file_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d) / "staging"
            sanitized = Path(d) / "sanitized"
            staging.mkdir()
            pd.DataFrame({"x": [1]}).to_parquet(
                staging / "events_sale_2015-01-01_2023-01-02.parquet", index=False
            )
            r = _run_sanitize(staging, sanitized)
            assert r.returncode != 0, r.stdout + r.stderr
            assert not (
                sanitized / "events_sale_2015-01-01_2023-01-02.parquet"
            ).exists()

    def test_allow_backfill_processes_history(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d) / "staging"
            sanitized = Path(d) / "sanitized"
            staging.mkdir()
            pd.DataFrame({"customer_name": ["张三"]}).to_parquet(
                staging / "events_sale_2015-01-01_2023-01-02.parquet", index=False
            )
            r = _run_sanitize(staging, sanitized, "--allow-backfill")
            assert r.returncode == 0, r.stdout + r.stderr
            assert (
                sanitized / "events_sale_2015-01-01_2023-01-02.parquet"
            ).exists()

    def test_current_week_file_processed(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d) / "staging"
            sanitized = Path(d) / "sanitized"
            staging.mkdir()
            today = date.today()
            wk = today - timedelta(days=7)
            name = f"events_sale_{wk}_{today}.parquet"
            pd.DataFrame({"customer_name": ["张三"]}).to_parquet(
                staging / name, index=False
            )
            r = _run_sanitize(staging, sanitized)
            assert r.returncode == 0, r.stdout + r.stderr
            assert (sanitized / name).exists()
```

注：`sanitize.py` 现用 `SCRAPE_OUTPUT_DIR` 解析 STAGING_DIR、`SCRAPE_SANITIZED_DIR` 解析输出（见 `sanitize.py:54-55`），且 `_resolve` 对绝对路径直接返回，故测试用绝对 tmp 路径注入有效。`unittest` 已在该测试文件顶部 import。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_scraper_sanitize.py::SanitizeWeeklyGateTests -v`
Expected: FAIL — 历史文件当前会被产出（returncode 0、文件存在），断言不成立。

- [ ] **Step 3: 写实现**

在 `scraper/sanitize.py` import 区后（约 line 30，`import pandas as pd` 之后）加双路 import：

```python
try:  # 脚本模式: python scraper/sanitize.py (scraper/ 在 sys.path[0])
    from scrape_window import weekly_violation
except ModuleNotFoundError:  # 包模式: import scraper.sanitize (pytest)
    from scraper.scrape_window import weekly_violation
```

`main()` 的 argparse（约 line 116-127）加 flag：

```python
    parser.add_argument(
        "--allow-backfill",
        action="store_true",
        help="放行历史文件 (跨度>14天/起始>14天前); 周任务勿用",
    )
```

batch 分支（`if not args.input:` 之后；构造 `files` 列表之后、`if not files:` 之后、处理循环之前，约 line 147）插入闸：

```python
    if not args.allow_backfill:
        from datetime import date as _date

        today = _date.today()
        violations = [
            (f.name, reason)
            for f in files
            if (reason := weekly_violation(f.name, today)) is not None
        ]
        if violations:
            print(
                "❌ weekly 模式拒绝历史/异常文件 (加 --allow-backfill 放行):",
                file=sys.stderr,
            )
            for name, reason in violations:
                print(f"    - {name}: {reason}", file=sys.stderr)
            return 1
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_scraper_sanitize.py -v`
Expected: PASS（含原有 + 新 SanitizeWeeklyGateTests）

- [ ] **Step 5: 提交**

```bash
git add scraper/sanitize.py tests/test_scraper_sanitize.py
git commit -m "feat(scraper): sanitize 第一层 weekly 闸 + --allow-backfill (TDD)"
```

---

## Task 4: run_weekly.ps1 manifest 闸 + staging 自清

**Files:**
- Modify: `scraper/run_weekly.ps1`

无单测（PowerShell 脚本）；靠 Task 2 CLI 的 pytest + Task 6 dry-run + 人工 review 验收。

- [ ] **Step 1: 顶部变量区加 staging 目录**

在 `scraper/run_weekly.ps1` 变量区（`$sanitizedDir = Join-Path $PSScriptRoot "sanitized"` 那行附近，约 line 14）加：

```powershell
$stagingDir = Join-Path $PSScriptRoot "staging"
```

- [ ] **Step 2: 上传前插入 manifest 闸**

在 `# === 上传 ===`（约 line 109）之前、`Run-Step "sanitize" ...`（约 line 107）之后插入：

```powershell
    # === 第二层 manifest 闸: 历史/超量文件 → 非零退出 → throw → 不上传不打 heartbeat ===
    Run-Step "manifest_guard" (Join-Path $PSScriptRoot "scrape_window.py") -ScriptArgs @("--check", $sanitizedDir)
```

（`Run-Step` 见非零 exit 即 throw，落入现有 catch → exit 1，天然不触发 categories/forecast/heartbeat。）

- [ ] **Step 3: 上传成功后插入 staging 自清**

在上传循环结束、`Log "=== 完成: $($files.Count) 文件上传, 挪到 $thisRunDir ==="`（约 line 136）之后、触发服务器重算之前插入：

```powershell
    # === staging 自清: 已上传成功, 把 staging 目标文件挪进 uploaded/<ts>/staging/ ===
    # 对称于 sanitized→uploaded; 防 staging 累积历史 (护栏长期成立). _cache/ 保留.
    $stagingDest = Join-Path $thisRunDir "staging"
    New-Item -ItemType Directory -Force -Path $stagingDest | Out-Null
    $stagingFiles = Get-ChildItem -Path $stagingDir -File | Where-Object {
        $_.Name -match '^(events_|inventory_snapshot_|product_master_)'
    }
    foreach ($sf in $stagingFiles) {
        Move-Item -Path $sf.FullName -Destination $stagingDest
    }
    Log "staging 自清: 挪走 $($stagingFiles.Count) 个文件 → $stagingDest (_cache 保留)"
```

- [ ] **Step 4: 静态 review（无单测）**

人工核对：
- manifest_guard 在 curl 上传之前；非零 → throw → 不进上传/refresh/heartbeat。
- staging 自清在上传循环全部成功之后、refresh 之前执行，确保只有上传成功才自清。
- `Get-ChildItem -File` 排除 `_cache/` 目录；正则只匹配三类前缀（`.parquet`+`.xlsx` 都带这些前缀，一并挪走）。

- [ ] **Step 5: 提交**

```bash
git add scraper/run_weekly.ps1
git commit -m "feat(scraper): run_weekly 第二层 manifest 闸 + 上传后 staging 自清"
```

---

## Task 5: 一次性归档现存 staging/sanitized 目标文件

**Files:** 无代码改动；ops 操作（保留现场，不删）。

- [ ] **Step 1: 先看实际内容（不照搬名单）**

Run:
```powershell
Get-ChildItem scraper/staging -File | Where-Object { $_.Name -match '^(events_|inventory_snapshot_|product_master_)' } | Select-Object Name, Length
Get-ChildItem scraper/sanitized -File -ErrorAction SilentlyContinue | Select-Object Name, Length
```
Expected（本次核实快照，仅参考）：staging 6 个本周文件、sanitized 空。

- [ ] **Step 2: 归档到 staging_archive/（用 glob，保留 _cache）**

Run:
```powershell
$dest = "scraper/staging_archive/preguardrail_cleanup_20260608"
New-Item -ItemType Directory -Force -Path "$dest/staging", "$dest/sanitized" | Out-Null
Get-ChildItem scraper/staging -File | Where-Object { $_.Name -match '^(events_|inventory_snapshot_|product_master_)' } | Move-Item -Destination "$dest/staging"
Get-ChildItem scraper/sanitized -File -ErrorAction SilentlyContinue | Move-Item -Destination "$dest/sanitized"
```

- [ ] **Step 3: 验证 staging 只剩 _cache**

Run:
```powershell
Get-ChildItem scraper/staging
```
Expected: 只剩 `_cache/` 目录，无 events_/inventory_snapshot_/product_master_ 文件。

- [ ] **Step 4: 记录归档（写 README 进归档目录）**

Run:
```powershell
"2026-06-08 上线 run-boundary 护栏前的一次性 staging/sanitized 归档。保留现场不删。" | Out-File -Encoding utf8 "scraper/staging_archive/preguardrail_cleanup_20260608/README.txt"
```

（`staging_archive/` 是否 gitignored 在 Task 6 Step 6 确认；若未忽略不要 commit 大 parquet。）

---

## Task 6: dry-run 验收 + 全量回归

**Files:** 无改动；验收。

- [ ] **Step 1: 全量单测回归**

Run: `pytest tests/ -q`
Expected: 全绿，无回归（含新 test_scrape_window.py + test_scraper_sanitize.py 新增）。

- [ ] **Step 2: dry-run — 历史文件必须被 CLI 挡住**

Run:
```powershell
$tmp = New-Item -ItemType Directory -Force -Path "$env:TEMP/scrape_dryrun"
python -c "import pandas as pd; pd.DataFrame({'x':[1]}).to_parquet(r'$($tmp.FullName)/events_sale_2015-01-01_2023-01-02.parquet', index=False)"
python scraper/scrape_window.py --check $tmp.FullName
echo "exit=$LASTEXITCODE"
```
Expected: 打印 manifest + `❌ manifest 闸拦截`，`exit=1`。

- [ ] **Step 2b: dry-run — --allow-backfill 放行**

Run:
```powershell
python scraper/scrape_window.py --check $tmp.FullName --allow-backfill
echo "exit=$LASTEXITCODE"
```
Expected: `✅ --allow-backfill`，`exit=0`。

- [ ] **Step 3: 验证 staging 现场（Task 5 后）**

Run: `Get-ChildItem scraper/staging`
Expected: 只剩 `_cache/`。

- [ ] **Step 4: run_weekly.ps1 终审**

人工 review 改后的 `run_weekly.ps1`：
- manifest_guard 在 curl 上传之前；abort 路径不触发 categories/forecast/heartbeat。
- staging 自清只在上传全部成功后执行；`_cache/` 保留。

- [ ] **Step 5: 清理 dry-run 临时目录**

Run: `Remove-Item -Recurse -Force "$env:TEMP/scrape_dryrun"`

- [ ] **Step 6: 收尾 — 确认 .gitignore 不带入归档大文件**

Run: `git status --short`
Expected: 仅 `scraper/scrape_window.py`、`tests/*`、`scraper/sanitize.py`、`scraper/run_weekly.ps1`、`docs/...` 等代码/文档变更；`staging_archive/` 下 parquet **不应**进暂存（确认已 gitignore，否则补 .gitignore）。

---

## Self-Review

**Spec coverage:**
- scrape_window 纯函数 → Task 1 ✅
- `--check` CLI + manifest 按 kind + 大小闸 + master 显式标注 → Task 2 ✅
- sanitize 第一层 + `--allow-backfill` → Task 3 ✅
- run_weekly 第二层 manifest 闸 + staging 自清 → Task 4 ✅
- 一次性归档（glob 全部现存目标文件，不 hardcode）→ Task 5 ✅
- unknown 收紧（坏命名目标文件拒）→ Task 1 用例 `test_bad_named_target_rejected` ✅
- dry-run 验收（历史被挡 + 不打错 heartbeat）→ Task 6 ✅

**类型/签名一致性：**
- `parse_window(filename) -> (kind, start, end)`、`weekly_violation(filename, today, max_span_days=14, max_age_days=14)`、`run_check(directory, today, max_total_mb, allow_backfill)`、`_iter_target_files(directory)` 全计划一致。
- 双路 import 名一致（`weekly_violation`）。
- run_weekly 变量 `$stagingDir`/`$stagingDest`/`$thisRunDir` 一致。

**边界：** span > 14 拒（==14 放行）、start < today-14 拒（==today-14 放行），Task 1 `test_boundary_span_exactly_14_ok` 锁定。
