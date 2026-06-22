# 补货页 Vue 迁移 Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把补货决策页的「只读列表 + 筛选 + 排序 + KPI + 供应商概览」迁到独立 Vue 栈 `/ui/restock`，行为对旧页严格 1:1。

**Architecture:** 后端新增 2 个 strict `/api/restock/*` 瘦端点（投影白名单 + pydantic `extra="forbid"`）；前端在 `frontend/src/pages/restock/` 用纯函数 `filter/sort/kpi/supplier/cells/ordered/suppressed` + Vitest 锁契约，Vue 组件只做编排与渲染；旧页不动，双栈并存。

**Tech Stack:** Flask + pydantic v2（后端）、Vue 3 + vue-router + TypeScript + Vitest（前端）、Playwright（e2e）。

**Spec:** `docs/superpowers/specs/2026-06-20-restock-vue-phase1-design.md`（Approved rev5）。实现前通读该 spec，本计划的契约值以 spec 为准。

**纪律：** 遵守生产长任务窗口外操作 + 本地验证后再推（周一 14:00 scraper 窗口禁 push main）。全程在 `feat/restock-vue-phase1` 分支，squash merge 回 main。

---

## 文件结构

**后端：**
- Modify `app/schemas_api.py` — 新增 `RestockItem` / `RestockItemList` / `RestockSuppressedEntry` / `RestockSuppressedList`，注册进 `API_MODELS`
- Modify `app/routes/restock.py` — 新增 `api_bp`（`/api/restock`）+ 投影函数 + 2 端点
- Modify `app/routes/__init__.py` — 注册 `restock_api_bp`
- Modify `frontend/src/api/types.gen.ts` — `gen_ts_types.py` 生成（不手改）
- Create `tests/test_restock_api.py` — schema + 投影 + 端点测试

**前端纯函数（均 `frontend/src/pages/restock/`，各配 `.test.ts`）：**
- `constants.ts` `cells.ts` `filter.ts` `sort.ts` `kpi.ts` `supplier-summary.ts` `ordered-store.ts` `suppressed-normalize.ts` `normalize.ts` `types.ts`

**前端组件（`frontend/src/pages/restock/`）：**
- `RestockTable.vue` `FilterBar.vue` `SupplierOverview.vue` `KpiCards.vue` `RestockPage.vue`
- Modify `frontend/src/router.ts` — 加 `restock` child
- Create `frontend/src/pages/restock/no-analytics.test.ts` — 禁旧端点 guard

**e2e + 验收：**
- Create `e2e/test_restock_smoke.py` — 自建夹具 smoke
- Create `tools/bench_restock_api.py` — 后端 perf 脚本

---

## 阶段 A：后端 strict 端点（先行）

### Task 1: RestockSuppressedEntry/List schema + 端点

**Files:**
- Modify: `app/schemas_api.py`
- Modify: `app/routes/restock.py`
- Modify: `app/routes/__init__.py`
- Test: `tests/test_restock_api.py`（Create）

- [ ] **Step 1: 写 schema 失败测试**

```python
# tests/test_restock_api.py
import pytest
from pydantic import ValidationError
from app.schemas_api import RestockSuppressedEntry, RestockSuppressedList


def test_suppressed_entry_accepts_full_and_null_reason():
    e = RestockSuppressedEntry.model_validate(
        {"skipped_at": "2026-06-10 09:00:00", "reason": None, "days_left": 4}
    )
    assert e.days_left == 4


def test_suppressed_entry_rejects_extra_key():
    with pytest.raises(ValidationError):
        RestockSuppressedEntry.model_validate(
            {"skipped_at": "x", "reason": None, "days_left": 1, "junk": 1}
        )


def test_suppressed_list_empty_ok():
    m = RestockSuppressedList.model_validate({"ok": True, "items": {}})
    assert m.items == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_restock_api.py -v`
Expected: FAIL（ImportError: cannot import name 'RestockSuppressedEntry'）

- [ ] **Step 3: 加 schema**

```python
# app/schemas_api.py — 追加（保持文件既有 import 风格）
class RestockSuppressedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skipped_at: str
    reason: str | None
    days_left: int


class RestockSuppressedList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    items: dict[str, RestockSuppressedEntry]
```

并在文件末尾 `API_MODELS`（gen_ts_types 的注册表）中加入 `RestockSuppressedList`（含其嵌套 entry 会被一并导出）。若不确定 `API_MODELS` 形态，先 `grep -n "API_MODELS" app/schemas_api.py` 确认追加方式。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_restock_api.py -v`
Expected: PASS（3 个 schema 测试）

- [ ] **Step 5: 写端点失败测试**

```python
# tests/test_restock_api.py — 追加
def test_api_restock_suppressed_shape(client):
    # client 为既有 conftest fixture（登录态 Flask test client）
    resp = client.get("/api/restock/suppressed")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["items"], dict)
```

> 用既有 `tests/conftest.py` 的 `client` fixture（参照 `tests/test_restock_decisions.py` 的用法）。若该文件用 `self.client`，照其风格改写为同款。

- [ ] **Step 6: 运行确认失败**

Run: `pytest tests/test_restock_api.py::test_api_restock_suppressed_shape -v`
Expected: FAIL（404，端点未建）

- [ ] **Step 7: 加 api_bp + suppressed 端点**

```python
# app/routes/restock.py — 顶部已 import svc / get_session；追加：
from app.schemas_api import RestockSuppressedList

api_bp = Blueprint("api_restock", __name__, url_prefix="/api/restock")


@api_bp.get("/suppressed")
def api_suppressed():
    with get_session() as s:
        items = svc.list_suppressed(s)
    payload = {"ok": True, "items": items}
    return jsonify(RestockSuppressedList.model_validate(payload).model_dump())
```

```python
# app/routes/__init__.py — 在 restock_bp 注册旁追加
from app.routes.restock import api_bp as restock_api_bp
...
app.register_blueprint(restock_api_bp)
```

> 确认 `app/routes/restock.py` 现有 `bp` 的 import 行（`from app.routes.restock import bp as restock_bp`）所在，照同款加 `restock_api_bp`。

- [ ] **Step 8: 运行确认通过**

Run: `pytest tests/test_restock_api.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app/schemas_api.py app/routes/restock.py app/routes/__init__.py tests/test_restock_api.py
git commit -m "feat(restock): GET /api/restock/suppressed strict 端点"
```

---

### Task 2: RestockItem schema（白名单 + 非空 + Literal origin）

**Files:**
- Modify: `app/schemas_api.py`
- Test: `tests/test_restock_api.py`

- [ ] **Step 1: 写 schema 测试（满字段 / 拒非空 null / 拒额外键 / origin 枚举）**

```python
# tests/test_restock_api.py — 追加
from app.schemas_api import RestockItem

def _full_item():
    return {
        "barcode": "5201234567890", "model": "ABC123", "name_zh": "测试品",
        "origin": "FOREIGN", "supplier_id": "GR001",
        "is_truly_discontinued": False, "is_new_item": False,
        "qty_total": 100, "weeks_of_cover": 8.0,
        "weekly_velocity": 12.5, "weekly_revenue": 80.0,
        "margin_pct": 35.0, "margin_source": "purchase", "margin_price_source": "master",
        "master_stock_price_eur": 3.2, "master_sale_price_eur": 6.0,
        "last_purchase_unit_price": 3.0, "sale_net_avg": 5.8,
        "weekly_qty_12w": [0,1,2,3,4,5,6,7,8,9,10,11], "trend_slope_pct_per_week": 1.2,
        "realized_profit_eur": 500.0, "inventory_cost_value_eur": 320.0,
        "last_purchase_days_ago": 20, "last_purchase_at": "2026-05-30",
        "restock_qty_p50": 50, "restock_qty_p98": 90, "restock_source": "p98_hist",
        "last_purchase_qty": 60, "urgency_score": 72, "stockout_zero_weeks_last8": 0,
    }


def test_restock_item_full_ok():
    m = RestockItem.model_validate(_full_item())
    assert m.urgency_score == 72


