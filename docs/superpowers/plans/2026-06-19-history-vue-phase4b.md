# 货号历史 Vue Phase 4b（批次记录 tab：扫描批次）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `/ui/history` 的「批次记录」tab 加「扫描批次」子-tab，迁移旧 `index-scan-history.js` 的批次浏览/下载能力；列表走新建 strict `/api/history/scan-batches`，二进制下载复用既有 `/scan_history/*`，ZIP 为 additive 增强。

**Architecture:** 后端新增 1 个只读 strict 列表端点（pydantic `extra=forbid`，复用 `scan_history` service 不重写）；前端镜像 Phase 4a recent-changes 文件结构（store 代际守卫 + lazy 持久挂载 + normalize/types）。两个子面板各自独立 Pinia store，完全隔离。

**Tech Stack:** Python 3.12 + Flask + pydantic（后端）；Vue 3 + TypeScript + Pinia + Vitest（前端）；pytest（后端测试）。

**设计 spec：** `docs/superpowers/specs/2026-06-19-history-vue-phase4b-design.md`（终审 APPROVE）。

---

## 文件结构

**后端：**
- Modify: `app/schemas_api.py` — 加 `ScanXlsxFile` / `ScanBatch` / `ScanBatchList`；`API_MODELS` 追加 `ScanBatchList`
- Modify: `app/routes/history.py` — 加 `GET /api/history/scan-batches` 路由
- Create: `tests/test_scan_batches_api.py` — 新端点契约测试
- Modify: `tests/test_scan_history_routes.py` — 补 ZIP 下载端到端测试
- Generated: `frontend/src/api/types.gen.ts` — 跑 `tools/gen_ts_types.py` 产出（勿手改）

**前端：**
- Create: `frontend/src/pages/history/scan-batch-types.ts` — VM 类型
- Create: `frontend/src/pages/history/scan-batch-normalize.ts` — API→VM
- Create: `frontend/src/pages/history/scan-batch-normalize.test.ts`
- Create: `frontend/src/stores/scanBatches.ts` — Pinia store
- Create: `frontend/src/stores/scanBatches.test.ts`
- Create: `frontend/src/pages/history/ScanBatchPanel.vue` — 子面板
- Create: `frontend/src/pages/history/ScanBatchPanel.test.ts`
- Modify: `frontend/src/pages/history/HistoryPage.vue` — 子-tab 接线
- Modify: `frontend/src/pages/history/HistoryPage.test.ts` — 子-tab 断言
- Modify: `frontend/src/pages/history/no-analytics.test.ts` — 扫描集加 `scanBatches.ts`

> 注：前端命令在 `frontend/` 目录跑。后端 `pytest` 在仓库根跑（默认 tmp sqlite）。

---

## Task 1: 后端 schema + API_MODELS 注册 + 生成 TS 类型

**Files:**
- Modify: `app/schemas_api.py:399-455`（在 RecentChanges* 之后、API_MODELS 之前插入新 schema；API_MODELS 列表追加）
- Generated: `frontend/src/api/types.gen.ts`

- [ ] **Step 1: 加 schema 类**

在 `app/schemas_api.py` 的 `RecentChangesDetail` 类之后、`# gen_ts_types.py 的导出清单` 注释之前，插入：

```python
class ScanXlsxFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    size_bytes: int


class ScanBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    employee: str
    scanned_at: str
    csv_filename: str | None
    csv_rows: int | None
    csv_size_bytes: int | None
    xlsx_files: list[ScanXlsxFile]


class ScanBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    batches: list[ScanBatch]
```

- [ ] **Step 2: 把顶层 `ScanBatchList` 加进 `API_MODELS`**

`API_MODELS` 列表（`schemas_api.py:445`）在 `RecentChangesDetail,` 后追加一行：

```python
    RecentChangesDetail,
    ScanBatchList,
]
```

> 只加顶层 `ScanBatchList`；嵌套 `ScanBatch`/`ScanXlsxFile` 经 `$defs` 自动生成。

- [ ] **Step 3: 生成 TS 类型**

Run（仓库根）: `python tools/gen_ts_types.py`
Expected: 退出码 0，`frontend/src/api/types.gen.ts` 被更新。

- [ ] **Step 4: 验证生成物含新类型**

Run（仓库根）: `grep -E "ScanBatchList|ScanBatch\b" frontend/src/api/types.gen.ts`
Expected: 匹配到 `ScanBatchList` 与 `ScanBatch`（防类型静默缺失）。若无匹配 → 回到 Step 2 确认 API_MODELS 改对。

- [ ] **Step 5: gen --check 绿**

Run（仓库根）: `python tools/gen_ts_types.py --check`
Expected: 退出码 0（无漂移）。

- [ ] **Step 6: Commit**

```bash
git add app/schemas_api.py frontend/src/api/types.gen.ts
git commit -m "feat(history): Phase 4b scan-batches strict schema + TS 类型生成"
```

---

## Task 2: 后端 `GET /api/history/scan-batches` 路由 + 契约测试

**Files:**
- Create: `tests/test_scan_batches_api.py`
- Modify: `app/routes/history.py`（在 `recent_changes_batches` 之后加新路由）

- [ ] **Step 1: 写失败测试**

Create `tests/test_scan_batches_api.py`：

