# 货号历史 Vue Phase 1（核心查询+变更溯源）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把货号历史页的查询核心（搜索 → 当前状态 → 历史事件线）迁到 Vue 独立栈 `/ui/history`，additive 不退役旧页，只吃 `GET /api/history`。

**Architecture:** 复刻 forecast-eval/briefing 范式：新增 canonical `GET /api/history?q=`（pydantic 校验，复用 `history_service.build_response`）→ gen_ts_types → 前端 normalize（单点收窄，discriminated union 七状态）+ pinia store + Vue 组件 → vue-router child route + nav 翻 routeName + 新页顶部「完整分析（旧版）」深链。**旧 SPA history 代码全保留**，加机械守护测试防误删/防接分析。

**Tech Stack:** Flask + pydantic、Vue 3 `<script setup>` + pinia + vue-router + vitest、pytest。

**spec：** `docs/superpowers/specs/2026-06-17-history-vue-phase1-design.md`（含 HC-1~HC-7 硬约束）。本计划在 worktree `C:\Dev\label-sync\.claude\worktrees\feat+history-vue-phase1`（分支 `worktree-feat+history-vue-phase1`，已含 forecast-eval merged）。pytest 用 `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest`（cwd=worktree 根）；前端 `cd frontend && npx vitest run <file>` / `npm run test` / `npm run typecheck`（node_modules 需先 `npm install`）。

**已核实事实（勿凭记忆）：**
- `build_response(q)` 返回三分支：命中 `{found:True, current:{...18字段}, events:[...]}`；模糊 `{found:False, fuzzy_matches:[...]}`；无 `{found:False}`。`current` 字段 = `find_record` 15 字段（barcode/model/location/is_active/source/created_at/updated_at/product_name_zh/product_name_local/erp_category_raw/erp_category_code/manual_grade/stock_price/sale_price/is_truly_discontinued）+ build_response 追加 `store_locations/warehouse_locations/unknown_locations`。
- 列类型（`app/models.py`）：`product_model:str(NN)`、`stockpile_location:str(NN)`、`manual_grade:int|None`、`stock_price/sale_price:float|None`、`is_truly_discontinued:bool(NN)`、`source/created_at/updated_at/product_name_*/erp_category_*:str|None`、`is_active` 经 `bool()` 转布尔。
- event：`at:str`、`change_type:str|None`、`source:str|None`（build_response 后可能仍 None）、`summary:str|None`（仅 inventory_events）、`changes:list`；change：`field:str`、`old/new:str|None`、`old_split/new_split`（仅 field==stockpile_location）。**所有时间戳是 Text 字符串，无 datetime 对象。**
- fuzzy：`{barcode:str, model:str, location:str, is_active:bool}`。
- `app/routes/history.py` 现有 `bp`（`/history`，旧 SPA 在用，**保留**）；`router.ts` 现有 briefing+forecast-eval 两个 child；`nav-items.ts` history 现为 `legacyPageId:"history"`。

---

## 文件结构

**后端：**
- 修改 `app/schemas_api.py` — 新增 `HistoryLocSplit/HistoryChange/HistoryEvent/HistoryCurrent/HistoryFuzzyMatch/HistorySearchData` + 入 `API_MODELS`
- 修改 `app/routes/history.py` — 加 `api_bp`（`/api/history`），复用 `build_response`
- 修改 `app/routes/__init__.py` — 注册 `history_api_bp`
- 创建 `tests/test_history_api.py` — 401/400/notfound/fuzzy/hit 契约
- 创建 `tests/test_history_legacy_preserved.py` — HC-1 机械守护

**类型生成：** 修改 `frontend/src/api/types.gen.ts`（gen_ts_types 产物）

**前端：**
- 创建 `frontend/src/pages/history/types.ts`（VM）
- 创建 `frontend/src/pages/history/normalize.ts` + `normalize.test.ts`
- 创建 `frontend/src/stores/history.ts` + `history.test.ts`
- 创建 `frontend/src/pages/history/HistoryPage.vue` + `HistoryPage.test.ts`
- 创建 `frontend/src/pages/history/no-analytics.test.ts` — HC-2 源码扫描守护
- 修改 `frontend/src/router.ts`、`frontend/src/shell/nav-items.ts`、`frontend/src/shell/SidebarNav.test.ts`

---

## Task 1: 后端 schema + /api/history 端点 + 注册 + 契约测试

**Files:** Modify `app/schemas_api.py`, `app/routes/history.py`, `app/routes/__init__.py`; Test `tests/test_history_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_history_api.py`（鉴权用 X-Upload-Token；seed 用 `app/services/history` 测试同款 `text()` 插入，proven 列）：