def test_restock_item_nullable_fields_accept_none():
    it = _full_item()
    for k in ["model","name_zh","supplier_id","qty_total","weeks_of_cover",
              "margin_pct","margin_source","margin_price_source",
              "master_stock_price_eur","master_sale_price_eur",
              "last_purchase_unit_price","sale_net_avg","trend_slope_pct_per_week",
              "realized_profit_eur","inventory_cost_value_eur","last_purchase_days_ago",
              "last_purchase_at","restock_qty_p50","restock_qty_p98","restock_source",
              "last_purchase_qty","urgency_score"]:
        d = _full_item(); d[k] = None
        RestockItem.model_validate(d)  # 不抛


@pytest.mark.parametrize("field", [
    "origin","weekly_velocity","weekly_revenue","weekly_qty_12w",
    "stockout_zero_weeks_last8","is_truly_discontinued","is_new_item","barcode",
])
def test_restock_item_nonnull_fields_reject_none(field):
    d = _full_item(); d[field] = None
    with pytest.raises(ValidationError):
        RestockItem.model_validate(d)


def test_restock_item_rejects_extra_key():
    d = _full_item(); d["urgency_breakdown"] = {"velocity": 30}
    with pytest.raises(ValidationError):
        RestockItem.model_validate(d)


@pytest.mark.parametrize("bad", ["HZ", "XX", "GR"])
def test_restock_item_origin_enum_rejects_unknown_value(bad):
    d = _full_item(); d["origin"] = bad
    with pytest.raises(ValidationError):
        RestockItem.model_validate(d)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_restock_api.py -k restock_item -v`
Expected: FAIL（ImportError: RestockItem）

- [ ] **Step 3: 加 RestockItem schema**

```python
# app/schemas_api.py — 追加。typing 顶部加 from typing import Literal
class RestockItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    model: str | None
    name_zh: str | None
    origin: Literal["FOREIGN", "CN", "unknown"]
    supplier_id: str | None
    is_truly_discontinued: bool
    is_new_item: bool
    qty_total: int | None
    weeks_of_cover: float | None
    weekly_velocity: float
    weekly_revenue: float
    margin_pct: float | None
    margin_source: str | None
    margin_price_source: str | None
    master_stock_price_eur: float | None
    master_sale_price_eur: float | None
    last_purchase_unit_price: float | None
    sale_net_avg: float | None
    weekly_qty_12w: list[int]
    trend_slope_pct_per_week: float | None
    realized_profit_eur: float | None
    inventory_cost_value_eur: float | None
    last_purchase_days_ago: int | None
    last_purchase_at: str | None
    restock_qty_p50: int | None
    restock_qty_p98: int | None
    restock_source: str | None
    last_purchase_qty: int | None
    urgency_score: int | None
    stockout_zero_weeks_last8: int


class RestockItemList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    total: int
    items: list[RestockItem]
```

`API_MODELS` 追加 `RestockItemList`。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_restock_api.py -k restock_item -v`
Expected: PASS（全部 parametrize 分支）

- [ ] **Step 5: Commit**

```bash
git add app/schemas_api.py tests/test_restock_api.py
git commit -m "feat(restock): RestockItem strict schema（白名单+非空+Literal origin）"
```

---

### Task 3: 投影函数 + GET /api/restock/items

**Files:**
- Modify: `app/routes/restock.py`
- Test: `tests/test_restock_api.py`

- [ ] **Step 1: 写投影 key 集测试**

```python
# tests/test_restock_api.py — 追加
from app.routes.restock import _project_item, _ITEM_KEYS

def test_project_item_key_set_equals_whitelist():
    # 喂一个超集 dict（含 drawer-only 胖字段），投影后 key 必须恰好等于白名单
    fat = {**_full_item(), "urgency_breakdown": {"velocity": 30}, "total_qty": 5,
           "retail_qty_26w": 3, "lifetime_invested_eur": 99.0}
    out = _project_item(fat)
    assert set(out.keys()) == set(_ITEM_KEYS)
    assert "urgency_breakdown" not in out
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_restock_api.py::test_project_item_key_set_equals_whitelist -v`
Expected: FAIL（ImportError: _project_item）

- [ ] **Step 3: 加投影函数 + items 端点**

```python
# app/routes/restock.py — 追加
from app.schemas_api import RestockItem, RestockItemList  # 与 Task1 import 合并
from app.services.analytics import list_sku_summary  # 文件顶部已 import 之一，复用

_ITEM_KEYS = tuple(RestockItem.model_fields.keys())  # 白名单单一真源 = schema 字段


def _project_item(row: dict) -> dict:
    return {k: row.get(k) for k in _ITEM_KEYS}


@api_bp.get("/items")
def api_items():
    rows = list_sku_summary()
    items = [_project_item(r) for r in rows]
    payload = {"ok": True, "total": len(items), "items": items}
    return jsonify(RestockItemList.model_validate(payload).model_dump())
```

> `_ITEM_KEYS` 用 `RestockItem.model_fields` 派生，保证投影白名单与 schema **同源不漂移**。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_restock_api.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 写端点冒烟（自建 1 行夹具，不依赖全库）**

```python
# tests/test_restock_api.py — 追加。复用 conftest 的 DB seed 工具 seed 一条 SKU。
def test_api_restock_items_returns_projected_rows(client, seed_one_sku):
    resp = client.get("/api/restock/items")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True and data["total"] >= 1
    row = data["items"][0]
    assert set(row.keys()) == set(_ITEM_KEYS)
```

> `seed_one_sku`：若 conftest 无现成 fixture，照 `tests/test_sku_summary.py` 的 seed 方式写一个最小 SKU（走 SQLAlchemy，禁裸 sqlite3）。

- [ ] **Step 6: 运行确认通过**

Run: `pytest tests/test_restock_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routes/restock.py tests/test_restock_api.py
git commit -m "feat(restock): GET /api/restock/items 投影白名单 + strict 校验"
```

---

### Task 4: 生成 TS 类型

**Files:**
- Modify: `frontend/src/api/types.gen.ts`（生成）

- [ ] **Step 1: 重新生成类型**

Run: `python tools/gen_ts_types.py`
Expected: `frontend/src/api/types.gen.ts` 出现 `RestockItem` / `RestockItemList` / `RestockSuppressedEntry` / `RestockSuppressedList`。

- [ ] **Step 2: 漂移检查**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/types.gen.ts
git commit -m "chore(restock): gen_ts_types 同步 RestockItem 等类型"
```

---

## 阶段 B：前端纯函数（TDD，全在 `frontend/src/pages/restock/`）

> 所有前端测试：`cd frontend && npm test`（Vitest）。单测试文件：`cd frontend && npx vitest run src/pages/restock/<name>.test.ts`。

### Task 5: constants.ts

**Files:**
- Create: `frontend/src/pages/restock/constants.ts`
- Test: `frontend/src/pages/restock/constants.test.ts`

- [ ] **Step 1: 写测试**

```ts
import { describe, it, expect } from "vitest";
import { INITIAL_FILTER, RESET_FILTER, THRESH, VISIBLE_CAP } from "./constants";