```python
"""GET /api/history/scan-batches 契约测试（Phase 4b）。

鉴权夹具镜像 tests/test_history_recent_changes_api.py（real_app + X-Upload-Token）。
扫描数据走文件系统：monkeypatch scan_history service 的 OUTPUT_DIR 到 tmp 目录。
"""

from __future__ import annotations

import pytest

from app.services import scan_history as scan_history_service


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


_AUTH = {"X-Upload-Token": "test-token-123"}


def _make_batch(base, folder_name, *, csv_rows=0, xlsx=None, write_csv=True):
    batch = base / folder_name
    batch.mkdir()
    if write_csv:
        csv = batch / "1产品信息导入模板.csv"
        lines = ["型号,唯一码"]
        lines.extend(f"M{i},B{i}" for i in range(csv_rows))
        csv.write_text("\n".join(lines), encoding="utf-8-sig")
    for x in xlsx or []:
        (batch / x).write_bytes(b"FAKE" * 100)
    return batch


def _get(app):
    return app.test_client().get("/api/history/scan-batches", headers=_AUTH)


def test_returns_strict_schema_with_batches(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    _make_batch(tmp_path, "ALI价格标20260420100000", csv_rows=3, xlsx=["ALI.xlsx"])
    _make_batch(tmp_path, "ABDUL价格标20260421100000", csv_rows=5)

    resp = _get(real_app)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert len(data["batches"]) == 2
    # 最近优先：ABDUL（更晚时间戳）在前
    assert data["batches"][0]["employee"] == "ABDUL"


def test_exact_key_sets(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    _make_batch(tmp_path, "ALI价格标20260420100000", csv_rows=1, xlsx=["ALI.xlsx"])

    data = _get(real_app).get_json()
    assert set(data.keys()) == {"ok", "batches"}
    b = data["batches"][0]
    assert set(b.keys()) == {
        "batch_id", "employee", "scanned_at",
        "csv_filename", "csv_rows", "csv_size_bytes", "xlsx_files",
    }
    assert set(b["xlsx_files"][0].keys()) == {"name", "size_bytes"}


def test_missing_csv_nulls_pass_schema(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    _make_batch(tmp_path, "ALI价格标20260420100000", xlsx=["ALI.xlsx"], write_csv=False)

    resp = _get(real_app)
    assert resp.status_code == 200  # 不被 pydantic 打 500
    b = resp.get_json()["batches"][0]
    assert b["csv_filename"] is None
    assert b["csv_rows"] is None
    assert b["csv_size_bytes"] is None


def test_empty_output_dir(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    data = _get(real_app).get_json()
    assert data["batches"] == []


def test_caps_at_100(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    for i in range(110):
        _make_batch(tmp_path, f"E价格标202604{i:08d}", csv_rows=0)
    data = _get(real_app).get_json()
    assert len(data["batches"]) == 100


def test_unauthenticated_returns_json_401(real_app):
    resp = real_app.test_client().get("/api/history/scan-batches")  # 无 token
    assert resp.status_code == 401
    assert resp.is_json


def test_service_exception_bubbles_500(real_app, monkeypatch):
    def boom():
        raise RuntimeError("scan boom")

    monkeypatch.setattr(scan_history_service, "list_batches", boom)
    client = real_app.test_client()
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    resp = client.get("/api/history/scan-batches", headers=_AUTH)
    assert resp.status_code == 500
```

- [ ] **Step 2: 跑测试确认失败**

Run（仓库根）: `pytest tests/test_scan_batches_api.py -v`
Expected: FAIL（404，路由未定义 → 多数断言失败）。

- [ ] **Step 3: 实现路由**

在 `app/routes/history.py` 的 `recent_changes_batches()` 函数之后插入：

```python
@api_bp.get("/scan-batches")
def scan_batches():
    from app.schemas_api import ScanBatchList
    from app.services import scan_history as scan_history_service

    # service 系统级异常不在此吞 → 冒泡 Flask 通用 500（对齐其它 strict 端点）。
    payload = {"ok": True, "batches": scan_history_service.list_batches()}
    return jsonify(ScanBatchList.model_validate(payload).model_dump())
```

> `scan_history_service.list_batches()` 默认 `limit=100`，返回的 dict 字段恰好对齐 `ScanBatch`（`scan_history.py:99-108`：batch_id/employee/scanned_at/csv_filename/csv_rows/csv_size_bytes/xlsx_files），无需投影改名。

- [ ] **Step 4: 确认新端点已注册到 app**

`/api/history/scan-batches` 走 `api_bp`（已在 `create_app` 注册）。无需改注册代码。

- [ ] **Step 5: 跑测试确认通过**

Run（仓库根）: `pytest tests/test_scan_batches_api.py -v`
Expected: 7 个用例全 PASS。

- [ ] **Step 6: Commit**

```bash
git add app/routes/history.py tests/test_scan_batches_api.py
git commit -m "feat(history): Phase 4b GET /api/history/scan-batches（strict 列表 + 401/500/null/cap 契约）"
```

---

## Task 3: ZIP 下载端到端测试（补进既有路由测试）

**Files:**
- Modify: `tests/test_scan_history_routes.py`（在 `test_download_xlsx_returns_file` 之后加）