```python
"""GET /api/history?q=：货号历史 canonical 端点（pydantic 契约，Phase 1）。

只读，复用 history_service.build_response。鉴权镜像 tests/test_api_briefing.py。
seed 复用 tests/test_history_service.py 的 text() 插入（proven 列，sqlite/PG 通用）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _get(app, q):
    return app.test_client().get(
        f"/api/history?q={q}", headers={"X-Upload-Token": "test-token-123"}
    )


def _exec(sql, params):
    from app import db

    with db.get_engine().begin() as conn:
        conn.execute(text(sql), params)


def _seed_stockpile(barcode, model, loc="A22-04-04", is_active=1, source="scan_import"):
    _exec(
        "INSERT INTO stockpile (product_barcode, product_model, stockpile_location, is_active, source) "
        "VALUES (:b, :m, :l, :a, :s)",
        {"b": barcode, "m": model, "l": loc, "a": is_active, "s": source},
    )


def _seed_change(barcode, field, old, new, ctype, at):
    _exec(
        "INSERT INTO stockpile_changes "
        "(product_barcode, field_name, old_value, new_value, change_type, created_at) "
        "VALUES (:b, :f, :o, :n, :c, :at)",
        {"b": barcode, "f": field, "o": old, "n": new, "c": ctype, "at": at},
    )


def test_history_unauthenticated_returns_json_401(real_app):
    r = real_app.test_client().get("/api/history?q=x")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_history_empty_q_returns_400_not_schema(real_app):
    """HC-7：空 q 走 {ok:false,msg} 400，不走 HistorySearchData。"""
    r = _get(real_app, "")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_history_not_found(real_app):
    r = _get(real_app, "nosuchcode")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["found"] is False
    assert not body.get("fuzzy_matches")


def test_history_fuzzy_matches(real_app):
    _seed_stockpile("8299979002791", "ABC123")
    # 子串匹配但非精确 → fuzzy 分支
    r = _get(real_app, "ABC")
    assert r.status_code == 200
    body = r.get_json()
    assert body["found"] is False
    assert len(body["fuzzy_matches"]) >= 1
    assert body["fuzzy_matches"][0]["barcode"] == "8299979002791"


def test_history_exact_hit_with_events(real_app):
    _seed_stockpile("8299979002791", "ABC123", loc="A22-04-04", source="scan_import")
    _seed_change("8299979002791", "stockpile_location", "A22-04-04", "A22/X11", "update", "2026-04-25 16:52:43")
    r = _get(real_app, "8299979002791")
    assert r.status_code == 200
    body = r.get_json()
    assert body["found"] is True
    assert body["current"]["barcode"] == "8299979002791"
    assert body["current"]["model"] == "ABC123"
    assert body["current"]["store_locations"] == ["A22-04-04"]
    assert len(body["events"]) == 1
    ev = body["events"][0]
    assert ev["change_type"] == "update"
    # 库位变更 → change 带 old_split/new_split
    ch = ev["changes"][0]
    assert ch["field"] == "stockpile_location"
    assert ch["new_split"]["stores"] == ["A22"]
    assert ch["new_split"]["warehouses"] == ["X11"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest tests/test_history_api.py -v`
Expected: 401 PASS；其余 FAIL（端点 404 / `HistorySearchData` 未定义）。

- [ ] **Step 3: 加 pydantic schema**

在 `app/schemas_api.py`，`ForecastEvalData` 之后、`API_MODELS` 之前插入（字段/类型已逐字段核对 service+models）：

```python
class HistoryLocSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stores: list[str]
    warehouses: list[str]
    unknown: list[str]


class HistoryChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    old: str | None
    new: str | None
    old_split: HistoryLocSplit | None = None
    new_split: HistoryLocSplit | None = None


class HistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str
    change_type: str | None
    source: str | None
    summary: str | None = None
    changes: list[HistoryChange]


class HistoryCurrent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    model: str
    location: str
    is_active: bool
    source: str | None
    created_at: str | None
    updated_at: str | None
    product_name_zh: str | None
    product_name_local: str | None
    erp_category_raw: str | None
    erp_category_code: str | None
    manual_grade: int | None
    stock_price: float | None
    sale_price: float | None
    is_truly_discontinued: bool
    store_locations: list[str]
    warehouse_locations: list[str]
    unknown_locations: list[str]


class HistoryFuzzyMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    model: str
    location: str | None
    is_active: bool


class HistorySearchData(BaseModel):
    """GET /api/history?q= 的 200 响应。命中/模糊/无 三分支，缺省分支字段 Optional 兜。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    found: bool
    current: HistoryCurrent | None = None
    events: list[HistoryEvent] | None = None
    fuzzy_matches: list[HistoryFuzzyMatch] | None = None
```

`API_MODELS` 行末尾追加 `HistorySearchData`：
```python
API_MODELS: list[type[BaseModel]] = [BriefingData, MeData, ForecastEvalData, HistorySearchData]
```

- [ ] **Step 4: 加 api_bp 端点**

在 `app/routes/history.py` 末尾追加（保留现有 `bp`）：

```python
api_bp = Blueprint("api_history", __name__, url_prefix="/api/history")


@api_bp.get("")
def search():
    # HC-7：空 q 走 {ok,msg} 400，不进 schema
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "msg": "缺少查询参数"}), 400
    # 系统级异常不在此吞（对齐 /api/briefing/data）：让其冒泡到 Flask 通用 500，
    # 不把 SQL 文案泄给客户端。
    from app.schemas_api import HistorySearchData

    result = history_service.build_response(q)
    return jsonify(HistorySearchData.model_validate({"ok": True, **result}).model_dump())
```

- [ ] **Step 5: 注册蓝图**

`app/routes/__init__.py`：import 区加 `from app.routes.history import api_bp as history_api_bp`（保持 isort 顺序——`history` import 那几行附近，`ruff check --fix` 会自动排）；`register_routes` 体内、`app.register_blueprint(history_bp)` 之后加 `app.register_blueprint(history_api_bp)`。

