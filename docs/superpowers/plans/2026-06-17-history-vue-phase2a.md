# 货号历史 Vue Phase 2a（SLA + PUR + 客户拆分）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `/ui/history` 命中态补销售分析(SLA)+采购面(PUR)+CN/老外客户拆分卡，数据走新建瘦端点 `GET /api/history/<barcode>/analytics`。additive，独立 store 失败隔离。

**Architecture:** 瘦端点只调 `compute_sales_metrics`/`compute_purchase_metrics`/`compute_customer_split`，strict pydantic（只建 2a 字段）→ gen_ts_types → 前端独立 `useSkuAnalyticsStore` + analytics-normalize（单点收窄）→ HistoryPage 命中分支触发 `analyticsStore.load` 并渲染分析块（独立 loading/error，不影响 P1 hero/概况/events）。

**Tech Stack:** Flask + pydantic、Vue 3 + pinia + vitest、pytest。

**spec：** `docs/superpowers/specs/2026-06-17-history-vue-phase2a-design.md`（HC-A1~A5）。worktree `C:\Dev\label-sync\.claude\worktrees\feat+history-vue-phase2a`（分支 `worktree-feat+history-vue-phase2a`，含 P1 全部）。pytest 用 `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest`（cwd=worktree 根）；前端 `cd frontend && npx vitest run <file>` / `npm run test` / `npm run typecheck`（node_modules 需先 `npm install`）。

**已核实事实（勿凭记忆）：**
- 三个 compute 返回（`app/services/analytics/metrics.py` + `_shared.py`，逐字段核过）：
  - `compute_sales_metrics` → `{total_qty:int, total_revenue:float, unique_customers:int, lifespan_days:int, trend_slope_pct_per_week:float|None}`
  - `compute_purchase_metrics` → `{stock_balance:int, avg_margin_pct:float|None, purchase_freq_365d:int, last_purchase_days_ago:int|None}`
  - `compute_customer_split` → `{cn:{...}, fo:{...}}`，每端 = `{qty:int, unique_customers:int, max_single_qty:int, last_at:str|None, avg_freq_per_month:float}`
- 三函数都从 `app.services.analytics` re-export（现有 `analytics.py` 路由即 `from app.services import analytics as analytics_service; analytics_service.compute_sales_metrics(...)`）。
- `app/routes/history.py` 已有 `bp`(`/history`) + `api_bp`(`/api/history`，P1 建)，`api_bp` 已在 `__init__.py` 注册 → 本期**只在 api_bp 加一个路由，无需再注册**。
- 当前 `HistoryPage.vue`（worktree）命中态结构：hero → `<dl class="history__overview">`(概况，结束于 `</dl>`) → `<div class="history__timeline">`(历史时间线)。分析块插在概况 `</dl>` 之后、timeline `<div>` 之前。
- `HistoryPage.test.ts` 现 mock `../../stores/history`；本期需**追加** mock `../../stores/skuAnalytics`。
- 无销售/不存在 barcode：三函数返回零值 shape（不 404）。customer master 未 seed 时 customer_type=unknown → cn/fo 两端零值（合法）。

---

## 文件结构
**后端：** 修改 `app/schemas_api.py`（+5 模型 + API_MODELS）、`app/routes/history.py`（api_bp 加 analytics 路由）；创建 `tests/test_history_analytics_api.py`
**类型生成：** 修改 `frontend/src/api/types.gen.ts`
**前端：** 创建 `frontend/src/pages/history/analytics-types.ts`、`analytics-normalize.ts`(+test)、`frontend/src/stores/skuAnalytics.ts`(+test)；修改 `frontend/src/pages/history/HistoryPage.vue`(+扩展 HistoryPage.test.ts)

---

## Task 1: 后端瘦端点 + strict schema + 契约测试

**Files:** Modify `app/schemas_api.py`, `app/routes/history.py`; Test `tests/test_history_analytics_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_history_analytics_api.py`：