> ZIP 路由（`/scan_history/batches/<id>/download/zip`）已存在但旧测试未覆盖；本期它成为新用户入口，补端到端断言（200 + attachment + 归档成员；不存在 → 404）。这是对既有路由的覆盖测试，预期对现有实现即 PASS。

- [ ] **Step 1: 写测试**

在 `tests/test_scan_history_routes.py` 的 `ScanHistoryRoutesTests` 类内、`test_download_xlsx_returns_file` 之后加：

```python
    def test_download_zip_returns_archive_with_members(self):
        import io
        import zipfile

        self._make_batch(
            "ALI价格标20260420100000",
            csv_rows=2,
            xlsx_files=["ALI.xlsx", "B.xlsx"],
        )

        resp = self.client.get("/scan_history/batches/ALI价格标20260420100000/download/zip")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            names = zf.namelist()
        self.assertTrue(any("1产品信息导入模板.csv" in n for n in names))
        self.assertTrue(any(n.endswith("ALI.xlsx") for n in names))
        self.assertTrue(any(n.endswith("B.xlsx") for n in names))

    def test_download_zip_returns_404_for_missing_batch(self):
        resp = self.client.get("/scan_history/batches/NOPE价格标20260420100000/download/zip")
        self.assertEqual(resp.status_code, 404)
```

- [ ] **Step 2: 跑测试**

Run（仓库根）: `pytest tests/test_scan_history_routes.py -v`
Expected: 全 PASS（含新 2 个 + 原有 6 个）。若 ZIP 成员名断言因 `build_batch_zip` 实际归档结构不符而失败 → 读 `app/services/scan_history.py::build_batch_zip` 修正断言以匹配实际成员名（不改 service）。

- [ ] **Step 3: Commit**

```bash
git add tests/test_scan_history_routes.py
git commit -m "test(history): Phase 4b 补 ZIP 下载端到端（200+attachment+归档成员/404）"
```

---

## Task 4: 前端 types + normalize（含测试）

**Files:**
- Create: `frontend/src/pages/history/scan-batch-types.ts`
- Create: `frontend/src/pages/history/scan-batch-normalize.ts`
- Create: `frontend/src/pages/history/scan-batch-normalize.test.ts`

- [ ] **Step 1: 写 VM 类型**

Create `frontend/src/pages/history/scan-batch-types.ts`：

```typescript
export interface ScanXlsxFileVM {
  name: string;
  sizeBytes: number;
}

export interface ScanBatchVM {
  batchId: string;
  employee: string;
  scannedAt: string;
  csvFilename: string | null;
  csvRows: number | null;
  csvSizeBytes: number | null;
  xlsxFiles: ScanXlsxFileVM[];
}
```

- [ ] **Step 2: 写失败测试**

Create `frontend/src/pages/history/scan-batch-normalize.test.ts`：

```typescript
import { describe, expect, it } from "vitest";
import { normalizeBatches } from "./scan-batch-normalize";

function raw(over = {}) {
  return {
    ok: true,
    batches: [
      {
        batch_id: "ALI价格标20260420100000",
        employee: "ALI",
        scanned_at: "2026-04-20 10:00:00",
        csv_filename: "1产品信息导入模板.csv",
        csv_rows: 3,
        csv_size_bytes: 120,
        xlsx_files: [{ name: "ALI.xlsx", size_bytes: 400 }],
        ...over,
      },
    ],
  };
}

describe("scan-batch normalize", () => {
  it("snake → camel，字段完整", () => {
    const vm = normalizeBatches(raw() as never);
    expect(vm[0]).toEqual({
      batchId: "ALI价格标20260420100000",
      employee: "ALI",
      scannedAt: "2026-04-20 10:00:00",
      csvFilename: "1产品信息导入模板.csv",
      csvRows: 3,
      csvSizeBytes: 120,
      xlsxFiles: [{ name: "ALI.xlsx", sizeBytes: 400 }],
    });
  });

  it("CSV 缺失：三字段保持 null（不塌成 0）", () => {
    const vm = normalizeBatches(
      raw({ csv_filename: null, csv_rows: null, csv_size_bytes: null }) as never,
    );
    expect(vm[0].csvFilename).toBeNull();
    expect(vm[0].csvRows).toBeNull();
    expect(vm[0].csvSizeBytes).toBeNull();
  });

  it("batches 缺省 → 空数组", () => {
    expect(normalizeBatches({ ok: true } as never)).toEqual([]);
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run（`frontend/`）: `npm run test -- scan-batch-normalize`
Expected: FAIL（`normalize` 未定义）。

- [ ] **Step 4: 实现 normalize**

Create `frontend/src/pages/history/scan-batch-normalize.ts`：

```typescript
import type { ScanBatchList } from "../../api/types.gen";
import type { ScanBatchVM } from "./scan-batch-types";