describe("constants", () => {
  it("初始默认 ≠ 重置目标", () => {
    expect(INITIAL_FILTER.origin).toBe("FOREIGN");
    expect(INITIAL_FILTER.coverMax).toBe(4);
    expect(RESET_FILTER.origin).toBe("");
    expect(RESET_FILTER.coverMax).toBe(null);
  });
  it("阈值锁定", () => {
    expect(THRESH.HOT_URGENCY).toBe(70);
    expect(THRESH.COVER_CAP).toBe(13.0);
    expect(THRESH.SUPPLIER_OVERVIEW_TOP).toBe(5);
    expect(THRESH.ORDERED_EXPIRY_DAYS).toBe(30);
    expect(VISIBLE_CAP).toBe(500);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/pages/restock/constants.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```ts
// frontend/src/pages/restock/constants.ts
export interface FilterState {
  origin: string;
  views: { active: boolean; new: boolean; disc: boolean };
  band: string;
  coverMax: number | null;
  coverThreshold: number;
  supplier: string | null;
  show_ordered: boolean;
  search: string;
}

export const INITIAL_FILTER: FilterState = {
  origin: "FOREIGN",
  views: { active: true, new: false, disc: false },
  band: "all",
  coverMax: 4,
  coverThreshold: 4,
  supplier: null,
  show_ordered: false,
  search: "",
};

// 旧页「重置」非恢复初始默认：origin="" / coverMax=null（spec §6）
export const RESET_FILTER: FilterState = {
  origin: "",
  views: { active: true, new: false, disc: false },
  band: "all",
  coverMax: null,
  coverThreshold: 4,
  supplier: null,
  show_ordered: false,
  search: "",
};

export const THRESH = {
  HOT_URGENCY: 70,
  OVERSTOCK_WEEKS: 20,
  COVER_CAP: 13.0,
  SUPPLIER_OVERVIEW_HOT: 70,
  SUPPLIER_OVERVIEW_TOP: 5,
  ORDERED_EXPIRY_DAYS: 30,
} as const;

export const VISIBLE_CAP = 500;
export const INITIAL_SORT = { key: "urgency_score", dir: "desc" } as const;
```

- [ ] **Step 4: 运行确认通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/constants.test.ts
cd .. && git add frontend/src/pages/restock/constants.* && git commit -m "feat(restock-ui): constants 真源（初始/重置/阈值）"
```

---

### Task 6: cells.ts（纯展示格式化）

**Files:**
- Create: `frontend/src/pages/restock/cells.ts` + `.test.ts`

- [ ] **Step 1: 写测试（锁所有分级边界）**

```ts
import { describe, it, expect } from "vitest";
import { fmt, fmtDays, coverTone, urgencyLevel, wocLevel, marginLevel } from "./cells";

describe("cells", () => {
  it("fmt null → 破折号；千分位", () => {
    expect(fmt(null)).toBe("—");
    expect(fmt(1234)).toBe("1,234");
  });
  it("fmtDays 分档", () => {
    expect(fmtDays(null)).toBe("—");
    expect(fmtDays(0)).toBe("今天");
    expect(fmtDays(5)).toBe("5 天前");
    expect(fmtDays(40)).toBe("1 月前");
    expect(fmtDays(400)).toBe("1.1 年前");
  });
  it("coverTone 阈值（T=4）", () => {
    expect(coverTone(null, 4)).toBe("ok");
    expect(coverTone(1, 4)).toBe("crit");   // <0.5T=2
    expect(coverTone(3, 4)).toBe("low");    // <T=4
    expect(coverTone(6, 4)).toBe("ok");     // <2T=8
    expect(coverTone(9, 4)).toBe("high");   // ≥2T
  });
  it("urgencyLevel", () => {
    expect(urgencyLevel(70)).toBe("high");
    expect(urgencyLevel(40)).toBe("mid");
    expect(urgencyLevel(39)).toBe("low");
  });
  it("wocLevel", () => {
    expect(wocLevel(2)).toBe("crit");
    expect(wocLevel(4)).toBe("warn");
    expect(wocLevel(20)).toBe("cold");
    expect(wocLevel(10)).toBe("");
  });
  it("marginLevel", () => {
    expect(marginLevel(50)).toBe("great");
    expect(marginLevel(30)).toBe("good");
    expect(marginLevel(10)).toBe("meh");
    expect(marginLevel(9)).toBe("bad");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/pages/restock/cells.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现（移植 restock.js:93/101/189/148/178/232）**

```ts
// frontend/src/pages/restock/cells.ts
export function fmt(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
}

export function fmtDays(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 1) return "今天";
  if (n < 30) return `${n} 天前`;
  if (n < 365) return `${Math.round(n / 30)} 月前`;
  return `${(n / 365).toFixed(1)} 年前`;
}

export function coverTone(w: number | null | undefined, T: number): string {
  if (w === null || w === undefined) return "ok";
  if (w < T * 0.5) return "crit";
  if (w < T) return "low";
  if (w < T * 2) return "ok";
  return "high";
}

export function urgencyLevel(score: number): "high" | "mid" | "low" {
  return score >= 70 ? "high" : score >= 40 ? "mid" : "low";
}

export function wocLevel(woc: number): string {
  if (woc <= 2) return "crit";
  if (woc <= 4) return "warn";
  if (woc >= 20) return "cold";
  return "";
}

export function marginLevel(m: number): string {
  if (m >= 50) return "great";
  if (m >= 30) return "good";
  if (m >= 10) return "meh";
  return "bad";
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/cells.test.ts
cd .. && git add frontend/src/pages/restock/cells.* && git commit -m "feat(restock-ui): cells 纯展示格式化"
```

---

### Task 7: filter.ts（filterPredicate 1:1 + skipSupplier + band=ok null）

**Files:**
- Create: `frontend/src/pages/restock/filter.ts` + `.test.ts`

- [ ] **Step 1: 写测试（红队 FOREIGN/CN、band 顺序、coverMax 仅 active、band=ok 保留 null）**

```ts
import { describe, it, expect } from "vitest";
import { filterPredicate, type FilterCtx } from "./filter";
import { INITIAL_FILTER, type FilterState } from "./constants";

const EMPTY: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set() };
function item(p: Partial<any> = {}): any {
  return {
    barcode: "b1", model: "M1", name_zh: "名", origin: "FOREIGN", supplier_id: "GR1",
    is_truly_discontinued: false, is_new_item: false, urgency_score: 80,
    weeks_of_cover: 3, ...p,
  };
}
function f(p: Partial<FilterState> = {}): FilterState {
  return { ...INITIAL_FILTER, ...p };
}

describe("filterPredicate", () => {
  it("ordered 隐藏（show_ordered=false）", () => {
    expect(filterPredicate(item(), f(), { ...EMPTY, ordered: { b1: {} } })).toBe(false);
  });
  it("suppressed 默认隐藏；skipped band 只看 suppressed", () => {
    const ctx = { ...EMPTY, suppressed: { b1: {} } };
    expect(filterPredicate(item(), f(), ctx)).toBe(false);
    expect(filterPredicate(item(), f({ band: "skipped" }), ctx)).toBe(true);
    expect(filterPredicate(item({ barcode: "b2" }), f({ band: "skipped" }), ctx)).toBe(false);
  });
  it("origin 不匹配剔除", () => {
    expect(filterPredicate(item({ origin: "CN" }), f({ origin: "FOREIGN" }), EMPTY)).toBe(false);
  });
  it("coverMax 仅在 active 视图生效", () => {
    const it = item({ weeks_of_cover: 8 });
    expect(filterPredicate(it, f({ coverMax: 4 }), EMPTY)).toBe(false);
    // 非 active 视图（只看 disc）不应用 coverMax
    const disc = item({ weeks_of_cover: 8, is_truly_discontinued: true });
    expect(filterPredicate(disc, f({ coverMax: 4, views: { active: false, new: false, disc: true } }), EMPTY)).toBe(true);
  });
  it("band=ok 保留 urgency_score=null 行", () => {
    expect(filterPredicate(item({ urgency_score: null }), f({ band: "ok", origin: "" }), EMPTY)).toBe(true);
  });
  it("skipSupplier 忽略 supplier 过滤", () => {
    const it = item({ supplier_id: "GR2" });
    expect(filterPredicate(it, f({ supplier: "GR1" }), EMPTY)).toBe(false);
    expect(filterPredicate(it, f({ supplier: "GR1" }), EMPTY, { skipSupplier: true })).toBe(true);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/pages/restock/filter.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现（移植 restock.js:285-330 逐条）**

```ts
// frontend/src/pages/restock/filter.ts
import type { FilterState } from "./constants";

export interface FilterCtx {
  ordered: Record<string, unknown>;
  suppressed: Record<string, unknown>;
  selected: Set<string>;
}

export function filterPredicate(
  it: any, fil: FilterState, ctx: FilterCtx, opts: { skipSupplier?: boolean } = {},
): boolean {
  const isOrdered = it.barcode in ctx.ordered;
  if (fil.show_ordered) return isOrdered;
  if (isOrdered) return false;

  const isSuppressed = it.barcode in ctx.suppressed;
  if (fil.band === "skipped") {
    if (!isSuppressed) return false;
  } else if (isSuppressed) {
    return false;
  }
  if (fil.origin && it.origin !== fil.origin) return false;
  if (!opts.skipSupplier && fil.supplier && it.supplier_id !== fil.supplier) return false;
  if (fil.search) {
    const q = fil.search.toLowerCase();
    const hay = `${it.supplier_id ?? ""} ${it.barcode ?? ""} ${it.model ?? ""} ${it.name_zh ?? ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  const vw = fil.views;
  const isActive = !it.is_truly_discontinued && !it.is_new_item;
  const viewMatch =
    (vw.active && isActive) || (vw.new && it.is_new_item) || (vw.disc && it.is_truly_discontinued);
  if (!viewMatch) return false;

  const score = it.urgency_score ?? -1;
  switch (fil.band) {
    case "urgent": if (score < 70) return false; break;
    case "watch": if (score < 40 || score >= 70) return false; break;
    case "ok": if (score >= 40) return false; break;
    case "flagged": if (!ctx.selected.has(it.barcode)) return false; break;
    default: break;
  }
  if (fil.coverMax !== null && vw.active) {
    if (it.weeks_of_cover !== null && it.weeks_of_cover !== undefined && it.weeks_of_cover > fil.coverMax) {
      return false;
    }
  }
  return true;
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/filter.test.ts
cd .. && git add frontend/src/pages/restock/filter.* && git commit -m "feat(restock-ui): filterPredicate 1:1（skipSupplier + band null 口径）"
```

---

### Task 8: sort.ts（applySort + 审计偏离 双 null→0）

**Files:**
- Create: `frontend/src/pages/restock/sort.ts` + `.test.ts`

- [ ] **Step 1: 写测试**

```ts
import { describe, it, expect } from "vitest";
import { applySort } from "./sort";

describe("applySort", () => {
  it("desc 数值；null 沉底", () => {
    const r = applySort([{ s: 1 }, { s: null }, { s: 3 }], { key: "s", dir: "desc" });
    expect(r.map((x) => x.s)).toEqual([3, 1, null]);
  });
  it("asc 数值", () => {
    const r = applySort([{ s: 3 }, { s: 1 }], { key: "s", dir: "asc" });
    expect(r.map((x) => x.s)).toEqual([1, 3]);
  });
  it("审计偏离：两边 null 返回 0（稳定相对序保持输入顺序）", () => {
    const a = { s: null, id: 1 }, b = { s: null, id: 2 };
    const r = applySort([a, b], { key: "s", dir: "desc" });
    expect(r.map((x) => x.id)).toEqual([1, 2]);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/pages/restock/sort.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现（移植 restock.js:340，含双 null 修复）**

```ts
// frontend/src/pages/restock/sort.ts
export interface SortState { key: string; dir: "asc" | "desc"; }

export function applySort<T extends Record<string, any>>(items: T[], sort: SortState): T[] {
  const { key, dir } = sort;
  const mul = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = a[key], bv = b[key];
    const an = av === null || av === undefined;
    const bn = bv === null || bv === undefined;
    if (an && bn) return 0;        // 审计偏离：旧实现返回 1（违反反对称性），spec §6
    if (an) return 1;              // null 沉底
    if (bn) return -1;
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/sort.test.ts
cd .. && git add frontend/src/pages/restock/sort.* && git commit -m "feat(restock-ui): applySort（null 沉底 + 审计修复双 null→0）"
```

---

### Task 9: kpi.ts

**Files:**
- Create: `frontend/src/pages/restock/kpi.ts` + `.test.ts`

- [ ] **Step 1: 写测试（充足排除 null；spend 口径）**

```ts
import { describe, it, expect } from "vitest";
import { computeKpi } from "./kpi";
import { filterPredicate, type FilterCtx } from "./filter";
import { INITIAL_FILTER } from "./constants";

const ctx: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set() };
function it_(p: any = {}) {
  return { barcode: "b" + Math.random(), is_truly_discontinued: false, is_new_item: false,
    urgency_score: 80, restock_qty_p50: 10, last_purchase_unit_price: 2,
    master_stock_price_eur: 1, origin: "FOREIGN", weeks_of_cover: 1, ...p };
}

describe("computeKpi", () => {
  it("分档计数 + 充足排除 null", () => {
    const items = [it_({ urgency_score: 80 }), it_({ urgency_score: 50 }),
                   it_({ urgency_score: 10 }), it_({ urgency_score: null })];
    const k = computeKpi(items, INITIAL_FILTER, ctx, filterPredicate);
    expect(k.hot).toBe(1); expect(k.watch).toBe(1); expect(k.ok).toBe(1); // null 不计入 ok
  });
  it("spend = Σ可见 p50×(last_pp ?? master_pp)", () => {
    const k = computeKpi([it_({ restock_qty_p50: 10, last_purchase_unit_price: 2 })],
      INITIAL_FILTER, ctx, filterPredicate);
    expect(k.spend).toBe(20);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/pages/restock/kpi.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现（移植 restock.js:1113-1138；不输出已标记）**

```ts
// frontend/src/pages/restock/kpi.ts
import type { FilterState } from "./constants";
import type { FilterCtx } from "./filter";

export interface Kpi { hot: number; watch: number; ok: number; spend: number; }

export function computeKpi(
  items: any[], fil: FilterState, ctx: FilterCtx,
  predicate: (it: any, f: FilterState, c: FilterCtx, o?: any) => boolean,
): Kpi {
  const pool = items.filter(
    (it) => !it.is_truly_discontinued && !it.is_new_item &&
      !(it.barcode in ctx.ordered) && !(it.barcode in ctx.suppressed),
  );
  const hot = pool.filter((it) => (it.urgency_score ?? -1) >= 70).length;
  const watch = pool.filter((it) => { const s = it.urgency_score ?? -1; return s >= 40 && s < 70; }).length;
  const ok = pool.filter((it) => { const s = it.urgency_score ?? -1; return s >= 0 && s < 40; }).length;
  let spend = 0;
  for (const it of items.filter((x) => predicate(x, fil, ctx))) {
    const qty = it.restock_qty_p50;
    const cost = it.last_purchase_unit_price ?? it.master_stock_price_eur;
    if (qty && cost) spend += qty * cost;
  }
  return { hot, watch, ok, spend };
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/kpi.test.ts
cd .. && git add frontend/src/pages/restock/kpi.* && git commit -m "feat(restock-ui): computeKpi（充足排除 null + spend 口径）"
```

---

### Task 10: supplier-summary.ts（skipSupplier 池）

**Files:**
- Create: `frontend/src/pages/restock/supplier-summary.ts` + `.test.ts`

- [ ] **Step 1: 写测试（红队：FOREIGN 筛选下 CN 供应商不出现）**

```ts
import { describe, it, expect } from "vitest";
import { supplierSummary, allSuppliersSummary } from "./supplier-summary";
import { filterPredicate, type FilterCtx } from "./filter";
import { INITIAL_FILTER } from "./constants";

const ctx: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set() };
function it_(p: any) {
  return { barcode: "b" + Math.random(), is_truly_discontinued: false, is_new_item: false,
    weeks_of_cover: 1, ...p };
}

describe("supplier-summary", () => {
  it("红队：origin=FOREIGN 时 CN 供应商不漏出", () => {
    const items = [
      it_({ origin: "FOREIGN", supplier_id: "GR1", urgency_score: 90 }),
      it_({ origin: "CN", supplier_id: "CN9", urgency_score: 95 }),
    ];
    const hot = supplierSummary(items, { ...INITIAL_FILTER, origin: "FOREIGN" }, ctx, filterPredicate);
    expect(hot.map((s) => s.supplier_id)).toEqual(["GR1"]);
    expect(hot.find((s) => s.supplier_id === "CN9")).toBeUndefined();
  });
  it("折叠按 hot_count desc；展开按 max desc 全量", () => {
    const items = [
      it_({ origin: "FOREIGN", supplier_id: "A", urgency_score: 90 }),
      it_({ origin: "FOREIGN", supplier_id: "A", urgency_score: 80 }),
      it_({ origin: "FOREIGN", supplier_id: "B", urgency_score: 60 }),
    ];
    const hot = supplierSummary(items, { ...INITIAL_FILTER, origin: "FOREIGN" }, ctx, filterPredicate);
    expect(hot[0].supplier_id).toBe("A");           // hot_count=2
    const all = allSuppliersSummary(items, { ...INITIAL_FILTER, origin: "FOREIGN" }, ctx, filterPredicate);
    expect(all.map((s) => s.supplier_id)).toEqual(["A", "B"]); // max desc
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/pages/restock/supplier-summary.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现（移植 restock.js:818-848；池 = predicate skipSupplier）**

```ts
// frontend/src/pages/restock/supplier-summary.ts
import { THRESH } from "./constants";
import type { FilterState } from "./constants";
import type { FilterCtx } from "./filter";

export interface SupplierRow { supplier_id: string; count: number; hot_count: number; max: number; }

function aggregate(
  items: any[], fil: FilterState, ctx: FilterCtx,
  predicate: (it: any, f: FilterState, c: FilterCtx, o?: any) => boolean,
): Map<string, SupplierRow> {
  const pool = items.filter((it) => predicate(it, fil, ctx, { skipSupplier: true }));
  const byS = new Map<string, SupplierRow>();
  for (const it of pool) {
    if (!it.supplier_id || it.urgency_score == null) continue;
    const k = it.supplier_id;
    if (!byS.has(k)) byS.set(k, { supplier_id: k, count: 0, hot_count: 0, max: 0 });
    const e = byS.get(k)!;
    if (it.urgency_score >= THRESH.SUPPLIER_OVERVIEW_HOT) e.hot_count += 1;
    e.count += 1;
    if (it.urgency_score > e.max) e.max = it.urgency_score;
  }
  return byS;
}

export function supplierSummary(items: any[], fil: FilterState, ctx: FilterCtx, predicate: any): SupplierRow[] {
  return Array.from(aggregate(items, fil, ctx, predicate).values())
    .filter((s) => s.hot_count > 0)
    .sort((a, b) => b.hot_count - a.hot_count);
}

export function allSuppliersSummary(items: any[], fil: FilterState, ctx: FilterCtx, predicate: any): SupplierRow[] {
  return Array.from(aggregate(items, fil, ctx, predicate).values())
    .sort((a, b) => b.max - a.max);
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/supplier-summary.test.ts
cd .. && git add frontend/src/pages/restock/supplier-summary.* && git commit -m "feat(restock-ui): 供应商概览（skipSupplier 池，红队 1:1）"
```

---

### Task 11: ordered-store.ts（localStorage 读 + 过期 + 货到自动清）

**Files:**
- Create: `frontend/src/pages/restock/ordered-store.ts` + `.test.ts`

- [ ] **Step 1: 写测试（损坏 / 过期边界 / 自动清）**

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { loadOrdered, autoClearOrderedByPurchase, LS_KEY_ORDERED } from "./ordered-store";

beforeEach(() => localStorage.clear());

describe("ordered-store", () => {
  it("损坏 JSON → {}", () => {
    localStorage.setItem(LS_KEY_ORDERED, "{not json");
    expect(loadOrdered()).toEqual({});
  });
  it("过期项剔除（>30 天）", () => {
    const old = new Date(Date.now() - 31 * 86400000).toISOString();
    const fresh = new Date().toISOString();
    localStorage.setItem(LS_KEY_ORDERED, JSON.stringify({ a: { marked_at: old }, b: { marked_at: fresh } }));
    const r = loadOrdered();
    expect("a" in r).toBe(false); expect("b" in r).toBe(true);
  });
  it("货到自动清：last_purchase_at > marked_at", () => {
    const marked = "2026-06-01T00:00:00.000Z";
    const ordered: Record<string, any> = { b1: { marked_at: marked } };
    const items = [{ barcode: "b1", last_purchase_at: "2026-06-10" }];
    const changed = autoClearOrderedByPurchase(ordered, items);
    expect(changed).toBe(true); expect("b1" in ordered).toBe(false);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/pages/restock/ordered-store.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现（移植 restock.js:54-90；纯函数化）**

```ts
// frontend/src/pages/restock/ordered-store.ts
import { THRESH } from "./constants";

export const LS_KEY_ORDERED = "restock_ordered_v1";

export function loadOrdered(): Record<string, { marked_at: string }> {
  try {
    const raw = localStorage.getItem(LS_KEY_ORDERED);
    if (!raw) return {};
    const data = JSON.parse(raw);
    const cutoff = Date.now() - THRESH.ORDERED_EXPIRY_DAYS * 86400000;
    const cleaned: Record<string, { marked_at: string }> = {};
    for (const [bc, v] of Object.entries<any>(data || {})) {
      if (v && v.marked_at && Date.parse(v.marked_at) >= cutoff) cleaned[bc] = v;
    }
    return cleaned;
  } catch {
    return {};
  }
}

export function saveOrdered(ordered: Record<string, unknown>): void {
  try { localStorage.setItem(LS_KEY_ORDERED, JSON.stringify(ordered)); } catch { /* quota */ }
}

// 货到后 last_purchase_at 晚于 marked_at → 删该项。返回是否有变更（变更则调用方 saveOrdered）。
export function autoClearOrderedByPurchase(
  ordered: Record<string, { marked_at: string }>, items: any[],
): boolean {
  let changed = false;
  for (const bc of Object.keys(ordered)) {
    const it = items.find((x) => x.barcode === bc);
    if (!it || !it.last_purchase_at) continue;
    const last = Date.parse(it.last_purchase_at);
    const marked = Date.parse(ordered[bc].marked_at);
    if (Number.isFinite(last) && last > marked) { delete ordered[bc]; changed = true; }
  }
  return changed;
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/ordered-store.test.ts
cd .. && git add frontend/src/pages/restock/ordered-store.* && git commit -m "feat(restock-ui): ordered-store（过期清理 + 货到自动清）"
```

---

### Task 12: suppressed-normalize.ts

**Files:**
- Create: `frontend/src/pages/restock/suppressed-normalize.ts` + `.test.ts`

- [ ] **Step 1: 写测试（失败/空兜底 {}）**

```ts
import { describe, it, expect } from "vitest";
import { normalizeSuppressed } from "./suppressed-normalize";

describe("normalizeSuppressed", () => {
  it("ok=true 取 items", () => {
    expect(normalizeSuppressed({ ok: true, items: { b1: { skipped_at: "x", reason: null, days_left: 3 } } }))
      .toEqual({ b1: { skipped_at: "x", reason: null, days_left: 3 } });
  });
  it("ok=false / null → {}", () => {
    expect(normalizeSuppressed({ ok: false, items: {} })).toEqual({});
    expect(normalizeSuppressed(null)).toEqual({});
  });
});
```

- [ ] **Step 2: 运行确认失败 → Step 3 实现**

```ts
// frontend/src/pages/restock/suppressed-normalize.ts
import type { RestockSuppressedList, RestockSuppressedEntry } from "../../api/types.gen";

export function normalizeSuppressed(
  data: RestockSuppressedList | null | undefined,
): Record<string, RestockSuppressedEntry> {
  if (!data || !data.ok || !data.items) return {};
  return data.items;
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/suppressed-normalize.test.ts
cd .. && git add frontend/src/pages/restock/suppressed-normalize.* && git commit -m "feat(restock-ui): suppressed 归一（失败兜底 {}）"
```

---

## 阶段 C：Vue 组件 + 页面

> 组件测试参照 `frontend/src/pages/history/*.test.ts` 的 `@vue/test-utils` + `apiGet` mock 风格。

### Task 13: types.ts + RestockTable.vue（行渲染 + 货号深链 + p98 文本）

**Files:**
- Create: `frontend/src/pages/restock/types.ts`
- Create: `frontend/src/pages/restock/RestockTable.vue` + `RestockTable.test.ts`

- [ ] **Step 1: types.ts（复用生成类型 + 视图态）**

```ts
// frontend/src/pages/restock/types.ts
import type { RestockItem } from "../../api/types.gen";
export type { RestockItem };
export interface OrderedEntry { marked_at: string; }
```

- [ ] **Step 2: 写组件测试（500 上限 + 深链 + p98 文本不可编辑）**

```ts
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import RestockTable from "./RestockTable.vue";

function rows(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    barcode: "b" + i, model: "M" + i, name_zh: "名" + i, origin: "FOREIGN",
    supplier_id: "GR1", urgency_score: 50, qty_total: 1, weeks_of_cover: 1,
    weekly_velocity: 1, weekly_revenue: 1, margin_pct: 20, weekly_qty_12w: new Array(12).fill(0),
    restock_qty_p50: 5, restock_qty_p98: 9, last_purchase_qty: 3, last_purchase_days_ago: 1,
    realized_profit_eur: 1, inventory_cost_value_eur: 1, stockout_zero_weeks_last8: 0,
    is_truly_discontinued: false, is_new_item: false, trend_slope_pct_per_week: 0,
  }));
}

describe("RestockTable", () => {
  it("最多渲染 500 行", () => {
    const w = mount(RestockTable, { props: { rows: rows(600), coverThreshold: 4 } });
    expect(w.findAll("tr.rs-row").length).toBe(500);
  });
  it("p98 列是文本非 input", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    expect(w.find(".rs-qty-input").exists()).toBe(false);
  });
  it("点货号 emit open-history", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    w.find(".rs-bc-link").trigger("click");
    expect(w.emitted("open-history")?.[0]).toEqual(["b0"]);
  });
});
```

- [ ] **Step 3: 运行确认失败 → 实现 RestockTable.vue**

实现要点（移植 renderRow，去 drawer/flag/input；urgency 单元格仅 bar+数字无 tooltip；列保持旧表头顺序）：
```vue
<!-- frontend/src/pages/restock/RestockTable.vue -->
<script setup lang="ts">
import { computed } from "vue";
import { VISIBLE_CAP } from "./constants";
import { fmt, fmtDays, coverTone, urgencyLevel, marginLevel } from "./cells";
import type { RestockItem } from "./types";

const props = defineProps<{ rows: RestockItem[]; coverThreshold: number }>();
const emit = defineEmits<{ (e: "open-history", bc: string): void }>();
const visible = computed(() => props.rows.slice(0, VISIBLE_CAP));
</script>

<template>
  <table class="rs-table">
    <tbody id="rsTbody">
      <tr v-for="it in visible" :key="it.barcode" class="rs-row">
        <td>
          <span v-if="it.urgency_score != null" class="rs-urg">
            <span class="rs-urg-bar"><span :class="`rs-urg-fill rs-urg-fill--${urgencyLevel(it.urgency_score)}`"
              :style="{ width: Math.max(0, Math.min(100, it.urgency_score)) + '%' }"></span></span>
            <span :class="`rs-urg-num rs-urg-num--${urgencyLevel(it.urgency_score)}`">{{ it.urgency_score }}</span>
          </span>
          <span v-else class="rs-urg-num rs-urg-num--none">—</span>
        </td>
        <td>
          <span class="rs-model">{{ it.name_zh || it.model }}</span>
          <button class="rs-bc-link" @click="emit('open-history', it.barcode)">{{ it.barcode }}</button>
          <span v-if="it.is_truly_discontinued" class="rs-tag rs-tag--disc">停用</span>
          <span v-if="it.is_new_item" class="rs-tag rs-tag--new">新品</span>
          <span v-if="it.stockout_zero_weeks_last8 > 0" class="rs-badge-stockout">⚠ 近 {{ it.stockout_zero_weeks_last8 }} 周零销疑因缺货</span>
        </td>
        <td>{{ it.supplier_id || "—" }}</td>
        <td class="rs-num">{{ fmt(it.qty_total) }}</td>
        <td class="rs-num">
          <span :class="`rs-cover-num ${coverTone(it.weeks_of_cover, props.coverThreshold)}`">
            {{ it.weeks_of_cover != null ? it.weeks_of_cover.toFixed(1) + "w" : "—" }}</span>
        </td>
        <td class="rs-num">{{ fmt(it.weekly_velocity, 1) }}</td>
        <td class="rs-num">€{{ fmt(it.weekly_revenue, 1) }}</td>
        <td class="rs-num">
          <span v-if="it.margin_pct != null" :class="`rs-margin rs-margin--${marginLevel(it.margin_pct)}`">{{ it.margin_pct.toFixed(1) }}%</span>
          <span v-else class="rs-margin rs-margin--none">—</span>
        </td>
        <td class="rs-num">{{ fmtDays(it.last_purchase_days_ago) }}</td>
        <td class="rs-num">{{ it.restock_qty_p50 ?? "—" }}</td>
        <td class="rs-num">{{ it.restock_qty_p98 ?? "—" }}</td>
        <td class="rs-num">{{ it.last_purchase_qty ?? "—" }}</td>
      </tr>
      <tr v-if="visible.length === 0"><td colspan="12" class="empty">无匹配项</td></tr>
    </tbody>
  </table>
</template>
```
> sparkline / 盈亏 badge 若 Phase 1 要 1:1 保留，按 restock.js:262/274 补对应纯函数与 `<td>`；本表先含核心列，**视觉对照阶段（Task 18）补齐缺列**确保与旧表列集一致。

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/RestockTable.test.ts
cd .. && git add frontend/src/pages/restock/RestockTable.* frontend/src/pages/restock/types.ts && git commit -m "feat(restock-ui): RestockTable（500 上限 + 深链 + p98 文本）"
```

---

### Task 14: FilterBar.vue + KpiCards.vue + SupplierOverview.vue

**Files:**
- Create: 三个 `.vue` + 各自 `.test.ts`

- [ ] **Step 1: SupplierOverview 测试（点击 emit supplier + coverMax=null 双语义）**

```ts
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import SupplierOverview from "./SupplierOverview.vue";

describe("SupplierOverview", () => {
  it("点 chip emit select-supplier（携带 coverMax=null 语义由父处理）", () => {
    const w = mount(SupplierOverview, { props: {
      rows: [{ supplier_id: "GR1", count: 3, hot_count: 2, max: 90 }],
      expanded: false, activeSupplier: null,
    }});
    w.find(".sup-chip").trigger("click");
    expect(w.emitted("select-supplier")?.[0]).toEqual(["GR1"]);
  });
});
```

- [ ] **Step 2: 实现三组件**

- `KpiCards.vue`：props `{ kpi: Kpi }`，渲染 紧急/关注/充足/补货额（无已标记）。
- `FilterBar.vue`：props `{ filter }`，emit `update`（origin 分段 / views / band[全部/紧急/关注/充足/已跳过] / coverMax 滑块 / search / reset）。reset emit `RESET_FILTER`。
- `SupplierOverview.vue`：props `{ rows, expanded, activeSupplier }`，emit `select-supplier(bc)` / `toggle-expand`。**coverMax=null 的副作用由父 RestockPage 在处理 select-supplier 时执行**（见 Task 15），组件只发 supplier。

> 每组件配最小 mount 测试：FilterBar 点「已跳过」chip emit `{band:"skipped"}`；点重置 emit `origin===""` 且 `coverMax===null`。KpiCards 断言渲染 4 个数字、无「已标记」。

- [ ] **Step 3: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/
cd .. && git add frontend/src/pages/restock/FilterBar.* frontend/src/pages/restock/KpiCards.* frontend/src/pages/restock/SupplierOverview.* && git commit -m "feat(restock-ui): FilterBar/KpiCards/SupplierOverview"
```

---

### Task 15: RestockPage.vue（编排 + shallowRef + 401 + 供应商点击清 coverMax）

**Files:**
- Create: `frontend/src/pages/restock/RestockPage.vue` + `RestockPage.test.ts`
- Modify: `frontend/src/router.ts`

- [ ] **Step 1: 写页面测试（供应商点击清 coverMax 红队 + 加载编排）**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
vi.mock("../../api/client", () => ({
  apiGet: vi.fn(), UnauthenticatedError: class extends Error {},
}));
import { mount, flushPromises } from "@vue/test-utils";
import { apiGet } from "../../api/client";
import RestockPage from "./RestockPage.vue";

const item = (p: any) => ({ barcode: "b" + Math.random(), model: "M", name_zh: "n",
  origin: "FOREIGN", supplier_id: "GR1", is_truly_discontinued: false, is_new_item: false,
  qty_total: 1, weeks_of_cover: 8, weekly_velocity: 1, weekly_revenue: 1, margin_pct: 20,
  master_stock_price_eur: 1, master_sale_price_eur: 2, last_purchase_unit_price: 1, sale_net_avg: 1,
  margin_source: null, margin_price_source: null, weekly_qty_12w: new Array(12).fill(0),
  trend_slope_pct_per_week: 0, realized_profit_eur: 1, inventory_cost_value_eur: 1,
  last_purchase_days_ago: 1, last_purchase_at: null, restock_qty_p50: 5, restock_qty_p98: 9,
  restock_source: "x", last_purchase_qty: 3, urgency_score: 90, stockout_zero_weeks_last8: 0, ...p });

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
  localStorage.clear();
});

describe("RestockPage", () => {
  it("红队：点供应商清 coverMax，weeks_of_cover=8 行可见", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path === "/api/restock/items") return { ok: true, total: 1, items: [item({ weeks_of_cover: 8 })] } as any;
      return { ok: true, items: {} } as any; // suppressed
    });
    const w = mount(RestockPage);
    await flushPromises();
    // 默认 coverMax=4 + FOREIGN → weeks_of_cover=8 行被隐藏
    expect(w.findAll("tr.rs-row").length).toBe(0);
    // 点供应商 → coverMax=null → 该行显出
    w.findComponent({ name: "SupplierOverview" }).vm.$emit("select-supplier", "GR1");
    await flushPromises();
    expect(w.findAll("tr.rs-row").length).toBe(1);
  });
});
```

- [ ] **Step 2: 运行确认失败 → 实现 RestockPage.vue**

```vue
<!-- frontend/src/pages/restock/RestockPage.vue -->
<script setup lang="ts">
import { ref, shallowRef, computed, markRaw, onMounted } from "vue";
import { useRouter } from "vue-router";
import { apiGet, UnauthenticatedError } from "../../api/client";
import type { RestockItemList, RestockSuppressedList } from "../../api/types.gen";
import { INITIAL_FILTER, INITIAL_SORT, RESET_FILTER, type FilterState } from "./constants";
import { filterPredicate, type FilterCtx } from "./filter";
import { applySort, type SortState } from "./sort";
import { computeKpi } from "./kpi";
import { supplierSummary, allSuppliersSummary } from "./supplier-summary";
import { loadOrdered, saveOrdered, autoClearOrderedByPurchase } from "./ordered-store";
import { normalizeSuppressed } from "./suppressed-normalize";
import RestockTable from "./RestockTable.vue";
import FilterBar from "./FilterBar.vue";
import KpiCards from "./KpiCards.vue";
import SupplierOverview from "./SupplierOverview.vue";

const router = useRouter();
const items = shallowRef<any[]>([]);            // 27k 行：浅响应，避免深代理
const suppressed = ref<Record<string, any>>({});
const ordered = ref<Record<string, { marked_at: string }>>({});
const filter = ref<FilterState>({ ...INITIAL_FILTER });
const sort = ref<SortState>({ ...INITIAL_SORT });
const supExpanded = ref(false);
const loadError = ref<string | null>(null);
const loaded = ref(false);

const ctx = computed<FilterCtx>(() => ({ ordered: ordered.value, suppressed: suppressed.value, selected: new Set() }));
const filteredSorted = computed(() => applySort(items.value.filter((it) => filterPredicate(it, filter.value, ctx.value)), sort.value));
const kpi = computed(() => computeKpi(items.value, filter.value, ctx.value, filterPredicate));
const supRows = computed(() => supExpanded.value
  ? allSuppliersSummary(items.value, filter.value, ctx.value, filterPredicate)
  : supplierSummary(items.value, filter.value, ctx.value, filterPredicate).slice(0, 5));

async function load() {
  loadError.value = null;
  try {
    ordered.value = loadOrdered();
    const data = await apiGet<RestockItemList>("/api/restock/items");
    items.value = markRaw(data.items as any[]);
    if (autoClearOrderedByPurchase(ordered.value, items.value)) saveOrdered(ordered.value);
    try {
      const s = await apiGet<RestockSuppressedList>("/api/restock/suppressed");
      suppressed.value = normalizeSuppressed(s);
    } catch { suppressed.value = {}; }
    loaded.value = true;
  } catch (e) {
    if (e instanceof UnauthenticatedError) return; // client 已跳登录
    loadError.value = (e as Error).message;
  }
}

function onSelectSupplier(bc: string) {
  // 凑单模式：设 supplier 且清 coverMax（spec §1，红队静默缩水）
  filter.value = { ...filter.value, supplier: bc, coverMax: null };
}
function onUpdateFilter(f: FilterState) { filter.value = f; }
function onReset() { filter.value = { ...RESET_FILTER }; }
function onOpenHistory(bc: string) { location.href = "/ui/history?q=" + encodeURIComponent(bc); }

onMounted(load);
</script>

<template>
  <section id="pageRestock">
    <KpiCards :kpi="kpi" />
    <SupplierOverview name="SupplierOverview" :rows="supRows" :expanded="supExpanded"
      :active-supplier="filter.supplier" @select-supplier="onSelectSupplier" @toggle-expand="supExpanded = !supExpanded" />
    <FilterBar :filter="filter" @update="onUpdateFilter" @reset="onReset" />
    <p v-if="loadError" class="empty">加载失败：{{ loadError }}</p>
    <p v-else-if="!loaded" class="empty">加载中…</p>
    <RestockTable v-else :rows="filteredSorted" :cover-threshold="filter.coverThreshold" @open-history="onOpenHistory" />
  </section>
</template>
```
> `name="SupplierOverview"` 用于测试 `findComponent({name})`；若组件未显式 `defineOptions({name})`，在 SupplierOverview.vue 加 `defineOptions({ name: "SupplierOverview" })`。
> 401 中性态：`apiGet` 已在 401 时跳登录；页面只在 `!loaded` 时显「加载中…」中性占位（非业务空态）。

- [ ] **Step 3: 注册路由**

```ts
// frontend/src/router.ts — children 数组追加
{ path: "restock", name: "restock", component: () => import("./pages/restock/RestockPage.vue") },
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/RestockPage.test.ts
cd .. && git add frontend/src/pages/restock/RestockPage.* frontend/src/router.ts && git commit -m "feat(restock-ui): RestockPage 编排（shallowRef + 401 中性 + 点供应商清 coverMax）"
```

---

### Task 16: 禁旧端点 guard

**Files:**
- Create: `frontend/src/pages/restock/no-analytics.test.ts`

- [ ] **Step 1: 写守护测试（照 history/no-analytics.test.ts 先例）**

```ts
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const DIR = join(__dirname);
const FORBIDDEN = ["/analytics/", "/restock/decisions"];

describe("restock 页只走 /api/restock/*", () => {
  it("源码不含旧胖端点", () => {
    const files = readdirSync(DIR).filter((f) => (f.endsWith(".ts") || f.endsWith(".vue")) && !f.endsWith(".test.ts"));
    for (const f of files) {
      const src = readFileSync(join(DIR, f), "utf8");
      for (const bad of FORBIDDEN) expect(src.includes(bad), `${f} 含 ${bad}`).toBe(false);
    }
  });
});
```

- [ ] **Step 2: 运行确认通过（实现已合规）**

Run: `cd frontend && npx vitest run src/pages/restock/no-analytics.test.ts`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/restock/no-analytics.test.ts
git commit -m "test(restock-ui): 守护只走 /api/restock/*"
```

---

### Task 17: scoped CSS 移植 + 视觉对照补缺列

**Files:**
- Modify: `frontend/src/pages/restock/*.vue`（各组件 `<style scoped>`）

- [ ] **Step 1: 起本地栈**

Run: `./dev.ps1 -Frontend`（先 `python tools/pull_prod_db.py` 灌真实数据；本地空 PG 见 `project_local_pg_derived_cols_empty`）

- [ ] **Step 2: 浏览器对照旧页**

旧页：`http://127.0.0.1:5000/`（hash 进补货分区）；新页：`http://127.0.0.1:5173/ui/restock`（或 dev.ps1 给的端口）。
逐项核对：被渲染列集 / KPI 三数 + 补货额 / 供应商概览（折叠 top5、展开全量）。把所需 `.rs-*` 规则从 `static/css/components.css` **移进各组件 `<style scoped>`、用 token 变量**（参照 `AppShell.vue` 注释）。**不全局 import components.css**。

- [ ] **Step 3: 补齐与旧表一致的缺列**（sparkline / 盈亏 badge 等），各补对应纯函数 + 单测。

- [ ] **Step 4: 截图留档 + Commit**

```bash
git add frontend/src/pages/restock/
git commit -m "feat(restock-ui): scoped CSS 移植 + 列集对齐旧页"
```

---

## 阶段 D：e2e + 性能 + 收尾

### Task 18: e2e smoke（自建夹具）

**Files:**
- Create: `e2e/test_restock_smoke.py`

- [ ] **Step 1: 写 smoke（自建最小夹具，不依赖导入/顺序）**

```python
# e2e/test_restock_smoke.py
import pytest

pytestmark = pytest.mark.smoke

def test_restock_ui_renders_rows(page, base_url, seed_restock_fixture, login):
    # seed_restock_fixture: 走 SQLAlchemy 注入几条 SKU（含 1 条 FOREIGN 高分），
    # 参照 e2e/conftest.py 既有 fixture 风格；login: 既有登录态 fixture。
    page.goto(f"{base_url}/ui/restock")
    page.wait_for_selector("tr.rs-row")
    assert page.locator("tr.rs-row").count() >= 1
    assert page.locator("#pageRestock").inner_text()  # KPI 区有内容
```

> `seed_restock_fixture` 在 `e2e/conftest.py` 新增：用 SQLAlchemy 建最小 stockpile + inventory_events，使 `list_sku_summary()` 至少返回 1 行。DB 隔离照 `project_e2e_harness`（强制 `DATABASE_URL` → 沙箱 sqlite）。

- [ ] **Step 2: 运行**

Run: `pytest e2e/test_restock_smoke.py -v`（需先 `cd frontend && npm run build` 产出 dist + output.css，见 `project_e2e_harness` 假绿坑）
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add e2e/test_restock_smoke.py e2e/conftest.py
git commit -m "test(e2e): /ui/restock smoke（自建夹具）"
```

---

### Task 19: 性能门槛

**Files:**
- Create: `tools/bench_restock_api.py`

- [ ] **Step 1: 后端 bench 脚本**

```python
# tools/bench_restock_api.py — 同机同数据集；预热 3 / 计时 10 取 p50
import statistics, time
from app import create_app  # 照项目 app 工厂；不确定则 grep "def create_app"

def _p50(client, path, warm=3, n=10):
    for _ in range(warm): client.get(path)
    ts = []
    for _ in range(n):
        t = time.perf_counter(); client.get(path); ts.append(time.perf_counter() - t)
    return statistics.median(ts)

def main():
    app = create_app(); c = app.test_client()
    old = _p50(c, "/analytics/list"); new = _p50(c, "/api/restock/items")
    print(f"/analytics/list p50={old*1000:.0f}ms  /api/restock/items p50={new*1000:.0f}ms  ratio={new/old:.2f}")
    assert new <= old * 1.3, f"items p50 {new:.3f} > analytics {old:.3f} ×1.3"

if __name__ == "__main__": main()
```

- [ ] **Step 2: 跑（对真实量级数据；本地灌 prod DB）**

Run: `python tools/bench_restock_api.py`
Expected: `ratio` ≤ 1.3，断言不抛。把输出贴进 PR 描述。

- [ ] **Step 3: 前端 filter+sort 量化（Vitest bench 或临时测试）**

```ts
// frontend/src/pages/restock/perf.test.ts （可选 @vitest 普通 test 计时）
import { describe, it, expect } from "vitest";
import { filterPredicate } from "./filter";
import { applySort } from "./sort";
import { INITIAL_FILTER } from "./constants";

describe("perf", () => {
  it("27k filter+sort 中位（相对参照 ×1.5）", () => {
    const items = Array.from({ length: 27000 }, (_, i) => ({
      barcode: "b" + i, origin: "FOREIGN", supplier_id: "GR1", is_truly_discontinued: false,
      is_new_item: false, urgency_score: i % 100, weeks_of_cover: i % 10,
    }));
    const ctx = { ordered: {}, suppressed: {}, selected: new Set<string>() };
    const run = () => applySort(items.filter((it) => filterPredicate(it, INITIAL_FILTER, ctx)), { key: "urgency_score", dir: "desc" });
    for (let i = 0; i < 3; i++) run();
    const ts: number[] = [];
    for (let i = 0; i < 20; i++) { const t = performance.now(); run(); ts.push(performance.now() - t); }
    ts.sort((a, b) => a - b);
    const median = ts[10];
    expect(median).toBeLessThan(100); // 宽松上限；PR 记录实测中位
  });
});
```

- [ ] **Step 4: Commit**

```bash
git add tools/bench_restock_api.py frontend/src/pages/restock/perf.test.ts
git commit -m "test(restock): 后端/前端性能门槛脚本"
```

---

### Task 20: 全量回归 + 导航确认 + 收尾

- [ ] **Step 1: 后端全测**

Run: `pytest tests/ -q`
Expected: 全绿（新增 restock_api 测试 + 既有 1018）

- [ ] **Step 2: 前端全测 + 构建**

Run: `cd frontend && npm test && npm run build`
Expected: Vitest 全绿；vue-tsc 0 错

- [ ] **Step 3: gen_ts_types 漂移检查**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0

- [ ] **Step 4: 确认导航策略**

侧栏「补货」仍指旧页；`/ui/restock` 仅预览直达（不改 SidebarNav 主入口）。确认 `frontend/src/shell/SidebarNav.vue` 补货项未被改向新页（Phase 1 不切主入口，spec §8）。

- [ ] **Step 5: PR**

```bash
git push -u origin feat/restock-vue-phase1
# gh pr create，描述贴：后端/前端 perf p50 实测 + 审计偏离（双 null→0）+ 省略 urgency tooltip
```
> push 前确认非周一 14:00 scraper 窗口；本地已浏览器验收。

---

## Self-Review（对照 spec rev5）

- §3 API 契约 → Task 1-4 ✅（suppressed/items 端点 + RestockItem 白名单 + 投影 key 集 + 拒 null + origin 枚举 + gen_ts_types）
- §1 省略控件（urgency tooltip/⚑/已标记/drawer/knob/p98 文本）→ Task 13 RestockTable（无 input、urgency 无 tooltip）✅
- §1 供应商点击清 coverMax 双入口 → Task 15 onSelectSupplier + 红队测试 ✅（表内 supplier 按钮：Phase 1 表格 supplier 单元格若做成可点，emit 同 onSelectSupplier；当前 RestockTable 未含 supplier 点击——**补充**：Task 13 supplier 单元格加 `@click` emit `select-supplier`，父复用 onSelectSupplier。见下「修正」）
- §2 ordered/suppressed 只读加载 → Task 11/12/15 ✅
- §6 filter/sort/kpi/supplier 契约 + band=ok null + 审计偏离 → Task 7/8/9/10 ✅
- §6 常量两套值 → Task 5 ✅
- §5 scoped CSS 不全局导入 → Task 17 ✅
- §8 shallowRef + 导航 → Task 15/20 ✅
- §9 验收全项 → Task 1-3/16/18/19/20 ✅

**修正（Self-Review 发现）：** Task 13 RestockTable 的 supplier 单元格当前只渲染文本。旧页表内 supplier 按钮也触发凑单模式（spec §1 双入口）。在 Task 13 Step 3 的 supplier `<td>` 改为：
```vue
<td>
  <button v-if="it.supplier_id" class="rs-supplier" @click="emit('select-supplier', it.supplier_id)">{{ it.supplier_id }}</button>
  <span v-else class="rs-supplier rs-supplier--none">—</span>
</td>
```
并在 `defineEmits` 加 `(e: "select-supplier", bc: string): void`；RestockPage 模板 `<RestockTable ... @select-supplier="onSelectSupplier" />`。RestockTable.test.ts 增一例：点 `.rs-supplier` emit `select-supplier`。