```python
"""GET /api/history/<barcode>/analytics：SLA+PUR+客户拆分瘦端点（Phase 2a 契约）。

只返回 {ok, sales, purchase, customer_split}（HC-A5）。鉴权镜像 tests/test_api_briefing.py。
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


def _get(app, bc):
    return app.test_client().get(
        f"/api/history/{bc}/analytics", headers={"X-Upload-Token": "test-token-123"}
    )


def _exec(sql, params):
    from app import db

    with db.get_engine().begin() as conn:
        conn.execute(text(sql), params)


def _seed_stockpile(app, barcode, model):
    import pandas as pd

    from app.repositories import stockpile_db

    with app.app_context():
        stockpile_db.import_from_dataframe(
            pd.DataFrame([{"product_barcode": barcode, "product_model": model, "stockpile_location": "A1"}])
        )


def _seed_event(barcode, event_type, qty, at, unit_price=None):
    _exec(
        "INSERT INTO inventory_events (product_barcode, event_type, qty, unit_price, event_at) "
        "VALUES (:b, :t, :q, :p, :at)",
        {"b": barcode, "t": event_type, "q": qty, "p": unit_price, "at": at},
    )


def test_analytics_unauthenticated_returns_json_401(real_app):
    r = real_app.test_client().get("/api/history/X/analytics")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_analytics_key_set_is_exactly_2a(real_app):
    """HC-A5：响应 key 恰好 {ok, sales, purchase, customer_split}，无 2b key。"""
    _seed_stockpile(real_app, "B1", "M1")
    r = _get(real_app, "B1")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"ok", "sales", "purchase", "customer_split"}
    assert set(body["customer_split"]) == {"cn", "fo"}


def test_analytics_no_sales_returns_zero_shape(real_app):
    """只有主档无事件：sales 全 0、customer_split 两端 0（合法零值，非错误）。"""
    _seed_stockpile(real_app, "B1", "M1")
    body = _get(real_app, "B1").get_json()
    assert body["ok"] is True
    assert body["sales"]["total_qty"] == 0
    assert body["sales"]["trend_slope_pct_per_week"] is None
    assert body["customer_split"]["cn"]["qty"] == 0
    assert body["purchase"]["stock_balance"] == 0


def test_analytics_with_events(real_app):
    """seed sale+purchase 事件：sales.total_qty 汇总、purchase.stock_balance = 进-销。"""
    _seed_stockpile(real_app, "B1", "M1")
    _seed_event("B1", "sale", 3, "2026-05-01", unit_price=10.0)
    _seed_event("B1", "sale", 2, "2026-05-08", unit_price=10.0)
    _seed_event("B1", "purchase", 10, "2026-04-01", unit_price=6.0)
    body = _get(real_app, "B1").get_json()
    assert body["sales"]["total_qty"] == 5
    assert body["purchase"]["stock_balance"] == 5   # 10 purchase - 5 sale
```

- [ ] **Step 2: 跑测试确认失败**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest tests/test_history_analytics_api.py -v`
Expected: 401 PASS；其余 FAIL（端点 404 / SkuAnalyticsData 未定义）。

- [ ] **Step 3: 加 pydantic schema**

在 `app/schemas_api.py`，`HistorySearchData` 之后、`API_MODELS` 之前插入：

```python
class SkuSalesMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_qty: int
    total_revenue: float
    unique_customers: int
    lifespan_days: int
    trend_slope_pct_per_week: float | None


class SkuPurchaseMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_balance: int
    avg_margin_pct: float | None
    purchase_freq_365d: int
    last_purchase_days_ago: int | None


class SkuCustomerEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty: int
    unique_customers: int
    max_single_qty: int
    last_at: str | None
    avg_freq_per_month: float


class SkuCustomerSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cn: SkuCustomerEnd
    fo: SkuCustomerEnd