export function normalizeBatches(raw: ScanBatchList): ScanBatchVM[] {
  return (raw.batches ?? []).map((b) => ({
    batchId: b.batch_id,
    employee: b.employee,
    scannedAt: b.scanned_at,
    csvFilename: b.csv_filename ?? null,
    csvRows: b.csv_rows ?? null,
    csvSizeBytes: b.csv_size_bytes ?? null,
    xlsxFiles: (b.xlsx_files ?? []).map((f) => ({ name: f.name, sizeBytes: f.size_bytes })),
  }));
}
```

- [ ] **Step 5: 跑测试确认通过**

Run（`frontend/`）: `npm run test -- scan-batch-normalize`
Expected: 3 个用例全 PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/history/scan-batch-types.ts frontend/src/pages/history/scan-batch-normalize.ts frontend/src/pages/history/scan-batch-normalize.test.ts
git commit -m "feat(history): Phase 4b scan-batch VM 类型 + normalize（null 安全）"
```

---

## Task 5: 前端 scanBatches store（含测试）

**Files:**
- Create: `frontend/src/stores/scanBatches.ts`
- Create: `frontend/src/stores/scanBatches.test.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/stores/scanBatches.test.ts`：

```typescript
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useScanBatchesStore } from "./scanBatches";

function batchList() {
  return {
    ok: true,
    batches: [
      { batch_id: "ALI价格标20260420100000", employee: "ALI", scanned_at: "2026-04-20 10:00:00",
        csv_filename: "x.csv", csv_rows: 3, csv_size_bytes: 120, xlsx_files: [] },
      { batch_id: "ABDUL价格标20260421100000", employee: "ABDUL", scanned_at: "2026-04-21 10:00:00",
        csv_filename: null, csv_rows: null, csv_size_bytes: null, xlsx_files: [] },
      { batch_id: "ALI价格标20260422100000", employee: "ALI", scanned_at: "2026-04-22 10:00:00",
        csv_filename: "y.csv", csv_rows: 1, csv_size_bytes: 50, xlsx_files: [] },
    ],
  };
}

const SCAN = "/api/history/scan-batches";
const scanCalls = () => vi.mocked(apiGet).mock.calls.filter((c) => c[0] === SCAN);

describe("scanBatches store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(apiGet).mockReset();
  });

  it("loadBatches 填 batches + loaded=true", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.batches.length).toBe(3);
    expect(s.loaded).toBe(true);
    expect(s.error).toBeNull();
  });

  it("employees 从批次派生（去重+排序）", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.employees).toEqual(["ABDUL", "ALI"]);
  });

  it("filteredBatches 按 employeeFilter；null=全部", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.filteredBatches.length).toBe(3);
    s.setEmployeeFilter("ALI");
    expect(s.filteredBatches.map((b) => b.employee)).toEqual(["ALI", "ALI"]);
    s.setEmployeeFilter(null);
    expect(s.filteredBatches.length).toBe(3);
  });

  it("toggleExpand 支持多行同时展开", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    s.toggleExpand("ALI价格标20260420100000");
    s.toggleExpand("ALI价格标20260422100000");
    expect(s.expanded.has("ALI价格标20260420100000")).toBe(true);
    expect(s.expanded.has("ALI价格标20260422100000")).toBe(true);
    s.toggleExpand("ALI价格标20260420100000");
    expect(s.expanded.has("ALI价格标20260420100000")).toBe(false);
  });

  it("401 → 不落 error", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.error).toBeNull();
    expect(s.loaded).toBe(false);
  });

  it("ensureLoaded 幂等：首调 1 次，二调 0 新请求", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.ensureLoaded();
    expect(scanCalls().length).toBe(1);
    await s.ensureLoaded();
    expect(scanCalls().length).toBe(1);
  });

  it("首次失败 loaded=false → 二次 ensureLoaded 重试发请求", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    const s = useScanBatchesStore();
    await s.ensureLoaded();
    expect(s.loaded).toBe(false);
    expect(s.error).toBe("boom");
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    await s.ensureLoaded();
    expect(scanCalls().length).toBe(2);
    expect(s.loaded).toBe(true);
  });

  it("reset 作废 pending：resolve 后不回填，loaded=false，清 filter+expanded", async () => {
    let resolve: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementation(() => new Promise((r) => { resolve = r; }) as never);
    const s = useScanBatchesStore();
    const p = s.loadBatches();
    s.setEmployeeFilter("ALI");
    s.reset();
    resolve(batchList());
    await p;
    expect(s.batches).toEqual([]);
    expect(s.loaded).toBe(false);
    expect(s.employeeFilter).toBeNull();
    expect(s.expanded.size).toBe(0);
  });

  it("inflight 代际竞态：A pending→reset→ensureLoaded(B)→A 迟到不清 B 的 inflight→不起 C", async () => {
    let resolveA: (v: unknown) => void = () => {};
    let resolveB: (v: unknown) => void = () => {};
    let nth = 0;
    vi.mocked(apiGet).mockImplementation(async () => {
      nth += 1;
      if (nth === 1) return new Promise((r) => { resolveA = r; }) as never;
      if (nth === 2) return new Promise((r) => { resolveB = r; }) as never;
      throw new Error("spurious C");
    });
    const s = useScanBatchesStore();
    const pA = s.ensureLoaded();
    expect(scanCalls().length).toBe(1);
    s.reset();
    const pB = s.ensureLoaded();
    expect(scanCalls().length).toBe(2);
    resolveA(batchList());
    await pA;
    const pExtra = s.ensureLoaded();
    expect(scanCalls().length).toBe(2); // 无 C
    resolveB(batchList());
    await pB;
    await pExtra;
    expect(scanCalls().length).toBe(2);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run（`frontend/`）: `npm run test -- scanBatches`
Expected: FAIL（store 未定义）。

- [ ] **Step 3: 实现 store**

Create `frontend/src/stores/scanBatches.ts`：

```typescript
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { ScanBatchList } from "../api/types.gen";
import { normalizeBatches } from "../pages/history/scan-batch-normalize";
import type { ScanBatchVM } from "../pages/history/scan-batch-types";