- [ ] **Step 6: 跑测试 + ruff**

Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest tests/test_history_api.py -v`
Expected: 5 个测试全 PASS。
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m ruff check app/schemas_api.py app/routes/history.py app/routes/__init__.py tests/test_history_api.py`
Expected: All checks passed（若 import 序报 I001 → `ruff check --fix app/routes/__init__.py`）。

- [ ] **Step 7: 提交**
```bash
git add app/schemas_api.py app/routes/history.py app/routes/__init__.py tests/test_history_api.py
git commit -m "feat(history): canonical /api/history + pydantic schema (Phase 1)"
```

---

## Task 2: 重新生成 TS 类型

**Files:** Modify `frontend/src/api/types.gen.ts`

- [ ] **Step 1: 生成**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe tools/gen_ts_types.py`
Expected: `wrote .../types.gen.ts`

- [ ] **Step 2: --check + 确认新接口**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe tools/gen_ts_types.py --check`
Expected: 退出码 0。`git diff frontend/src/api/types.gen.ts` 应见 `HistoryLocSplit/HistoryChange/HistoryEvent/HistoryCurrent/HistoryFuzzyMatch/HistorySearchData` 接口。

- [ ] **Step 3: 提交**
```bash
git add frontend/src/api/types.gen.ts
git commit -m "chore(history): 同步 TS 类型 (gen_ts_types)"
```

---

## Task 3: 前端 VM 类型 + normalize（HC-5 单点收窄）

**Files:** Create `frontend/src/pages/history/types.ts`, `normalize.ts`, `normalize.test.ts`

- [ ] **Step 1: 写 VM 类型**

创建 `frontend/src/pages/history/types.ts`：

```typescript
export interface LocSplitVM { stores: string[]; warehouses: string[]; unknown: string[]; }
export interface ChangeVM {
  field: string;
  old: string | null;
  new: string | null;
  oldSplit: LocSplitVM | null;
  newSplit: LocSplitVM | null;
}
export interface EventVM {
  at: string;
  changeType: string | null;
  source: string | null;
  summary: string | null;
  changes: ChangeVM[];
}
// CurrentVM 仅暴露 Phase 1 UI 字段（HC-6：schema 校验完整 raw，VM 只取所需）
export interface CurrentVM {
  barcode: string;
  model: string;
  isTrulyDiscontinued: boolean;
  manualGrade: number | null;
  productNameZh: string | null;
  productNameLocal: string | null;
  storeLocations: string[];
  warehouseLocations: string[];
  unknownLocations: string[];
  salePrice: number | null;
  source: string | null;
  updatedAt: string | null;
}
export interface FuzzyVM { barcode: string; model: string; location: string | null; isActive: boolean; }
export type HistoryResult =
  | { kind: "notfound" }
  | { kind: "fuzzy"; matches: FuzzyVM[] }
  | { kind: "hit"; current: CurrentVM; events: EventVM[] };
```

- [ ] **Step 2: 写失败测试**

创建 `frontend/src/pages/history/normalize.test.ts`（hit 分支含库位 split 事件 + inventory summary 事件 + 空 events，钉死易漂移 shape）：

```typescript
import { describe, expect, it } from "vitest";
import type { HistorySearchData } from "../../api/types.gen";
import { normalizeHistory } from "./normalize";

describe("normalizeHistory", () => {
  it("found=false 无候选 → notfound", () => {
    const r = normalizeHistory({ ok: true, found: false } as HistorySearchData);
    expect(r.kind).toBe("notfound");
  });

  it("found=false 有候选 → fuzzy", () => {
    const r = normalizeHistory({
      ok: true, found: false,
      fuzzy_matches: [{ barcode: "B1", model: "M1", location: "A22", is_active: true }],
    } as HistorySearchData);
    expect(r.kind).toBe("fuzzy");
    if (r.kind === "fuzzy") {
      expect(r.matches[0].barcode).toBe("B1");
      expect(r.matches[0].isActive).toBe(true);
    }
  });

  it("found=true → hit，含库位 split 事件 + inventory summary 事件 + camelCase", () => {
    const r = normalizeHistory({
      ok: true, found: true,
      current: {
        barcode: "B1", model: "M1", location: "A22", is_active: true,
        source: "scan_import", created_at: "2026-01-01", updated_at: "2026-06-01",
        product_name_zh: "中文名", product_name_local: "local", erp_category_raw: "x",
        erp_category_code: "y", manual_grade: 8, stock_price: null, sale_price: 12.5,
        is_truly_discontinued: false,
        store_locations: ["A22"], warehouse_locations: ["X11"], unknown_locations: [],
      },
      events: [
        { at: "2026-04-25 16:52:43", change_type: "update", source: "scan_import", summary: null,
          changes: [{ field: "stockpile_location", old: "A22", new: "A22/X11",
            old_split: { stores: ["A22"], warehouses: [], unknown: [] },
            new_split: { stores: ["A22"], warehouses: ["X11"], unknown: [] } }] },
        { at: "2026-03-01", change_type: "sale", source: "inventory_events",
          summary: "销售 5 件 × €12.50（C001）", changes: [] },
      ],
    } as HistorySearchData);
    expect(r.kind).toBe("hit");
    if (r.kind === "hit") {
      expect(r.current.productNameZh).toBe("中文名");
      expect(r.current.manualGrade).toBe(8);
      expect(r.current.salePrice).toBe(12.5);
      expect(r.current.storeLocations).toEqual(["A22"]);
      expect(r.events[0].changes[0].newSplit?.warehouses).toEqual(["X11"]);
      expect(r.events[1].summary).toContain("销售 5 件");
      expect(r.events[1].changes).toEqual([]);
    }
  });

  it("found=true events 缺省 → hit events 为 []", () => {
    const r = normalizeHistory({
      ok: true, found: true,
      current: {
        barcode: "B1", model: "M1", location: "", is_active: true, source: null,
        created_at: null, updated_at: null, product_name_zh: null, product_name_local: null,
        erp_category_raw: null, erp_category_code: null, manual_grade: null,
        stock_price: null, sale_price: null, is_truly_discontinued: true,
        store_locations: [], warehouse_locations: [], unknown_locations: [],
      },
    } as HistorySearchData);
    expect(r.kind).toBe("hit");
    if (r.kind === "hit") expect(r.events).toEqual([]);
  });
});
```