class SkuAnalyticsData(BaseModel):
    """GET /api/history/<barcode>/analytics 200 响应（Phase 2a canonical 契约）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    sales: SkuSalesMetrics
    purchase: SkuPurchaseMetrics
    customer_split: SkuCustomerSplit
```

`API_MODELS` 行末尾追加 `SkuAnalyticsData`：
```python
API_MODELS: list[type[BaseModel]] = [BriefingData, MeData, ForecastEvalData, HistorySearchData, SkuAnalyticsData]
```
（若实际内容不同，仅末尾追加 `SkuAnalyticsData`，不动其它。）

- [ ] **Step 4: 加 analytics 路由**

在 `app/routes/history.py` 末尾（现有 `api_bp` 的 `search()` 之后）追加：

```python
@api_bp.get("/<barcode>/analytics")
def analytics(barcode: str):
    from app.schemas_api import SkuAnalyticsData
    from app.services import analytics as analytics_service

    bc = barcode.strip()
    payload = {
        "ok": True,
        "sales": analytics_service.compute_sales_metrics(bc),
        "purchase": analytics_service.compute_purchase_metrics(bc),
        "customer_split": analytics_service.compute_customer_split(bc),
    }
    return jsonify(SkuAnalyticsData.model_validate(payload).model_dump())
```
（`api_bp` 已在 `app/routes/__init__.py` 注册，无需再注册。`jsonify` 已在文件顶部 import。）

- [ ] **Step 5: 跑测试 + ruff**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest tests/test_history_analytics_api.py -v`
Expected: 4 PASS。失败先排查 schema 字段/类型 vs compute 输出一致（**勿改测试断言迁就 bug**）。
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m ruff check app/schemas_api.py app/routes/history.py tests/test_history_analytics_api.py`
Expected: All checks passed

- [ ] **Step 6: 提交**
```bash
git add app/schemas_api.py app/routes/history.py tests/test_history_analytics_api.py
git commit -m "feat(history): /api/history/<barcode>/analytics 瘦端点 + strict schema (Phase 2a)"
```

---

## Task 2: 重新生成 TS 类型

**Files:** Modify `frontend/src/api/types.gen.ts`

- [ ] **Step 1: 生成** — Run: `C:/Dev/label-sync/.venv/Scripts/python.exe tools/gen_ts_types.py` → `wrote ...`
- [ ] **Step 2: --check** — Run: `C:/Dev/label-sync/.venv/Scripts/python.exe tools/gen_ts_types.py --check` → 退出码 0；`git diff` 应见 `SkuSalesMetrics/SkuPurchaseMetrics/SkuCustomerEnd/SkuCustomerSplit/SkuAnalyticsData`
- [ ] **Step 3: 提交**
```bash
git add frontend/src/api/types.gen.ts
git commit -m "chore(history): 同步 TS 类型 (gen_ts_types)"
```

---

## Task 3: 前端 VM 类型 + analytics-normalize

**Files:** Create `frontend/src/pages/history/analytics-types.ts`, `analytics-normalize.ts`, `analytics-normalize.test.ts`

- [ ] **Step 1: 写 VM 类型**

创建 `frontend/src/pages/history/analytics-types.ts`：

```typescript
export interface SalesVM {
  totalQty: number;
  totalRevenue: number;
  uniqueCustomers: number;
  lifespanDays: number;
  trendSlopePctPerWeek: number | null;
}
export interface PurchaseVM {
  stockBalance: number;
  avgMarginPct: number | null;
  purchaseFreq365d: number;
  lastPurchaseDaysAgo: number | null;
}
export interface CustomerEndVM {
  qty: number;
  uniqueCustomers: number;
  maxSingleQty: number;
  lastAt: string | null;
  avgFreqPerMonth: number;
}
export interface AnalyticsVM {
  sales: SalesVM;
  purchase: PurchaseVM;
  cn: CustomerEndVM;
  fo: CustomerEndVM;
}
```

- [ ] **Step 2: 写失败测试**

创建 `frontend/src/pages/history/analytics-normalize.test.ts`：

```typescript
import { describe, expect, it } from "vitest";
import type { SkuAnalyticsData } from "../../api/types.gen";
import { normalizeAnalytics } from "./analytics-normalize";

const FULL: SkuAnalyticsData = {
  ok: true,
  sales: { total_qty: 5, total_revenue: 62.5, unique_customers: 2, lifespan_days: 30, trend_slope_pct_per_week: 1.2 },
  purchase: { stock_balance: 5, avg_margin_pct: 40.0, purchase_freq_365d: 1, last_purchase_days_ago: 47 },
  customer_split: {
    cn: { qty: 3, unique_customers: 1, max_single_qty: 3, last_at: "2026-05-08", avg_freq_per_month: 0.5 },
    fo: { qty: 2, unique_customers: 1, max_single_qty: 2, last_at: null, avg_freq_per_month: 0.0 },
  },
};

describe("normalizeAnalytics", () => {
  it("camelCase 映射 + 客户两端", () => {
    const vm = normalizeAnalytics(FULL);
    expect(vm.sales.totalQty).toBe(5);
    expect(vm.sales.trendSlopePctPerWeek).toBe(1.2);
    expect(vm.purchase.stockBalance).toBe(5);
    expect(vm.cn.qty).toBe(3);
    expect(vm.fo.lastAt).toBeNull();
  });

  it("null 字段兜底（trend/margin/last_purchase 为 null）", () => {
    const vm = normalizeAnalytics({
      ...FULL,
      sales: { ...FULL.sales, trend_slope_pct_per_week: null },
      purchase: { stock_balance: 0, avg_margin_pct: null, purchase_freq_365d: 0, last_purchase_days_ago: null },
    });
    expect(vm.sales.trendSlopePctPerWeek).toBeNull();
    expect(vm.purchase.avgMarginPct).toBeNull();
    expect(vm.purchase.lastPurchaseDaysAgo).toBeNull();
  });
});
```

- [ ] **Step 3: 跑确认失败** — Run: `cd frontend && npx vitest run src/pages/history/analytics-normalize.test.ts` → FAIL（normalizeAnalytics 不存在）

- [ ] **Step 4: 写 normalize**

创建 `frontend/src/pages/history/analytics-normalize.ts`：

```typescript
import type {
  SkuAnalyticsData, SkuCustomerEnd, SkuPurchaseMetrics, SkuSalesMetrics,
} from "../../api/types.gen";
import type { AnalyticsVM, CustomerEndVM, PurchaseVM, SalesVM } from "./analytics-types";

function num(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}
function str(x: unknown): string | null {
  return typeof x === "string" ? x : null;
}

function sales(s: SkuSalesMetrics): SalesVM {
  return {
    totalQty: num(s.total_qty) ?? 0,
    totalRevenue: num(s.total_revenue) ?? 0,
    uniqueCustomers: num(s.unique_customers) ?? 0,
    lifespanDays: num(s.lifespan_days) ?? 0,
    trendSlopePctPerWeek: num(s.trend_slope_pct_per_week),
  };
}
function purchase(p: SkuPurchaseMetrics): PurchaseVM {
  return {
    stockBalance: num(p.stock_balance) ?? 0,
    avgMarginPct: num(p.avg_margin_pct),
    purchaseFreq365d: num(p.purchase_freq_365d) ?? 0,
    lastPurchaseDaysAgo: num(p.last_purchase_days_ago),
  };
}
function end(c: SkuCustomerEnd): CustomerEndVM {
  return {
    qty: num(c.qty) ?? 0,
    uniqueCustomers: num(c.unique_customers) ?? 0,
    maxSingleQty: num(c.max_single_qty) ?? 0,
    lastAt: str(c.last_at),
    avgFreqPerMonth: num(c.avg_freq_per_month) ?? 0,
  };
}

/** API 边界唯一收窄点（HC-A5）：只收 sales/purchase/customer_split，不碰任何 2b 字段。 */
export function normalizeAnalytics(raw: SkuAnalyticsData): AnalyticsVM {
  return {
    sales: sales(raw.sales),
    purchase: purchase(raw.purchase),
    cn: end(raw.customer_split.cn),
    fo: end(raw.customer_split.fo),
  };
}
```

- [ ] **Step 5: 跑确认通过** — Run: `cd frontend && npx vitest run src/pages/history/analytics-normalize.test.ts` → PASS（2）
- [ ] **Step 6: 提交**
```bash
git add frontend/src/pages/history/analytics-types.ts frontend/src/pages/history/analytics-normalize.ts frontend/src/pages/history/analytics-normalize.test.ts
git commit -m "feat(history): analytics VM 类型 + normalize 收窄层 (2a)"
```

---

## Task 4: 独立 skuAnalytics store（失败隔离 + 状态卫生）

**Files:** Create `frontend/src/stores/skuAnalytics.ts`, `skuAnalytics.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/stores/skuAnalytics.test.ts`：

```typescript
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(async () => ({
    ok: true,
    sales: { total_qty: 5, total_revenue: 62.5, unique_customers: 2, lifespan_days: 30, trend_slope_pct_per_week: 1.2 },
    purchase: { stock_balance: 5, avg_margin_pct: 40.0, purchase_freq_365d: 1, last_purchase_days_ago: 47 },
    customer_split: {
      cn: { qty: 3, unique_customers: 1, max_single_qty: 3, last_at: "2026-05-08", avg_freq_per_month: 0.5 },
      fo: { qty: 2, unique_customers: 1, max_single_qty: 2, last_at: null, avg_freq_per_month: 0.0 },
    },
  })),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useSkuAnalyticsStore } from "./skuAnalytics";

describe("skuAnalytics store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 填 vm 清 loading + 调对端点", async () => {
    const s = useSkuAnalyticsStore();
    const p = s.load("B1");
    expect(s.loading).toBe(true);
    await p;
    expect(s.loading).toBe(false);
    expect(s.vm?.sales.totalQty).toBe(5);
    expect(s.error).toBeNull();
    expect(vi.mocked(apiGet)).toHaveBeenCalledWith("/api/history/B1/analytics");
  });

  it("load 失败 → error 填充，vm null", async () => {
    const s = useSkuAnalyticsStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load("B1");
    expect(s.error).toBe("boom");
    expect(s.vm).toBeNull();
  });

  it("未登录吞掉，error 保持 null", async () => {
    const s = useSkuAnalyticsStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    await s.load("B1");
    expect(s.error).toBeNull();
  });

  it("旧 vm 存在 + 新 load 失败 → vm null（状态卫生回归）", async () => {
    const s = useSkuAnalyticsStore();
    await s.load("A");           // 成功，vm 非空
    expect(s.vm).not.toBeNull();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load("B");           // 失败
    expect(s.vm).toBeNull();     // 不得残留 A
    expect(s.error).toBe("boom");
  });

  it("reset() 清 vm/error", async () => {
    const s = useSkuAnalyticsStore();
    await s.load("A");
    s.reset();
    expect(s.vm).toBeNull();
    expect(s.error).toBeNull();
  });
});
```

- [ ] **Step 2: 跑确认失败** — Run: `cd frontend && npx vitest run src/stores/skuAnalytics.test.ts` → FAIL（useSkuAnalyticsStore 不存在）

- [ ] **Step 3: 写 store**

创建 `frontend/src/stores/skuAnalytics.ts`：

```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { SkuAnalyticsData } from "../api/types.gen";
import { normalizeAnalytics } from "../pages/history/analytics-normalize";
import type { AnalyticsVM } from "../pages/history/analytics-types";

export const useSkuAnalyticsStore = defineStore("skuAnalytics", () => {
  const vm = ref<AnalyticsVM | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load(barcode: string) {
    loading.value = true;
    error.value = null;
    vm.value = null; // 开查询即清旧 VM：失败/401 后不残留上次分析（HC-A4 状态卫生）
    try {
      const raw = await apiGet<SkuAnalyticsData>(`/api/history/${encodeURIComponent(barcode)}/analytics`);
      vm.value = normalizeAnalytics(raw);
    } catch (e) {
      if (e instanceof UnauthenticatedError) return; // 401 走全局跳转，不写块内 error
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  function reset() {
    vm.value = null;
    error.value = null;
    loading.value = false;
  }

  return { vm, loading, error, load, reset };
});
```

- [ ] **Step 4: 跑确认通过** — Run: `cd frontend && npx vitest run src/stores/skuAnalytics.test.ts` → PASS（5）
- [ ] **Step 5: 提交**
```bash
git add frontend/src/stores/skuAnalytics.ts frontend/src/stores/skuAnalytics.test.ts
git commit -m "feat(history): 独立 skuAnalytics store（失败隔离+状态卫生）"
```

---

## Task 5: HistoryPage 集成分析块

**Files:** Modify `frontend/src/pages/history/HistoryPage.vue`, `HistoryPage.test.ts`

- [ ] **Step 1: 扩展测试（先红）**

打开 `frontend/src/pages/history/HistoryPage.test.ts`。在文件顶部现有 `vi.mock("../../stores/history", ...)` 之后**追加** analytics store 的 mock + 一个可调状态对象：

```typescript
const analyticsState = {
  vm: null as import("./analytics-types").AnalyticsVM | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
  reset: vi.fn(),
};
vi.mock("../../stores/skuAnalytics", () => ({ useSkuAnalyticsStore: () => analyticsState }));
```
在现有 `reset()` 辅助函数里（或新增）一并重置 analytics：把 analytics 状态也清掉（`analyticsState.vm = null; analyticsState.loading = false; analyticsState.error = null; analyticsState.load = vi.fn(); analyticsState.reset = vi.fn();`）。

然后追加用例：

```typescript
function aVm(): import("./analytics-types").AnalyticsVM {
  return {
    sales: { totalQty: 5, totalRevenue: 62.5, uniqueCustomers: 2, lifespanDays: 30, trendSlopePctPerWeek: 1.2 },
    purchase: { stockBalance: 5, avgMarginPct: 40, purchaseFreq365d: 1, lastPurchaseDaysAgo: 47 },
    cn: { qty: 3, uniqueCustomers: 1, maxSingleQty: 3, lastAt: "2026-05-08", avgFreqPerMonth: 0.5 },
    fo: { qty: 2, uniqueCustomers: 1, maxSingleQty: 2, lastAt: null, avgFreqPerMonth: 0 },
  };
}
function hitState() {
  state.result = {
    kind: "hit",
    current: {
      barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
      productNameZh: "名", productNameLocal: null,
      storeLocations: [], warehouseLocations: [], unknownLocations: [],
      salePrice: null, source: null, updatedAt: null,
    },
    events: [],
  };
}

it("命中后渲染分析块（SLA 总销量 + PUR 库存推算 + 客户拆分）", () => {
  reset(); hitState(); analyticsState.vm = aVm();
  const w = mount(HistoryPage);
  expect(w.text()).toContain("销售分析");
  expect(w.text()).toContain("采购面");
  expect(w.text()).toContain("5");        // total_qty / stock_balance
  expect(w.text()).toContain("老外");      // 客户拆分卡
});

it("analytics 普通失败：分析块显错，但 P1 hero/概况/时间线仍在（HC-A4）", () => {
  reset(); hitState(); analyticsState.error = "API 500: /api/history/B1/analytics";
  const w = mount(HistoryPage);
  expect(w.text()).toContain("API 500");     // 块内错误
  expect(w.text()).toContain("M1");          // hero 仍在
  expect(w.text()).toContain("名");          // 概况仍在
  expect(w.text()).toContain("历史时间线");   // 时间线仍在
});

it("analytics 401（error 保持 null）：不显块内错误，P1 部分正常", () => {
  reset(); hitState(); // analyticsState.error 保持 null（store 吞 Unauth）
  const w = mount(HistoryPage);
  expect(w.text()).not.toContain("分析加载失败");
  expect(w.text()).toContain("M1");
});

it("analytics loading：显分析加载中，P1 hero 仍在", () => {
  reset(); hitState(); analyticsState.loading = true;
  const w = mount(HistoryPage);
  expect(w.text()).toContain("分析加载中");
  expect(w.text()).toContain("M1");
});
```

> 注：现有 7+2(RECENT)+2(bugfix) 个用例继续保留；它们的 `state.result` 多为非 hit 或 hit-无分析，analyticsState 默认 vm=null 不渲染分析块，不受影响。

- [ ] **Step 2: 跑确认失败**
Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts`
Expected: 新增 4 用例 FAIL（分析块未实现）；现有用例需仍 PASS（若因新 mock 报错，确认 analyticsState mock 加对）。

- [ ] **Step 3: 改组件 `<script setup>`**

`HistoryPage.vue` 顶部 import 加：
```typescript
import { useSkuAnalyticsStore } from "../../stores/skuAnalytics";
```
`const store = useHistoryStore();` 之后加：
```typescript
const analyticsStore = useSkuAnalyticsStore();
```
`runSearch` 改为（命中触发 analytics load，非命中 reset）：
```typescript
async function runSearch(query: string) {
  await store.load(query);
  if (!store.error && store.result && store.result.kind === "hit") {
    pushRecent(query);
    analyticsStore.load(store.result.current.barcode);
  } else {
    analyticsStore.reset();
  }
}
```
`doReset` 加一行 `analyticsStore.reset();`：
```typescript
function doReset() {
  q.value = "";
  store.reset();
  analyticsStore.reset();
}
```
加格式化 helper（SLA/PUR 显示用）：
```typescript
const fmtPct = (v: number | null) => (v == null ? "—" : `${v}%`);
const eur = (v: number | null) => (v == null ? "—" : `€${v.toFixed(2)}`);
const dayN = (v: number | null) => (v == null ? "—" : `${v} 天`);
```

- [ ] **Step 4: 改组件模板**

在命中态 `</dl>`（概况结束）之后、`<div class="history__timeline">` 之前，插入分析块：

```html
      <section class="history__analytics">
        <p v-if="analyticsStore.loading" class="history__msg">分析加载中…</p>
        <p v-else-if="analyticsStore.error" class="history__error">分析加载失败：{{ analyticsStore.error }}</p>
        <template v-else-if="analyticsStore.vm">
          <div class="history__sec-hd">销售分析</div>
          <div class="history__metrics">
            <div class="history__kv"><span>总销量</span><b>{{ analyticsStore.vm.sales.totalQty }}</b></div>
            <div class="history__kv"><span>总营收</span><b>{{ eur(analyticsStore.vm.sales.totalRevenue) }}</b></div>
            <div class="history__kv"><span>独立客户</span><b>{{ analyticsStore.vm.sales.uniqueCustomers }}</b></div>
            <div class="history__kv"><span>寿命</span><b>{{ analyticsStore.vm.sales.lifespanDays }} 天</b></div>
            <div class="history__kv"><span>12 周趋势</span><b>{{ fmtPct(analyticsStore.vm.sales.trendSlopePctPerWeek) }}/周</b></div>
          </div>

          <div class="history__cards">
            <div class="history__card">
              <div class="history__card-hd">CN 中国</div>
              <div>销量 <b>{{ analyticsStore.vm.cn.qty }}</b> · 客户 <b>{{ analyticsStore.vm.cn.uniqueCustomers }}</b></div>
              <div>单笔最大 <b>{{ analyticsStore.vm.cn.maxSingleQty }}</b> · 月频 <b>{{ analyticsStore.vm.cn.avgFreqPerMonth }}</b></div>
              <div>上次 <b>{{ analyticsStore.vm.cn.lastAt ?? "—" }}</b></div>
            </div>
            <div class="history__card">
              <div class="history__card-hd">老外</div>
              <div>销量 <b>{{ analyticsStore.vm.fo.qty }}</b> · 客户 <b>{{ analyticsStore.vm.fo.uniqueCustomers }}</b></div>
              <div>单笔最大 <b>{{ analyticsStore.vm.fo.maxSingleQty }}</b> · 月频 <b>{{ analyticsStore.vm.fo.avgFreqPerMonth }}</b></div>
              <div>上次 <b>{{ analyticsStore.vm.fo.lastAt ?? "—" }}</b></div>
            </div>
          </div>

          <div class="history__sec-hd">采购面</div>
          <div class="history__metrics">
            <div class="history__kv"><span>库存推算</span><b>{{ analyticsStore.vm.purchase.stockBalance }}</b></div>
            <div class="history__kv"><span>毛利率</span><b>{{ fmtPct(analyticsStore.vm.purchase.avgMarginPct) }}</b></div>
            <div class="history__kv"><span>365 天采购</span><b>{{ analyticsStore.vm.purchase.purchaseFreq365d }}</b></div>
            <div class="history__kv"><span>上次采购</span><b>{{ dayN(analyticsStore.vm.purchase.lastPurchaseDaysAgo) }}</b></div>
          </div>
        </template>
      </section>
```

`<style scoped>` 末尾追加（token 对照现有，全部已在本文件用过）：
```css
.history__analytics { margin-bottom: var(--sp-6); }
.history__sec-hd { font-size: var(--fs-sm); color: var(--ink-2); margin: var(--sp-4) 0 var(--sp-2); }
.history__metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--sp-3); margin-bottom: var(--sp-3); }
.history__kv { display: flex; flex-direction: column; gap: 2px; }
.history__kv span { font-size: var(--fs-sm); color: var(--ink-2); }
.history__kv b { font-family: var(--mono); }
.history__cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--sp-3); margin-bottom: var(--sp-3); }
.history__card { border: 1px solid var(--line-soft); border-radius: var(--r-sm); padding: var(--sp-3); font-size: var(--fs-sm); }
.history__card-hd { color: var(--ink-2); margin-bottom: var(--sp-1); }
```

- [ ] **Step 5: 跑确认通过 + typecheck**
Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts` → 全 PASS（原有 + 新 4）
Run: `cd frontend && npx vitest run src/pages/history/no-analytics.test.ts` → 2 PASS（HC-2 守护：新端点 `/api/history/<bc>/analytics` 不含 `/analytics/sku`，HistoryPage 引 skuAnalytics store 不破守护）
Run: `cd frontend && npm run typecheck` → 0

- [ ] **Step 6: 提交**
```bash
git add frontend/src/pages/history/HistoryPage.vue frontend/src/pages/history/HistoryPage.test.ts
git commit -m "feat(history): HistoryPage 集成分析块（SLA+PUR+客户拆分，命中触发/失败隔离）"
```

---

## Task 6: 全量验收

- [ ] **Step 1: 后端全量 + ruff**
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m pytest tests/ -q` → 全绿（新增 test_history_analytics_api 4；既有不回归）
Run: `C:/Dev/label-sync/.venv/Scripts/python.exe -m ruff check app/ tests/test_history_analytics_api.py` → clean
- [ ] **Step 2: TS 漂移** — Run: `C:/Dev/label-sync/.venv/Scripts/python.exe tools/gen_ts_types.py --check` → 0
- [ ] **Step 3: 前端全量 + typecheck + build**
Run: `cd frontend && npm run test && npm run typecheck && npm run build` → vitest 全绿、vue-tsc 0、build ok
- [ ] **Step 4: 本地人工验证**
```
./dev.ps1 -Frontend
```
浏览器 `http://localhost:5173/ui/` → 货号历史 → 查一个有销售的真实货号（本地 PG 空则可能零值，但分析块结构应渲染）：
- 命中后概况下方出现 销售分析 / 客户拆分 / 采购面
- 关掉网络/造 500 → 分析块显"分析加载失败"，但 hero/概况/历史时间线仍在（HC-A4）
- console 无 error
- [ ] **Step 5: 收尾**
- 更新 memory `project_frontend_decoupling.md`：货号历史 Phase 2a（SLA+PUR+客户拆分，瘦端点）已迁。
- 按 `superpowers:finishing-a-development-branch`：开 PR → CI 双矩阵 → squash merge → 前端手动 redeploy。

---

## 自审记录
1. **spec 覆盖**：HC-A1（不动旧页/router/nav，Task5 只扩组件）、HC-A2（Task1 瘦端点只调 3 函数只返回 4 key）、HC-A3（Task1 strict schema 逐字段核实）、HC-A4（Task4 独立 store + load 清 vm + 401 吞；Task5 失败隔离测试 + 401 不显块内错误）、HC-A5（Task1 key-set 断言 + Task3 VM 只含 2a）。canonical contract = Task1 schema。状态卫生（旧 vm 清 / 非命中 reset）= Task4 测试 + Task5 runSearch/doReset。
2. **占位符扫描**：每步完整代码；唯一判断点 = Task5 token（全部已在 HistoryPage.vue 现用，无新 token）。无 TBD。
3. **类型一致性**：schema 字段 ↔ compute 输出逐字段核；VM 名（sales/purchase/cn/fo + camelCase）在 types/normalize/store/组件/测试全程一致；端点 `/api/history/<bc>/analytics` 在 store/测试一致；`analyticsStore.load/reset` 签名一致。