export const useScanBatchesStore = defineStore("scanBatches", () => {
  const batches = ref<ScanBatchVM[]>([]);
  const employeeFilter = ref<string | null>(null); // null = 全部员工
  const expanded = ref<Set<string>>(new Set());     // 展开的 batchId，多行并存
  const loading = ref(false);
  const error = ref<string | null>(null);
  const loaded = ref(false);
  let inflight = false;
  let batchesGen = 0, initGen = 0;

  async function ensureLoaded() {
    if (loaded.value || inflight) return;
    const my = ++initGen;
    inflight = true;
    try { await loadBatches(); }
    finally { if (my === initGen) inflight = false; }
  }

  async function loadBatches() {
    const my = ++batchesGen;
    loading.value = true; error.value = null;
    try {
      const raw = await apiGet<ScanBatchList>("/api/history/scan-batches");
      if (my !== batchesGen) return;
      batches.value = normalizeBatches(raw);
      loaded.value = true;
    } catch (e) {
      if (my !== batchesGen) return;
      if (e instanceof UnauthenticatedError) return; // 401 不落 error
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === batchesGen) loading.value = false;
    }
  }

  const employees = computed(() =>
    [...new Set(batches.value.map((b) => b.employee))].sort());
  const filteredBatches = computed(() =>
    employeeFilter.value ? batches.value.filter((b) => b.employee === employeeFilter.value) : batches.value);

  function setEmployeeFilter(name: string | null) { employeeFilter.value = name; }
  function toggleExpand(batchId: string) {
    const next = new Set(expanded.value);
    next.has(batchId) ? next.delete(batchId) : next.add(batchId);
    expanded.value = next;
  }
  function reset() {
    batchesGen++; initGen++; loaded.value = false; inflight = false;
    batches.value = []; employeeFilter.value = null; expanded.value = new Set();
    loading.value = false; error.value = null;
  }

  return { batches, employeeFilter, expanded, loading, error, loaded,
           employees, filteredBatches,
           ensureLoaded, loadBatches, setEmployeeFilter, toggleExpand, reset };
});
```

- [ ] **Step 4: 跑测试确认通过**

Run（`frontend/`）: `npm run test -- scanBatches`
Expected: 9 个用例全 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/scanBatches.ts frontend/src/stores/scanBatches.test.ts
git commit -m "feat(history): Phase 4b scanBatches store（代际守卫 + 派生 employees + 多行展开 + 可重试）"
```

---

## Task 6: ScanBatchPanel.vue（含组件测试）

**Files:**
- Create: `frontend/src/pages/history/ScanBatchPanel.vue`
- Create: `frontend/src/pages/history/ScanBatchPanel.test.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/pages/history/ScanBatchPanel.test.ts`：