- [ ] **Step 3: 跑测试确认失败**
Run: `cd frontend && npx vitest run src/pages/history/normalize.test.ts`
Expected: FAIL（`normalizeHistory` 不存在）

- [ ] **Step 4: 写 normalize**

创建 `frontend/src/pages/history/normalize.ts`：

```typescript
import type {
  HistoryChange, HistoryCurrent, HistoryEvent, HistoryFuzzyMatch,
  HistoryLocSplit, HistorySearchData,
} from "../../api/types.gen";
import type { ChangeVM, CurrentVM, EventVM, FuzzyVM, HistoryResult, LocSplitVM } from "./types";

function arr(x: unknown): unknown[] { return Array.isArray(x) ? x : []; }
function str(x: unknown): string | null { return typeof x === "string" ? x : null; }
function num(x: unknown): number | null { return typeof x === "number" && Number.isFinite(x) ? x : null; }
function strList(x: unknown): string[] { return arr(x).filter((s): s is string => typeof s === "string"); }

function split(s: HistoryLocSplit | null | undefined): LocSplitVM | null {
  if (!s) return null;
  return { stores: strList(s.stores), warehouses: strList(s.warehouses), unknown: strList(s.unknown) };
}

function change(c: HistoryChange): ChangeVM {
  return { field: c.field, old: str(c.old), new: str(c.new), oldSplit: split(c.old_split), newSplit: split(c.new_split) };
}

function event(e: HistoryEvent): EventVM {
  return {
    at: e.at, changeType: str(e.change_type), source: str(e.source), summary: str(e.summary),
    changes: arr(e.changes).map((c) => change(c as HistoryChange)),
  };
}

function current(c: HistoryCurrent): CurrentVM {
  return {
    barcode: c.barcode, model: c.model,
    isTrulyDiscontinued: c.is_truly_discontinued === true,
    manualGrade: num(c.manual_grade),
    productNameZh: str(c.product_name_zh), productNameLocal: str(c.product_name_local),
    storeLocations: strList(c.store_locations), warehouseLocations: strList(c.warehouse_locations),
    unknownLocations: strList(c.unknown_locations),
    salePrice: num(c.sale_price), source: str(c.source), updatedAt: str(c.updated_at),
  };
}

/** API 边界唯一收窄点（HC-5）：组件只吃 HistoryResult，不碰 raw。 */
export function normalizeHistory(raw: HistorySearchData): HistoryResult {
  if (raw.found === true && raw.current) {
    return { kind: "hit", current: current(raw.current), events: arr(raw.events).map((e) => event(e as HistoryEvent)) };
  }
  const matches = arr(raw.fuzzy_matches);
  if (matches.length) {
    return {
      kind: "fuzzy",
      matches: matches.map((m): FuzzyVM => {
        const f = m as HistoryFuzzyMatch;
        return { barcode: f.barcode, model: f.model, location: str(f.location), isActive: f.is_active === true };
      }),
    };
  }
  return { kind: "notfound" };
}
```

- [ ] **Step 5: 跑测试确认通过**
Run: `cd frontend && npx vitest run src/pages/history/normalize.test.ts`
Expected: PASS（4 个测试）

- [ ] **Step 6: 提交**
```bash
git add frontend/src/pages/history/types.ts frontend/src/pages/history/normalize.ts frontend/src/pages/history/normalize.test.ts
git commit -m "feat(history): VM 类型 + normalize 收窄层 (7 状态 result union)"
```

---

## Task 4: 前端 pinia store

**Files:** Create `frontend/src/stores/history.ts`, `history.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/stores/history.test.ts`：

```typescript
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(async () => ({
    ok: true, found: false,
    fuzzy_matches: [{ barcode: "B1", model: "M1", location: "A22", is_active: true }],
  })),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useHistoryStore } from "./history";

describe("history store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 命中填 result（fuzzy）并清 loading + 调对端点", async () => {
    const s = useHistoryStore();
    const p = s.load("ABC");
    expect(s.loading).toBe(true);
    await p;
    expect(s.loading).toBe(false);
    expect(s.result?.kind).toBe("fuzzy");
    expect(s.error).toBeNull();
    expect(vi.mocked(apiGet)).toHaveBeenCalledWith("/api/history?q=ABC");
  });

  it("load 失败 → error 填充，result 保持 null", async () => {
    const s = useHistoryStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load("x");
    expect(s.error).toBe("boom");
    expect(s.result).toBeNull();
  });

  it("未登录错误被吞掉，不污染 error", async () => {
    const s = useHistoryStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    await s.load("x");
    expect(s.error).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**
Run: `cd frontend && npx vitest run src/stores/history.test.ts`
Expected: FAIL（`useHistoryStore` 不存在）

- [ ] **Step 3: 写 store**

创建 `frontend/src/stores/history.ts`（HC-2 第一层防线：只调 `/api/history`）：

```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { HistorySearchData } from "../api/types.gen";
import { normalizeHistory } from "../pages/history/normalize";
import type { HistoryResult } from "../pages/history/types";