```typescript
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(),
}));

import { apiGet } from "../../api/client";
import ScanBatchPanel from "./ScanBatchPanel.vue";

function batchList() {
  return {
    ok: true,
    batches: [
      { batch_id: "ALI价格标20260420100000", employee: "ALI", scanned_at: "2026-04-20 10:00:00",
        csv_filename: "x.csv", csv_rows: 3, csv_size_bytes: 120, xlsx_files: [{ name: "ALI.xlsx", size_bytes: 400 }] },
      { batch_id: "ZH#A 价/标20260421100000", employee: "ABDUL", scanned_at: "2026-04-21 10:00:00",
        csv_filename: null, csv_rows: null, csv_size_bytes: null, xlsx_files: [] },
    ],
  };
}

async function mountLoaded() {
  vi.mocked(apiGet).mockResolvedValue(batchList() as never);
  const w = mount(ScanBatchPanel);
  await new Promise((r) => setTimeout(r, 0)); // flush onMounted ensureLoaded
  await w.vm.$nextTick();
  return w;
}

describe("ScanBatchPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(apiGet).mockReset();
  });

  it("onMounted 调 ensureLoaded（请求列表端点）", async () => {
    await mountLoaded();
    expect(vi.mocked(apiGet).mock.calls.some((c) => c[0] === "/api/history/scan-batches")).toBe(true);
  });

  it("行头是 button 且 aria-expanded 随展开切换", async () => {
    const w = await mountLoaded();
    const head = w.findAll("button.sb-row-head")[0];
    expect(head.attributes("type")).toBe("button");
    expect(head.attributes("aria-expanded")).toBe("false");
    await head.trigger("click");
    expect(w.findAll("button.sb-row-head")[0].attributes("aria-expanded")).toBe("true");
  });

  it("多行可同时展开", async () => {
    const w = await mountLoaded();
    const heads = w.findAll("button.sb-row-head");
    await heads[0].trigger("click");
    await heads[1].trigger("click");
    const expanded = w.findAll("button.sb-row-head").filter((h) => h.attributes("aria-expanded") === "true");
    expect(expanded.length).toBe(2);
  });

  it("CSV 缺失行显示「CSV 缺失」且无 CSV 下载链", async () => {
    const w = await mountLoaded();
    await w.findAll("button.sb-row-head")[1].trigger("click");
    const html = w.html();
    expect(html).toContain("CSV 缺失");
  });

  it("下载链接 encodeURIComponent 编码 batchId 与文件名；无 target=_blank", async () => {
    const w = await mountLoaded();
    await w.findAll("button.sb-row-head")[0].trigger("click");
    const links = w.findAll("a.sb-dl");
    const hrefs = links.map((a) => a.attributes("href"));
    const enc = encodeURIComponent("ALI价格标20260420100000");
    expect(hrefs).toContain(`/scan_history/batches/${enc}/download/csv`);
    expect(hrefs).toContain(`/scan_history/batches/${enc}/download/zip`);
    expect(hrefs).toContain(`/scan_history/batches/${enc}/files/${encodeURIComponent("ALI.xlsx")}`);
    for (const a of links) expect(a.attributes("target")).toBeUndefined();
  });

  it("特殊字符 batchId（#、空格、/）正确编码", async () => {
    const w = await mountLoaded();
    await w.findAll("button.sb-row-head")[1].trigger("click");
    const zip = w.findAll("a.sb-dl").find((a) => a.attributes("href")?.includes("/download/zip"));
    expect(zip?.attributes("href")).toBe(
      `/scan_history/batches/${encodeURIComponent("ZH#A 价/标20260421100000")}/download/zip`,
    );
  });

  it("员工筛选无匹配 → 暂无批次空态", async () => {
    const w = await mountLoaded();
    const sel = w.find("select.sb-employee");
    // 注入一个不存在的值触发空 filteredBatches：直接用 store
    await sel.setValue("不存在的人");
    expect(w.html()).toContain("暂无批次");
  });

  it("加载失败 → 错误条 + 重试按钮调 ensureLoaded", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    const w = mount(ScanBatchPanel);
    await new Promise((r) => setTimeout(r, 0));
    await w.vm.$nextTick();
    expect(w.html()).toContain("boom");
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    await w.find("button.sb-retry").trigger("click");
    await new Promise((r) => setTimeout(r, 0));
    await w.vm.$nextTick();
    expect(w.findAll("button.sb-row-head").length).toBe(2);
  });
});
```

> 「员工筛选无匹配」用例：下拉只渲染派生的真实员工（ALI/ABDUL），`不存在的人` 不是合法 option；测试用 `setValue` 直接驱动 `<select>` 的 v-model 写入 `employeeFilter`，验证空态分支。若你的 select 绑定方式使非法值无法写入，改为在组件挂载后用 store 设 filter 再断言（保持验证「filteredBatches 空 → 暂无批次」这一行为契约）。

- [ ] **Step 2: 跑测试确认失败**

Run（`frontend/`）: `npm run test -- ScanBatchPanel`
Expected: FAIL（组件未定义）。

- [ ] **Step 3: 实现组件**

Create `frontend/src/pages/history/ScanBatchPanel.vue`：

```vue
<script setup lang="ts">
import { onMounted } from "vue";
import { useScanBatchesStore } from "../../stores/scanBatches";
import type { ScanBatchVM } from "./scan-batch-types";

const store = useScanBatchesStore();
onMounted(() => { store.ensureLoaded(); });

function csvUrl(b: ScanBatchVM) {
  return `/scan_history/batches/${encodeURIComponent(b.batchId)}/download/csv`;
}
function zipUrl(b: ScanBatchVM) {
  return `/scan_history/batches/${encodeURIComponent(b.batchId)}/download/zip`;
}
function fileUrl(b: ScanBatchVM, name: string) {
  return `/scan_history/batches/${encodeURIComponent(b.batchId)}/files/${encodeURIComponent(name)}`;
}
function fmtBytes(n: number | null): string {
  if (n === null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function summary(b: ScanBatchVM): string {
  const csv = b.csvRows !== null ? `${b.csvRows} 行` : "无 CSV";
  const xlsx = b.xlsxFiles.length ? `${b.xlsxFiles.length} 个 xlsx` : "";
  return [csv, xlsx].filter(Boolean).join(" · ");
}
function onEmployeeChange(e: Event) {
  const v = (e.target as HTMLSelectElement).value;
  store.setEmployeeFilter(v === "" ? null : v);
}
</script>

<template>
  <div class="sb">
    <div v-if="store.error" class="sb-error">
      加载失败：{{ store.error }}
      <button type="button" class="sb-retry" @click="store.ensureLoaded()">重试</button>
    </div>

    <template v-else>
      <div class="sb-toolbar">
        <select class="sb-employee" :value="store.employeeFilter ?? ''" @change="onEmployeeChange">
          <option value="">全部员工</option>
          <option v-for="e in store.employees" :key="e" :value="e">{{ e }}</option>
        </select>
      </div>

      <div v-if="store.filteredBatches.length === 0" class="sb-empty">暂无批次</div>

      <div v-else class="sb-list">
        <div v-for="b in store.filteredBatches" :key="b.batchId" class="sb-row">
          <button
            type="button"
            class="sb-row-head"
            :aria-expanded="store.expanded.has(b.batchId)"
            @click="store.toggleExpand(b.batchId)">
            <span class="sb-time">{{ b.scannedAt }}</span>
            <span class="sb-emp">{{ b.employee }}</span>
            <span class="sb-meta">{{ summary(b) }}</span>
            <span class="sb-chevron">{{ store.expanded.has(b.batchId) ? "▼" : "▶" }}</span>
          </button>

          <div v-if="store.expanded.has(b.batchId)" class="sb-detail">
            <div v-if="b.csvFilename" class="sb-file">
              📄 {{ b.csvFilename }} · {{ b.csvRows }} 行 · {{ fmtBytes(b.csvSizeBytes) }}
              <a class="sb-dl" :href="csvUrl(b)">下载</a>
            </div>
            <div v-else class="sb-file sb-file--muted">📄 CSV 缺失</div>

            <div v-for="f in b.xlsxFiles" :key="f.name" class="sb-file">
              📊 {{ f.name }} · {{ fmtBytes(f.sizeBytes) }}
              <a class="sb-dl" :href="fileUrl(b, f.name)">下载</a>
            </div>

            <div class="sb-file sb-file--zip">
              🗜 <a class="sb-dl" :href="zipUrl(b)">下载全部 ZIP</a>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sb { display: flex; flex-direction: column; gap: var(--sp-3); }
.sb-error { padding: var(--sp-3); color: var(--error); }
.sb-retry { margin-left: var(--sp-2); padding: 2px 10px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-0); cursor: pointer; }
.sb-employee { padding: 4px 8px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: var(--surface-1); color: var(--ink-0); }
.sb-empty { padding: var(--sp-4); color: var(--ink-3); }
.sb-row { border-bottom: 1px solid var(--line-soft); }
.sb-row-head { display: flex; gap: var(--sp-3); align-items: center; width: 100%; padding: var(--sp-2) 0; background: transparent; border: none; color: var(--ink-0); cursor: pointer; text-align: left; }
.sb-emp { color: var(--accent); }
.sb-meta { color: var(--ink-2); }
.sb-chevron { margin-left: auto; color: var(--ink-3); }
.sb-detail { padding: 0 0 var(--sp-2) var(--sp-3); display: flex; flex-direction: column; gap: 4px; }
.sb-file { font-size: var(--fs-sm); }
.sb-file--muted { color: var(--ink-3); }
.sb-dl { margin-left: var(--sp-2); color: var(--accent); }
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run（`frontend/`）: `npm run test -- ScanBatchPanel`
Expected: 8 个用例全 PASS。若「员工筛选无匹配」用例因 `setValue` 非法值不被写入而失败，按 Step 1 备注改为经 store 设 filter 后断言。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/history/ScanBatchPanel.vue frontend/src/pages/history/ScanBatchPanel.test.ts
git commit -m "feat(history): Phase 4b ScanBatchPanel.vue（折叠行/下载/编码/空态/重试 + a11y）"
```

---

## Task 7: HistoryPage 子-tab 接线（含测试）

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue:9,17-20,131-134,536-538`
- Modify: `frontend/src/pages/history/HistoryPage.test.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/pages/history/HistoryPage.test.ts` 加（沿用该文件既有 mount 工具；下例假设可 `import` 该文件已有的 `mountPage`/stub 约定，若无则按文件现有挂载方式写）：

```typescript
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import HistoryPage from "./HistoryPage.vue";

// 子-tab：点「批次记录」→ 默认显示「最近改动」子-tab，ScanBatchPanel 未挂载；
// 点「扫描批次」子-tab → scanVisited 置 true、ScanBatchPanel 挂载；切回再切回不重复请求。
describe("HistoryPage 批次记录子-tab", () => {
  it("点扫描批次子-tab → ScanBatchPanel 挂载（scanVisited 持久）", async () => {
    setActivePinia(createPinia());
    const w = mount(HistoryPage);
    // 进入批次记录 tab
    await w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!.trigger("click");
    // 默认在最近改动子-tab，扫描面板未挂载
    expect(w.findComponent({ name: "ScanBatchPanel" }).exists()).toBe(false);
    // 点扫描批次子-tab
    await w.findAll("button.history__sub-tab").find((b) => b.text().includes("扫描批次"))!.trigger("click");
    expect(w.findComponent({ name: "ScanBatchPanel" }).exists()).toBe(true);
  });
});
```

> 若 `HistoryPage.test.ts` 已对 store/子组件做了全局 stub，沿用其 stub 约定（用 `findComponent` 名称匹配或 stub 标记），避免真实网络。`ScanBatchPanel` 需具名（见 Step 2 末尾）。

- [ ] **Step 2: 跑测试确认失败**

Run（`frontend/`）: `npm run test -- HistoryPage`
Expected: FAIL（无子-tab 按钮 / ScanBatchPanel 未引入）。

- [ ] **Step 3: 实现接线**

3a. `HistoryPage.vue` script 顶部加 import（第 9 行 `RecentChangesPanel` 之后）：

```typescript
import ScanBatchPanel from "./ScanBatchPanel.vue";
```

3b. 子-tab 状态（第 18 行 `batchVisited` 之后）：

```typescript
const batchSubTab = ref<"recent" | "scan">("recent");
const scanVisited = ref(false);
function showScan() { batchSubTab.value = "scan"; scanVisited.value = true; }
```

3c. 批次记录 tab 内容（替换第 536-538 行）：

```vue
    <div v-if="batchVisited" v-show="activeTab === 'batch'">
      <div class="history__sub-tabs">
        <button type="button" class="history__sub-tab" :class="{ 'is-active': batchSubTab === 'recent' }" @click="batchSubTab = 'recent'">最近改动</button>
        <button type="button" class="history__sub-tab" :class="{ 'is-active': batchSubTab === 'scan' }" @click="showScan">扫描批次</button>
      </div>
      <RecentChangesPanel v-show="batchSubTab === 'recent'" @drill="onDrill" />
      <ScanBatchPanel v-if="scanVisited" v-show="batchSubTab === 'scan'" />
    </div>