export const useHistoryStore = defineStore("history", () => {
  const result = ref<HistoryResult | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load(q: string) {
    loading.value = true;
    error.value = null;
    try {
      const raw = await apiGet<HistorySearchData>(`/api/history?q=${encodeURIComponent(q)}`);
      result.value = normalizeHistory(raw);
    } catch (e) {
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  return { result, loading, error, load };
});
```

- [ ] **Step 4: 跑测试确认通过**
Run: `cd frontend && npx vitest run src/stores/history.test.ts`
Expected: PASS（3 个测试）

- [ ] **Step 5: 提交**
```bash
git add frontend/src/stores/history.ts frontend/src/stores/history.test.ts
git commit -m "feat(history): pinia store"
```

---

## Task 5: 页面组件 HistoryPage.vue（七状态）

**Files:** Create `frontend/src/pages/history/HistoryPage.vue`, `HistoryPage.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/pages/history/HistoryPage.test.ts`（mock store plain object 范式）：

```typescript
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { HistoryResult } from "./types";

const state = {
  result: null as HistoryResult | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
};
vi.mock("../../stores/history", () => ({ useHistoryStore: () => state }));

import HistoryPage from "./HistoryPage.vue";

function reset() { state.result = null; state.loading = false; state.error = null; state.load = vi.fn(); }

describe("HistoryPage", () => {
  it("初始态：提示输入 + 「完整分析（旧版）」链接指向 /?page=history", () => {
    reset();
    const w = mount(HistoryPage);
    expect(w.text()).toContain("输入条码");
    const link = w.find("a.history__legacy-link");
    expect(link.exists()).toBe(true);
    expect(link.attributes("href")).toBe("/?page=history");
  });

  it("loading 态", () => {
    reset(); state.loading = true;
    expect(mount(HistoryPage).text()).toContain("查询中");
  });

  it("error 态", () => {
    reset(); state.error = "API 500: /api/history";
    expect(mount(HistoryPage).text()).toContain("API 500");
  });

  it("notfound 态", () => {
    reset(); state.result = { kind: "notfound" };
    expect(mount(HistoryPage).text()).toContain("未找到");
  });

  it("fuzzy 态：候选表，行点击触发 load(barcode)", async () => {
    reset();
    state.result = { kind: "fuzzy", matches: [{ barcode: "B1", model: "M1", location: "A22", isActive: true }] };
    const w = mount(HistoryPage);
    expect(w.text()).toContain("候选");
    await w.find("tr.history__fuzzy-row").trigger("click");
    expect(state.load).toHaveBeenCalledWith("B1");
  });

  it("hit 态：hero + 概况 + 事件线", () => {
    reset();
    state.result = {
      kind: "hit",
      current: {
        barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: 8,
        productNameZh: "中文名", productNameLocal: null,
        storeLocations: ["A22"], warehouseLocations: ["X11"], unknownLocations: [],
        salePrice: 12.5, source: "scan_import", updatedAt: "2026-06-01",
      },
      events: [{ at: "2026-04-25 16:52:43", changeType: "update", source: "scan_import", summary: null,
        changes: [{ field: "stockpile_location", old: "A22", new: "A22/X11", oldSplit: null, newSplit: null }] }],
    };
    const w = mount(HistoryPage);
    expect(w.text()).toContain("M1");
    expect(w.text()).toContain("中文名");
    expect(w.text()).toContain("A22");
    expect(w.text()).toContain("更新");
  });

  it("hit 但事件空 → 空态", () => {
    reset();
    state.result = {
      kind: "hit",
      current: {
        barcode: "B1", model: "M1", isTrulyDiscontinued: true, manualGrade: null,
        productNameZh: null, productNameLocal: null,
        storeLocations: [], warehouseLocations: [], unknownLocations: [],
        salePrice: null, source: null, updatedAt: null,
      },
      events: [],
    };
    expect(mount(HistoryPage).text()).toContain("暂无历史变更");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**
Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 写组件**

创建 `frontend/src/pages/history/HistoryPage.vue`：

```vue
<script setup lang="ts">
import { ref } from "vue";
import PageHeader from "../../components/PageHeader.vue";
import { useHistoryStore } from "../../stores/history";

const store = useHistoryStore();
const q = ref("");

const SOURCE_CN: Record<string, string> = {
  scan_import: "扫描导入", user_correction: "手动修正",
  system_export: "系统导出", inventory_events: "进销存",
};
const FIELD_CN: Record<string, string> = {
  stockpile_location: "库位", product_model: "型号",
  product_barcode: "条码", is_active: "上下架",
};
const CHANGE_TYPE_CN: Record<string, string> = {
  update: "更新", insert: "新增", deactivate: "下架",
  reactivate: "上架", sale: "销售", purchase: "采购",
};
const cn = (m: Record<string, string>, k: string | null) => (k ? m[k] ?? k : "");

function doSearch() {
  const v = q.value.trim();
  if (v) store.load(v);
}
function pickFuzzy(barcode: string) {
  q.value = barcode;
  store.load(barcode);
}
async function copyBarcode(bc: string) {
  // 内网 HTTP 非 secure context：navigator.clipboard 可能不可用 → execCommand 兜底
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(bc); return; } catch { /* fall through */ }
  }
  const ta = document.createElement("textarea");
  ta.value = bc; ta.style.position = "fixed"; ta.style.left = "-9999px";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch { /* ignore */ }
  document.body.removeChild(ta);
}
</script>

<template>
  <main class="history">
    <PageHeader title="货号历史" subtitle="核心查询 / 变更溯源（完整分析见旧版）" />

    <!-- HC-1 安全阀：完整分析旧版深链 -->
    <a class="history__legacy-link" href="/?page=history">查看完整分析（旧版）→</a>

    <div class="history__search">
      <input
        v-model="q" class="history__input" type="text" placeholder="输入条码 / 型号后查询"
        @keydown.enter="doSearch" />
      <button class="history__btn" type="button" @click="doSearch">⌕ 查询</button>
      <button class="history__btn history__btn--ghost" type="button" @click="q = ''; store.result = null">↺ 重置</button>
    </div>

    <p v-if="store.loading" class="history__msg">查询中…</p>
    <p v-else-if="store.error" class="history__error">{{ store.error }}</p>
    <p v-else-if="!store.result" class="history__msg">输入条码或型号后查询历史</p>

    <template v-else-if="store.result.kind === 'notfound'">
      <p class="history__msg">未找到 "{{ q }}"，请检查型号或条码是否正确</p>
    </template>

    <template v-else-if="store.result.kind === 'fuzzy'">
      <div class="history__fuzzy">
        <div class="history__fuzzy-hd">候选匹配（精确未命中，点击选择）</div>
        <table class="history__table">
          <thead><tr><th>条码</th><th>型号</th><th>当前位置</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="m in store.result.matches" :key="m.barcode" class="history__fuzzy-row" @click="pickFuzzy(m.barcode)">
              <td>{{ m.barcode }}</td><td>{{ m.model }}</td><td>{{ m.location ?? "—" }}</td>
              <td>{{ m.isActive ? "活跃" : "已下架" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <template v-else-if="store.result.kind === 'hit'">
      <div class="history__hero">
        <span class="history__model">{{ store.result.current.model || "—" }}</span>
        <span class="history__barcode">{{ store.result.current.barcode }}</span>
        <span class="history__pill" :class="store.result.current.isTrulyDiscontinued ? 'is-off' : 'is-on'">
          {{ store.result.current.isTrulyDiscontinued ? "已停售" : "在售" }}
        </span>
        <span v-if="store.result.current.manualGrade !== null" class="history__grade">{{ store.result.current.manualGrade }}</span>
        <button class="history__btn history__btn--ghost" type="button" @click="copyBarcode(store.result.current.barcode)">⎘ 复制</button>
      </div>

      <dl class="history__overview">
        <template v-if="store.result.current.productNameZh"><dt>品名</dt><dd>{{ store.result.current.productNameZh }}</dd></template>
        <template v-if="store.result.current.productNameLocal"><dt>本地品名</dt><dd>{{ store.result.current.productNameLocal }}</dd></template>
        <dt>店面位置</dt><dd>{{ store.result.current.storeLocations.join(", ") || "—" }}</dd>
        <dt>仓库位置</dt><dd>{{ store.result.current.warehouseLocations.join(", ") || "—" }}</dd>
        <template v-if="store.result.current.unknownLocations.length"><dt>其他位置</dt><dd>{{ store.result.current.unknownLocations.join(", ") }}</dd></template>
        <template v-if="store.result.current.salePrice !== null"><dt>售价</dt><dd>€{{ store.result.current.salePrice.toFixed(2) }}</dd></template>
        <dt>来源</dt><dd>{{ cn(SOURCE_CN, store.result.current.source) || "—" }}</dd>
        <dt>最后更新</dt><dd>{{ store.result.current.updatedAt ?? "—" }}</dd>
      </dl>

      <div class="history__timeline">
        <div class="history__timeline-hd">历史时间线</div>
        <p v-if="!store.result.events.length" class="history__msg">暂无历史变更</p>
        <div v-else>
          <div class="history__count">共 {{ store.result.events.length }} 次操作</div>
          <div v-for="(ev, i) in store.result.events" :key="i" class="history__evt">
            <div class="history__evt-head">
              <span class="history__evt-type">{{ cn(CHANGE_TYPE_CN, ev.changeType) }}</span>
              <span class="history__evt-src">{{ cn(SOURCE_CN, ev.source) }}</span>
              <span class="history__evt-time">{{ ev.at }}</span>
            </div>
            <div v-if="ev.summary" class="history__evt-detail">{{ ev.summary }}</div>
            <div v-else-if="ev.changes.length" class="history__evt-detail">
              <div v-for="(ch, j) in ev.changes" :key="j">
                <span class="history__evt-field">{{ cn(FIELD_CN, ch.field) }}</span>
                <code>{{ ch.old || "空" }}</code> → <code>{{ ch.new || "空" }}</code>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </main>
</template>

<style scoped>
.history { padding: var(--sp-6); max-width: 1100px; margin: 0 auto; }
.history__legacy-link { display: inline-block; margin-bottom: var(--sp-4); font-size: var(--fs-sm); color: var(--accent); }
.history__search { display: flex; gap: var(--sp-2); margin-bottom: var(--sp-4); }
.history__input { flex: 1; padding: var(--sp-2) var(--sp-3); border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: var(--surface-1, transparent); color: var(--ink-0); }
.history__btn { padding: var(--sp-2) var(--sp-4); border: 1px solid var(--line-soft); border-radius: var(--r-sm); cursor: pointer; color: var(--ink-0); }
.history__btn--ghost { background: transparent; }
.history__msg { color: var(--ink-2); }
.history__error { color: var(--error); }
.history__fuzzy-hd, .history__timeline-hd { font-size: var(--fs-sm); color: var(--ink-2); margin-bottom: var(--sp-2); }
.history__table { width: 100%; border-collapse: collapse; }
.history__table th, .history__table td { padding: var(--sp-2) var(--sp-3); text-align: left; border-bottom: 1px solid var(--line-soft); font-size: var(--fs-sm); }
.history__fuzzy-row { cursor: pointer; }
.history__fuzzy-row:hover { background: var(--accent-subtle); }
.history__hero { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: var(--sp-4); flex-wrap: wrap; }
.history__model { font-size: var(--fs-xl); font-weight: 700; }
.history__barcode { font-family: var(--mono); color: var(--ink-2); }
.history__pill { font-size: var(--fs-sm); padding: 2px 8px; border-radius: var(--r-sm); }
.history__pill.is-on { background: var(--accent-subtle); color: var(--accent); }
.history__pill.is-off { background: var(--warn-subtle); color: var(--warn); }
.history__grade { font-family: var(--mono); font-weight: 700; padding: 2px 8px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); }
.history__overview { display: grid; grid-template-columns: max-content 1fr; gap: var(--sp-2) var(--sp-4); margin-bottom: var(--sp-6); }
.history__overview dt { color: var(--ink-2); font-size: var(--fs-sm); }
.history__overview dd { font-family: var(--mono); }
.history__count { font-size: var(--fs-sm); color: var(--ink-2); margin-bottom: var(--sp-2); }
.history__evt { padding: var(--sp-2) 0; border-bottom: 1px solid var(--line-soft); }
.history__evt-head { display: flex; gap: var(--sp-3); font-size: var(--fs-sm); }
.history__evt-type { font-weight: 600; }
.history__evt-src, .history__evt-time { color: var(--ink-2); }
.history__evt-detail { margin-top: var(--sp-1); font-size: var(--fs-sm); }
.history__evt-field { color: var(--ink-3); margin-right: var(--sp-2); }
</style>
```

> token 以 `static/css/tokens.css` 为单源，对照 BriefingPage.vue / ForecastEvalPage.vue 用过的变量名；若某 token 不存在用最近同族替换，不新造、不写死颜色。

- [ ] **Step 4: 跑测试确认通过**
Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts`
Expected: PASS（7 个测试）

- [ ] **Step 5: 提交**
```bash
git add frontend/src/pages/history/HistoryPage.vue frontend/src/pages/history/HistoryPage.test.ts
git commit -m "feat(history): HistoryPage.vue 七状态页面组件"
```

---

## Task 6: 路由注册 + nav 翻 routeName

**Files:** Modify `frontend/src/router.ts`, `frontend/src/shell/nav-items.ts`, `frontend/src/shell/SidebarNav.test.ts`

- [ ] **Step 1: 加路由**

`frontend/src/router.ts` 的 `children` 数组里、forecast-eval 那行之后加：
```typescript
        { path: "history", name: "history", component: () => import("./pages/history/HistoryPage.vue") },
```

- [ ] **Step 2: 翻 nav-items**

`frontend/src/shell/nav-items.ts` 把 history 那行
```typescript
  { id: "history", label: "货号历史", icon: "history", code: "05", legacyPageId: "history" },
```
改为
```typescript
  { id: "history", label: "货号历史", icon: "history", code: "05", routeName: "history" },
```
并更新顶部注释里的"已迁"计数（现为简报+预测效果+货号历史 3 项，未迁 11 项）。

- [ ] **Step 3: 更新 SidebarNav 测试**

`frontend/src/shell/SidebarNav.test.ts` 第三个用例追加 history 断言（RouterLink + legacy href 不含 history）：
```typescript
    // history 已迁 → RouterLink
    expect(links.some((l) => (l.props("to") as { name?: string })?.name === "history")).toBe(true);
    expect(hrefs).not.toContain("/?page=history"); // 侧栏不再有 history 的 legacy <a>（旧版入口在 HistoryPage 页内，不在侧栏）
```
（注意：现有用例里 `expect(hrefs).toContain("/?page=history")` 那行若存在，需**删除**——history 已不再走 legacy nav。`/?page=restock` 等未迁项断言保留。）

- [ ] **Step 4: 前端全量 + typecheck**
Run: `cd frontend && npm run test`
Expected: 全绿
Run: `cd frontend && npm run typecheck`
Expected: 退出码 0

- [ ] **Step 5: 提交**
```bash
git add frontend/src/router.ts frontend/src/shell/nav-items.ts frontend/src/shell/SidebarNav.test.ts
git commit -m "feat(history): vue-router 路由 + nav 翻 routeName"
```

---

## Task 7: 机械守护测试（HC-1 旧页保留 + HC-2 不接分析）

**Files:** Create `tests/test_history_legacy_preserved.py`, `frontend/src/pages/history/no-analytics.test.ts`

- [ ] **Step 1: 写 HC-1 旧页保留守护（Python）**

创建 `tests/test_history_legacy_preserved.py`：

```python
"""HC-1 守护：货号历史 Phase 1 是 additive 迁移，旧 SPA history 必须保留。

防止后续误把旧页当 forecast_eval 那样退役——Phase 1 完整 parity 未达成前，
旧版完整分析页是用户唯一的分析入口。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_old_spa_history_nav_entry_preserved():
    store_js = (ROOT / "static" / "js" / "store.js").read_text(encoding="utf-8")
    assert '{ id: "history"' in store_js, "旧 SPA 侧栏 history 入口被删——违反 HC-1"


def test_old_spa_history_partial_preserved():
    assert (ROOT / "templates" / "partials" / "_page_history.html").exists(), "旧 history 模板被删——违反 HC-1"


def test_old_spa_history_js_preserved():
    assert (ROOT / "static" / "js" / "history.js").exists(), "旧 history.js 被删——违反 HC-1"
```

- [ ] **Step 2: 跑确认通过（旧文件本就在，应直接绿）**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest tests/test_history_legacy_preserved.py -v`
Expected: 3 PASS（守护测试，当前即应通过）

- [ ] **Step 3: 写 HC-2 不接分析守护（前端源码扫描）**

创建 `frontend/src/pages/history/no-analytics.test.ts`：

```typescript
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const storeFile = join(here, "..", "..", "stores", "history.ts");

// HC-2：Phase 1 不得引用 analytics/timeline 接口
const FORBIDDEN = ["/analytics/sku", "/timeline"];

function sources(): string[] {
  const files = readdirSync(here).filter((f) => f.endsWith(".ts") || f.endsWith(".vue"));
  const texts = files.map((f) => readFileSync(join(here, f), "utf-8"));
  texts.push(readFileSync(storeFile, "utf-8"));
  return texts;
}

describe("HC-2 Phase 1 不接分析/SVG 接口", () => {
  for (const needle of FORBIDDEN) {
    it(`pages/history 与 stores/history.ts 不含 "${needle}"`, () => {
      for (const src of sources()) expect(src.includes(needle)).toBe(false);
    });
  }
});
```

- [ ] **Step 4: 跑确认通过**
Run: `cd frontend && npx vitest run src/pages/history/no-analytics.test.ts`
Expected: PASS（2 个用例）。若失败说明误引入了 analytics/timeline 字符串 → 移除。

- [ ] **Step 5: 提交**
```bash
git add tests/test_history_legacy_preserved.py frontend/src/pages/history/no-analytics.test.ts
git commit -m "test(history): HC-1 旧页保留 + HC-2 不接分析 机械守护"
```

---

## Task 8: 全量验收

- [ ] **Step 1: 后端全量 + ruff**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全绿（新增 test_history_api 5 + test_history_legacy_preserved 3；既有不回归）
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m ruff check app/ tests/test_history_api.py tests/test_history_legacy_preserved.py`
Expected: All checks passed

- [ ] **Step 2: TS 漂移守护**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe tools/gen_ts_types.py --check`
Expected: 退出码 0

- [ ] **Step 3: 前端全量 + typecheck + build**
Run: `cd frontend && npm run test && npm run typecheck && npm run build`
Expected: vitest 全绿（含 normalize/store/page/no-analytics/SidebarNav）、vue-tsc 0、build 成功（emit HistoryPage chunk）

- [ ] **Step 4: 本地人工验证（feedback：前端改动本地测试后再 push）**

```
./dev.ps1 -Frontend   # 本地 PG + 热重载后端 :5000 + 前端 Vite :5173
```
浏览器开 `http://localhost:5173/ui/` → 侧栏点「货号历史」→ 验证：
- 走 `/ui/history`（不跳旧 SPA）；空库可搜索（输入随便字符 → notfound 态）
- 顶部「查看完整分析（旧版）→」链接点击跳 `/?page=history`（旧 SPA 满血页仍在）
- 旧 SPA（:5000 直开）侧栏「货号历史」仍在（HC-1）
- console 无 error

- [ ] **Step 5: 收尾**
- 更新 memory `project_frontend_decoupling.md`：货号历史 Phase 1（additive，C 入口）已迁。
- 按 `superpowers:finishing-a-development-branch`：feat 分支 + 开 PR（CI 双矩阵全绿）→ squash merge。
- 纪律：周三非 scraper 窗口可部署；前端 app 手动 redeploy（已掌握）。

---

## 自审记录

1. **spec 覆盖**：HC-1（Task6 nav 翻+不删旧页 / Task7 守护测试）、HC-2（Task4 store 只调 /api/history + Task7 源码扫描）、HC-3（Task5 subtitle 文案）、HC-4（Task5 七状态测试）、HC-5（Task3 normalize 单点）、HC-6（Task1 schema 逐字段+核实类型）、HC-7（Task1 401/400 不走 schema 测试）。入口策略 C（Task5 back-link + Task6 nav）。两类易漂移 event 样例（Task3 normalize.test hit 分支）。全部有对应 task。
2. **占位符扫描**：每个 code step 有完整可粘贴代码；唯一判断点 = Task5 token 名兜底（以 tokens.css 为单源）。无 TBD。
3. **类型一致性**：schema 字段 ↔ build_response 输出逐字段核对；VM 字段名（current.*/event.*/result.kind）在 types/normalize/store/组件/测试全程一致；store `load(q)` 签名一致；端点 `/api/history?q=` 在 store 与 store 测试一致。