```

3d. 给 `ScanBatchPanel.vue` 具名（确保 `findComponent({ name: "ScanBatchPanel" })` 可匹配）。在 `ScanBatchPanel.vue` 的 `<script setup>` 顶部加：

```typescript
defineOptions({ name: "ScanBatchPanel" });
```

3e. 样式（`HistoryPage.vue` `<style scoped>` 内，复用 tab 视觉，加在 `.history__tabs` 规则附近）：

```css
.history__sub-tabs { display: flex; gap: var(--sp-2); margin-bottom: var(--sp-3); }
.history__sub-tab { padding: 4px 12px; background: transparent; border: 1px solid var(--line-soft); border-radius: var(--r-sm); color: var(--ink-2); cursor: pointer; }
.history__sub-tab.is-active { color: var(--ink-0); border-color: var(--accent); }
```

- [ ] **Step 4: 跑测试确认通过**

Run（`frontend/`）: `npm run test -- HistoryPage`
Expected: 全 PASS（含新子-tab 用例 + 既有用例）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.vue frontend/src/pages/history/HistoryPage.test.ts
git commit -m "feat(history): Phase 4b HistoryPage 批次记录子-tab 接线（scanVisited 持久挂载）"
```

---

## Task 8: no-analytics 守护扫描集纳入 scanBatches.ts

**Files:**
- Modify: `frontend/src/pages/history/no-analytics.test.ts:15`

- [ ] **Step 1: 改测试常量**

`no-analytics.test.ts` 的 `HISTORY_STORES` 数组加入 `scanBatches.ts`：

```typescript
const HISTORY_STORES = ["history.ts", "skuAnalytics.ts", "skuExtras.ts", "skuTimeline.ts", "recentChanges.ts", "scanBatches.ts"];
```

- [ ] **Step 2: 跑测试确认通过**

Run（`frontend/`）: `npm run test -- no-analytics`
Expected: PASS（扫描集含 `scanBatches.ts`，且该 store 不含 `/analytics/sku`）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/history/no-analytics.test.ts
git commit -m "test(history): Phase 4b no-analytics 扫描集纳入 scanBatches.ts"
```

---

## Task 9: 全量回归 + 收尾

- [ ] **Step 1: 前端全量测试 + 构建 + 类型生成 check**

Run（`frontend/`）: `npm run test` 然后 `npm run build`
Run（仓库根）: `python tools/gen_ts_types.py --check`
Expected: 全绿；build 成功；--check 退出码 0。

- [ ] **Step 2: 后端全量测试**

Run（仓库根）: `pytest tests/ -q`
Expected: 全 PASS（含新 `test_scan_batches_api.py` + `test_scan_history_routes.py`）。

- [ ] **Step 3: 本地浏览器验证（用户偏好：push 前本地验证）**

Run: `python server.py`（或 `./dev.ps1`），浏览器开 `http://127.0.0.1:5000/ui/history` → 批次记录 tab → 扫描批次子-tab → 验证列表/筛选/展开/下载链接。
Expected: 列表正常、多行可展开、下载链接可点（本地有 output_dir 数据时）。

- [ ] **Step 4: 收尾**

实现完成后按 `superpowers:finishing-a-development-branch`：push `feat/history-vue-phase4b` → 开 PR → 独立等 CI 双矩阵全绿 → squash merge。

---

## Self-Review 笔记

- **Spec 覆盖**：strict schema(T1) / 列表端点 + 401/500/null/cap(T2) / ZIP 端到端(T3) / TS 类型生成断言(T1 Step4) / normalize null 安全(T4) / store 代际+重试+reset+派生 employees+多行展开(T5) / panel 折叠+编码+空态+重试+a11y+onMounted(T6) / 子-tab 持久挂载(T7) / no-analytics(T8) / 旧端点回归(T3 + T9 Step2)。全部 spec 测试项有对应任务。
- **类型一致性**：`ScanBatchVM`/`ScanXlsxFileVM`（T4）在 store(T5)、panel(T6) 一致；store 暴露的 `ensureLoaded/loadBatches/setEmployeeFilter/toggleExpand/reset/employees/filteredBatches/expanded/error/loaded` 在 panel 与测试一致引用。
- **无占位符**：每步含实际代码/命令/预期。
- **已知风险**：`UnicodeDecodeError` 冒泡 500 为既有 service 风险，spec 明确排除出本期，计划不含修复任务。
