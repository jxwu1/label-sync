# 货号历史 Vue Phase 3 实施 Plan（SVG 销售/进价时间线）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `/ui/history` 命中态加一张销售/进价走势图（36 月销量柱 + 156 周进价阶梯折线），数据走新建瘦端点 `GET /api/history/<bc>/timeline`，渲染在独立 `TimelineChart.vue` 组件。

**Architecture:** additive 迁移（旧页/旧端点/「旧版」深链不动）。后端瘦端点 strict schema；前端独立 `useSkuTimelineStore`（HC-B7 并发守卫）+ 独立 `TimelineChart.vue`（封装全部 SVG 计算，干净响应式：正常 viewBox + SVG 内文字 + 共享日期域）。月柱与周进价点映射同一日期域避免时间漂移；负净月画可命中退货三角；no-analytics 守卫扩到扫全部 sku* store。

**Tech Stack:** Flask + pydantic（extra=forbid）+ Vue 3 + Pinia + TypeScript + vitest + @vue/test-utils + pytest。

**Spec:** `docs/superpowers/specs/2026-06-18-history-vue-phase3-design.md`（HC-P3-1~9，三轮审查 APPROVE）。

**前置（coder 必读）：**
- 分支已在 `feat/history-vue-phase3`。
- 后端测试 `pytest tests/test_history_timeline_api.py -v`（tmp sqlite）。
- 前端测试 `cd frontend && npx vitest run <file>`；类型 `npm run typecheck`。
- 改 schemas_api.py 后必跑 `python tools/gen_ts_types.py`（`--check` 守护）。
- store 的 `seq` 定义在 defineStore 闭包内（非模块级）。
- 数据来源已核：`compute_weekly_timeline`（metrics.py:213）每周 `{week_start,sale_qty,purchase_unit_price,raw_unit_price_local,currency_local}`；`compute_monthly_sales`（metrics.py:320）每月 `{month_start,sale_qty,retail_qty}`，sale_qty 含退货可为负。

---

## Task 1: 后端 schema + 注册 + TS 同步

**Files:**
- Modify: `app/schemas_api.py`（`SkuExtrasResponse` 之后追加 + `API_MODELS` 追加）
- Generated: `frontend/src/api/types.gen.ts`

- [ ] **Step 1: 追加 schema**

在 `app/schemas_api.py` 的 `SkuExtrasResponse` 类之后追加：
```python
class TimelineWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: str
    sale_qty: int
    purchase_unit_price: float | None
    raw_unit_price_local: float | None
    currency_local: str


class MonthlySale(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month_start: str
    sale_qty: int
    retail_qty: int


class SkuTimelineResponse(BaseModel):
    """GET /api/history/<barcode>/timeline 200 响应（Phase 3 canonical 契约）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    timeline: list[TimelineWeek]
    monthly_sales: list[MonthlySale]
```

- [ ] **Step 2: 注册 API_MODELS**

`API_MODELS` 列表末尾追加 `SkuTimelineResponse,`（在 `SkuExtrasResponse,` 之后）。

- [ ] **Step 3: 生成 + 校验 TS**

Run: `python tools/gen_ts_types.py && python tools/gen_ts_types.py --check`
Expected: 第二条退出码 0。
Run: `grep -c "SkuTimelineResponse\|TimelineWeek\|MonthlySale" frontend/src/api/types.gen.ts`
Expected: ≥ 3。

- [ ] **Step 4: ruff**

Run: `ruff format app/schemas_api.py && ruff check app/schemas_api.py`
Expected: clean。

- [ ] **Step 5: Commit**

```bash
git add app/schemas_api.py frontend/src/api/types.gen.ts
git commit -m "feat(history): Phase 3 timeline 端点 pydantic schema + TS 类型"
```

---

## Task 2: 后端端点 + 测试（TDD）

**Files:**
- Modify: `app/routes/history.py`（`api_bp` 加 `timeline` 路由）
- Test: `tests/test_history_timeline_api.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_history_timeline_api.py`。先 READ `tests/test_history_extras_api.py` 复用其 fixtures/helpers（`real_app` / `_exec` / `_seed_stockpile` / `_seed_event` / 登录或 X-Upload-Token、`clear_list_sku_summary_cache`）。写：
```python
def test_timeline_unauth_returns_401(real_app):
    resp = real_app.test_client().get("/api/history/12345/timeline")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "unauthenticated"


def test_timeline_hit_key_set_and_shapes(real_app, seed_sku_with_events):
    bc = seed_sku_with_events
    body = logged_in_get(real_app, f"/api/history/{bc}/timeline").get_json()
    assert set(body.keys()) == {"ok", "timeline", "monthly_sales"}
    assert len(body["timeline"]) == 156
    assert len(body["monthly_sales"]) == 36
    wk = body["timeline"][0]
    assert set(wk.keys()) == {
        "week_start", "sale_qty", "purchase_unit_price",
        "raw_unit_price_local", "currency_local",
    }
    mo = body["monthly_sales"][0]
    assert set(mo.keys()) == {"month_start", "sale_qty", "retail_qty"}


def test_timeline_no_events_sku_ok(real_app, seed_stockpile_only):
    # 无事件 SKU（非空 barcode，无 events）→ 200 合法零值（空 barcode 匹配不上 path route，不测）
    bc = seed_stockpile_only
    body = logged_in_get(real_app, f"/api/history/{bc}/timeline").get_json()
    assert body["ok"] is True
    assert all(w["sale_qty"] == 0 and w["purchase_unit_price"] is None for w in body["timeline"])
    assert all(m["sale_qty"] == 0 and m["retail_qty"] == 0 for m in body["monthly_sales"])
```
> coder：`seed_sku_with_events` / `seed_stockpile_only` / `logged_in_get` 按 `test_history_extras_api.py` 现有写法照搬/复用；该文件 import_from_dataframe 填 stockpile + _seed_event 插事件。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_history_timeline_api.py -v`
Expected: FAIL（路由 404）。

- [ ] **Step 3: 实现端点**

在 `app/routes/history.py` 的 `api_bp` 上加：
```python
@api_bp.get("/<barcode>/timeline")
def timeline(barcode: str):
    from app.schemas_api import SkuTimelineResponse
    from app.services import analytics as analytics_service

    bc = barcode.strip()
    payload = {
        "ok": True,
        "timeline": analytics_service.compute_weekly_timeline(bc),
        "monthly_sales": analytics_service.compute_monthly_sales(bc),
    }
    return jsonify(SkuTimelineResponse.model_validate(payload).model_dump())
```
> coder：确认 `compute_weekly_timeline` / `compute_monthly_sales` 经 `app.services.analytics` 包导出（metrics.py 内定义，包 re-export；`analytics.py` 旧端点已 `analytics_service.compute_weekly_timeline` 用过）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_history_timeline_api.py -v`
Expected: 3 PASS。

- [ ] **Step 5: ruff + commit**

```bash
ruff format app/routes/history.py tests/test_history_timeline_api.py && ruff check app/routes/history.py tests/test_history_timeline_api.py
git add app/routes/history.py tests/test_history_timeline_api.py
git commit -m "feat(history): Phase 3 timeline 瘦端点"
```

---

## Task 3: 后端 CN + 原子失败测试

**Files:** Modify `tests/test_history_timeline_api.py`

- [ ] **Step 1: 加测试**

```python
def test_timeline_cn_sku_raw_price_rmb(real_app, seed_cn_sku_with_purchase):
    # seed: origin=CN 的 SKU + 一笔 purchase event（unit_price 为 RMB）
    bc = seed_cn_sku_with_purchase
    body = logged_in_get(real_app, f"/api/history/{bc}/timeline").get_json()
    priced = [w for w in body["timeline"] if w["purchase_unit_price"] is not None]
    assert priced, "应至少一周有进价"
    w = priced[0]
    assert w["currency_local"] == "RMB"
    assert w["raw_unit_price_local"] is not None  # 原始 RMB 单价
    assert w["purchase_unit_price"] > 0            # EUR 落地


import pytest


@pytest.mark.parametrize("fn_name", ["compute_weekly_timeline", "compute_monthly_sales"])
def test_timeline_atomic_failure_500(real_app, seed_sku_with_events, monkeypatch, fn_name):
    from app.services import analytics as analytics_service

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(analytics_service, fn_name, boom)
    bc = seed_sku_with_events
    resp = logged_in_get_no_propagate(real_app, f"/api/history/{bc}/timeline")
    assert resp.status_code == 500
```
> coder：`seed_cn_sku_with_purchase` —— stockpile.supplier_id 设成 CN 供应商前缀（参照 `compute_weekly_timeline` 的 `classify_origin`，或直接用一个已知 CN origin 的 supplier_id；读 `app/services/sku_origin.py` / `classify_origin` 确认判定）。`logged_in_get_no_propagate` = 带 `app.config["PROPAGATE_EXCEPTIONS"]=False` 的请求（参照 `test_history_extras_api.py` 的 `_get_no_propagate`，TESTING=True 下才能拿到 500 而非重抛）。

- [ ] **Step 2: 跑 + 全后端**

Run: `pytest tests/test_history_timeline_api.py -v` → 全 PASS。
Run: `pytest tests/ -q` → 全绿无回归。

- [ ] **Step 3: Commit**

```bash
git add tests/test_history_timeline_api.py
git commit -m "test(history): Phase 3 timeline CN 货 + 原子失败覆盖"
```

---

## Task 4: 前端 VM + normalize（TDD）

**Files:**
- Create: `frontend/src/pages/history/timeline-types.ts`
- Create: `frontend/src/pages/history/timeline-normalize.ts`
- Test: `frontend/src/pages/history/timeline-normalize.test.ts`

- [ ] **Step 1: VM 类型**

`frontend/src/pages/history/timeline-types.ts`：
```typescript
export interface TimelineWeekVM {
  weekStart: string;
  saleQty: number;
  purchaseUnitPrice: number | null;
  rawUnitPriceLocal: number | null;
  currencyLocal: string;
}
export interface MonthlySaleVM {
  monthStart: string;
  saleQty: number;
  retailQty: number;
}
export interface TimelineVM {
  weeks: TimelineWeekVM[];
  monthlySales: MonthlySaleVM[];
}
```

- [ ] **Step 2: 失败测试**

`frontend/src/pages/history/timeline-normalize.test.ts`：
```typescript
import { describe, it, expect } from "vitest";
import { normalizeTimeline } from "./timeline-normalize";
import type { SkuTimelineResponse } from "../../api/types.gen";

const raw: SkuTimelineResponse = {
  ok: true,
  timeline: [
    { week_start: "2024-01-01", sale_qty: 3, purchase_unit_price: 5.5, raw_unit_price_local: 42, currency_local: "RMB" },
    { week_start: "2024-01-08", sale_qty: 0, purchase_unit_price: null, raw_unit_price_local: null, currency_local: "RMB" },
  ],
  monthly_sales: [
    { month_start: "2024-01-01", sale_qty: 10, retail_qty: 2 },
    { month_start: "2024-02-01", sale_qty: -4, retail_qty: 0 },
  ],
} as unknown as SkuTimelineResponse;

describe("normalizeTimeline", () => {
  it("maps snake to camel, preserves nulls and negative", () => {
    const vm = normalizeTimeline(raw);
    expect(vm.weeks[0].purchaseUnitPrice).toBe(5.5);
    expect(vm.weeks[0].rawUnitPriceLocal).toBe(42);
    expect(vm.weeks[1].purchaseUnitPrice).toBeNull();
    expect(vm.monthlySales[1].saleQty).toBe(-4);
    expect(vm.weeks).toHaveLength(2);
    expect(vm.monthlySales).toHaveLength(2);
  });
});
```
Run: `cd frontend && npx vitest run src/pages/history/timeline-normalize.test.ts` → FAIL。

- [ ] **Step 3: 实现 normalize**

`frontend/src/pages/history/timeline-normalize.ts`：
```typescript
import type { SkuTimelineResponse } from "../../api/types.gen";
import type { TimelineVM } from "./timeline-types";

export function normalizeTimeline(raw: SkuTimelineResponse): TimelineVM {
  return {
    weeks: (raw.timeline ?? []).map((w) => ({
      weekStart: w.week_start,
      saleQty: w.sale_qty ?? 0,
      purchaseUnitPrice: w.purchase_unit_price ?? null,
      rawUnitPriceLocal: w.raw_unit_price_local ?? null,
      currencyLocal: w.currency_local,
    })),
    monthlySales: (raw.monthly_sales ?? []).map((m) => ({
      monthStart: m.month_start,
      saleQty: m.sale_qty ?? 0,
      retailQty: m.retail_qty ?? 0,
    })),
  };
}
```

- [ ] **Step 4: 跑 + typecheck**

Run: `cd frontend && npx vitest run src/pages/history/timeline-normalize.test.ts && npm run typecheck` → PASS + 0。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/history/timeline-types.ts frontend/src/pages/history/timeline-normalize.ts frontend/src/pages/history/timeline-normalize.test.ts
git commit -m "feat(history): Phase 3 timeline VM 类型 + normalize"
```

---

## Task 5: useSkuTimelineStore（TDD，HC-B7）

**Files:**
- Create: `frontend/src/stores/skuTimeline.ts`
- Test: `frontend/src/stores/skuTimeline.test.ts`

- [ ] **Step 1: 失败测试**

`frontend/src/stores/skuTimeline.test.ts`（镜像 `skuExtras.test.ts` 结构）：
```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";

const apiGet = vi.fn();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiGet: (...a: unknown[]) => apiGet(...a) };
});

import { useSkuTimelineStore } from "./skuTimeline";
import { UnauthenticatedError } from "../api/client";

const ok = { ok: true, timeline: [], monthly_sales: [] };

beforeEach(() => { setActivePinia(createPinia()); apiGet.mockReset(); });

describe("useSkuTimelineStore", () => {
  it("load fills vm + right endpoint", async () => {
    apiGet.mockResolvedValueOnce(ok);
    const s = useSkuTimelineStore();
    await s.load("12345");
    expect(apiGet).toHaveBeenCalledWith("/api/history/12345/timeline");
    expect(s.vm).not.toBeNull();
  });
  it("failure fills error", async () => {
    apiGet.mockRejectedValueOnce(new Error("boom"));
    const s = useSkuTimelineStore();
    await s.load("x");
    expect(s.error).toBe("boom");
    expect(s.vm).toBeNull();
  });
  it("swallows UnauthenticatedError", async () => {
    apiGet.mockRejectedValueOnce(new UnauthenticatedError());
    const s = useSkuTimelineStore();
    await s.load("x");
    expect(s.error).toBeNull();
  });
  it("HC-B7 stale: A after B, B wins", async () => {
    let resolveA: (v: unknown) => void = () => {};
    apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
    apiGet.mockResolvedValueOnce({ ...ok, monthly_sales: [{ month_start: "2024-01-01", sale_qty: 9, retail_qty: 0 }] });
    const s = useSkuTimelineStore();
    const pA = s.load("A");
    const pB = s.load("B");
    await pB;
    resolveA(ok);
    await pA;
    expect(s.vm?.monthlySales.length).toBe(1); // B
  });
  it("HC-B7 reset cancels pending", async () => {
    let resolveA: (v: unknown) => void = () => {};
    apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
    const s = useSkuTimelineStore();
    const pA = s.load("A");
    s.reset();
    resolveA(ok);
    await pA;
    expect(s.vm).toBeNull();
  });
});
```
Run: `cd frontend && npx vitest run src/stores/skuTimeline.test.ts` → FAIL。

- [ ] **Step 2: 实现 store**

`frontend/src/stores/skuTimeline.ts`：
```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { SkuTimelineResponse } from "../api/types.gen";
import { normalizeTimeline } from "../pages/history/timeline-normalize";
import type { TimelineVM } from "../pages/history/timeline-types";

export const useSkuTimelineStore = defineStore("skuTimeline", () => {
  const vm = ref<TimelineVM | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  let seq = 0; // HC-B7 单调 request-id（闭包级）

  async function load(barcode: string) {
    const my = ++seq;
    loading.value = true;
    error.value = null;
    vm.value = null;
    try {
      const raw = await apiGet<SkuTimelineResponse>(
        `/api/history/${encodeURIComponent(barcode)}/timeline`,
      );
      if (my !== seq) return;
      vm.value = normalizeTimeline(raw);
    } catch (e) {
      if (my !== seq) return;
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === seq) loading.value = false;
    }
  }

  function reset() {
    seq++;
    vm.value = null;
    error.value = null;
    loading.value = false;
  }

  return { vm, loading, error, load, reset };
});
```

- [ ] **Step 3: 跑 + typecheck + commit**

Run: `cd frontend && npx vitest run src/stores/skuTimeline.test.ts && npm run typecheck` → 5 PASS + 0。
```bash
git add frontend/src/stores/skuTimeline.ts frontend/src/stores/skuTimeline.test.ts
git commit -m "feat(history): Phase 3 useSkuTimelineStore（含 HC-B7 stale/reset 守卫）"
```

---

## Task 6: TimelineChart.vue 组件（TDD，核心）

**Files:**
- Create: `frontend/src/pages/history/TimelineChart.vue`
- Test: `frontend/src/pages/history/TimelineChart.test.ts`

实现 HC-P3-6~9：共享日期域、负净三角、真 step 折线、同价分支、SVG `<title>`、轴 anchor、hasData。

- [ ] **Step 1: 写失败测试**

`frontend/src/pages/history/TimelineChart.test.ts`：
```typescript
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import TimelineChart from "./TimelineChart.vue";
import type { TimelineWeekVM, MonthlySaleVM } from "./timeline-types";

function wk(p: Partial<TimelineWeekVM> & { weekStart: string }): TimelineWeekVM {
  return { saleQty: 0, purchaseUnitPrice: null, rawUnitPriceLocal: null, currencyLocal: "EUR", ...p };
}
function mo(monthStart: string, saleQty = 0, retailQty = 0): MonthlySaleVM {
  return { monthStart, saleQty, retailQty };
}

describe("TimelineChart", () => {
  it("hasData=false → 无数据占位，无柱无线", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-01-01" })],
      monthlySales: [mo("2024-01-01", 0, 0)],
    }});
    expect(w.text()).toContain("无数据");
    expect(w.findAll("rect").length).toBe(0);
    expect(w.find("path").exists()).toBe(false);
  });

  it("只有采购无销售 → 画折线无柱", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [
        wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
        wk({ weekStart: "2024-01-08" }),
      ],
      monthlySales: [mo("2024-01-01", 0, 0)],
    }});
    expect(w.text()).not.toContain("无数据");
    expect(w.find("path.tml-price-line").exists()).toBe(true);
  });

  it("只有销售无采购 → 画柱无折线", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-01-01" })],
      monthlySales: [mo("2024-01-01", 8, 0)],
    }});
    expect(w.findAll("rect.tml-bar").length).toBe(1);
    expect(w.find("path.tml-price-line").exists()).toBe(false);
  });

  it("负净月不产生负 height + 可命中退货标记", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-02-01" })],
      monthlySales: [mo("2024-02-01", -5, 0)],
    }});
    // 无负 height
    for (const r of w.findAll("rect")) {
      const h = Number(r.attributes("height") ?? "0");
      expect(h).toBeGreaterThanOrEqual(0);
    }
    const marker = w.find('[data-kind="net-return"]');
    expect(marker.exists()).toBe(true);
    expect(marker.find("title").text()).toContain("净退货");
  });

  it("红队：单负净月无采购 → hasData=true 且退货标记可命中", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-02-01" })],
      monthlySales: [mo("2024-02-01", -3, 0)],
    }});
    expect(w.text()).not.toContain("无数据");
    expect(w.find('[data-kind="net-return"]').exists()).toBe(true);
  });

  it("两次不同进价 → path 含垂直跳变（step）", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [
        wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
        wk({ weekStart: "2024-02-01", purchaseUnitPrice: 8, rawUnitPriceLocal: 8 }),
      ],
      monthlySales: [mo("2024-01-01", 1, 0)],
    }});
    const d = w.find("path.tml-price-line").attributes("d")!;
    // 解析 d 的点，断言存在一对相邻点 x 近似相等而 y 不同（垂直段）
    const pts = [...d.matchAll(/[ML]\s*([\d.]+)[ ,]([\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
    let hasVertical = false;
    for (let i = 1; i < pts.length; i++) {
      if (Math.abs(pts[i][0] - pts[i - 1][0]) < 0.5 && Math.abs(pts[i][1] - pts[i - 1][1]) > 0.5) hasVertical = true;
    }
    expect(hasVertical).toBe(true);
  });

  it("同价分支 → 右轴单 tick", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [
        wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
        wk({ weekStart: "2024-02-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
      ],
      monthlySales: [mo("2024-01-01", 1, 0)],
    }});
    expect(w.findAll("text.tml-yr").length).toBe(1);
  });

  it("X 共享日期域：采购周落在所属月柱 X 区间内", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2025-03-10", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 })],
      monthlySales: [mo("2025-02-01", 1, 0), mo("2025-03-01", 1, 0), mo("2025-04-01", 1, 0)],
    }});
    const dot = w.find("circle.tml-dot");
    expect(dot.exists()).toBe(true);
    const dotX = Number(dot.attributes("cx"));
    // 找 2025-03 柱
    const marBar = w.findAll("rect.tml-bar").find((r) => r.attributes("data-month") === "2025-03-01")!;
    const bx = Number(marBar.attributes("x"));
    const bw = Number(marBar.attributes("width"));
    expect(dotX).toBeGreaterThanOrEqual(bx);
    expect(dotX).toBeLessThanOrEqual(bx + bw);
  });

  it("窄容器：X 首标签 anchor=start、末标签 anchor=end，x 在 [0,W]", () => {
    const months = Array.from({ length: 12 }, (_, i) =>
      mo(`2024-${String(i + 1).padStart(2, "0")}-01`, 1, 0));
    const w = mount(TimelineChart, { props: { weeks: [wk({ weekStart: "2024-01-01" })], monthlySales: months }});
    const labels = w.findAll("text.tml-xlabel");
    expect(labels.length).toBeGreaterThanOrEqual(2);
    const first = labels[0], last = labels[labels.length - 1];
    expect(first.attributes("text-anchor")).toBe("start");
    expect(last.attributes("text-anchor")).toBe("end");
    for (const l of [first, last]) {
      const x = Number(l.attributes("x"));
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(1000);
    }
  });

  it("CN tooltip 含 ¥ 与 €", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5.4, rawUnitPriceLocal: 42, currencyLocal: "RMB" })],
      monthlySales: [mo("2024-01-01", 1, 0)],
    }});
    const t = w.find("circle.tml-dot title").text();
    expect(t).toContain("¥");
    expect(t).toContain("€");
  });
});
```
Run: `cd frontend && npx vitest run src/pages/history/TimelineChart.test.ts` → FAIL（组件不存在）。

- [ ] **Step 2: 实现 TimelineChart.vue**

`frontend/src/pages/history/TimelineChart.vue`：
```vue
<script setup lang="ts">
import { computed } from "vue";
import type { TimelineWeekVM, MonthlySaleVM } from "./timeline-types";

const props = defineProps<{ weeks: TimelineWeekVM[]; monthlySales: MonthlySaleVM[] }>();

// viewBox 几何（单位 = viewBox units，非 CSS px）
const W = 1000, H = 260, padL = 44, padR = 52, padT = 16, padB = 28;
const innerW = W - padL - padR;
const innerH = H - padT - padB;
const baselineY = padT + innerH;
const BAR_GAP = 3;

function dayNum(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86400000;
}
function nextMonthDayNum(monthStartIso: string): number {
  const [y, m] = monthStartIso.slice(0, 10).split("-").map(Number);
  const ny = m === 12 ? y + 1 : y;
  const nm = m === 12 ? 1 : m + 1;
  return Date.UTC(ny, nm - 1, 1) / 86400000;
}

const hasData = computed(
  () =>
    props.monthlySales.some((m) => m.saleQty + m.retailQty !== 0) ||
    props.weeks.some((w) => w.purchaseUnitPrice != null),
);

// 共享日期域（HC-P3-9）
const domain = computed(() => {
  const starts: number[] = [];
  if (props.weeks.length) starts.push(dayNum(props.weeks[0].weekStart));
  if (props.monthlySales.length) starts.push(dayNum(props.monthlySales[0].monthStart));
  const ends: number[] = [];
  if (props.weeks.length) ends.push(dayNum(props.weeks[props.weeks.length - 1].weekStart) + 7);
  if (props.monthlySales.length)
    ends.push(nextMonthDayNum(props.monthlySales[props.monthlySales.length - 1].monthStart));
  const t0 = starts.length ? Math.min(...starts) : 0;
  const t1 = ends.length ? Math.max(...ends) : t0 + 1;
  return { t0, span: Math.max(1, t1 - t0) };
});
function x(day: number): number {
  const { t0, span } = domain.value;
  return padL + ((day - t0) / span) * innerW;
}

const maxQ = computed(() =>
  Math.max(1, ...props.monthlySales.map((m) => Math.max(0, m.saleQty + m.retailQty))),
);

interface Bar { x: number; w: number; h: number; y: number; title: string; month: string; }
interface ReturnMark { cx: number; title: string; month: string; }
const bars = computed<Bar[]>(() => {
  const out: Bar[] = [];
  for (const m of props.monthlySales) {
    const net = m.saleQty + m.retailQty;
    if (net <= 0) continue;
    const x0 = x(dayNum(m.monthStart));
    const x1 = x(nextMonthDayNum(m.monthStart));
    const h = (net / maxQ.value) * innerH * 0.85;
    out.push({
      x: x0 + BAR_GAP / 2,
      w: Math.max(1, x1 - x0 - BAR_GAP),
      h,
      y: baselineY - h,
      title: `${m.monthStart.slice(0, 7)}：${net} 件`,
      month: m.monthStart,
    });
  }
  return out;
});
const returnMarks = computed<ReturnMark[]>(() => {
  const out: ReturnMark[] = [];
  for (const m of props.monthlySales) {
    const net = m.saleQty + m.retailQty;
    if (net >= 0) continue;
    const x0 = x(dayNum(m.monthStart));
    const x1 = x(nextMonthDayNum(m.monthStart));
    out.push({
      cx: (x0 + x1) / 2,
      title: `${m.monthStart.slice(0, 7)}：净退货 ${Math.abs(net)} 件`,
      month: m.monthStart,
    });
  }
  return out;
});
// 退货三角 path（底 8 × 高 6 viewBox units，尖朝上，底贴 baseline 上方 1）
function trianglePath(cx: number): string {
  const half = 4, h = 6, baseY = baselineY - 1;
  return `M${(cx - half).toFixed(1)},${baseY} L${(cx + half).toFixed(1)},${baseY} L${cx.toFixed(1)},${(baseY - h).toFixed(1)} Z`;
}

// 进价：前向填充 + 反向外推
const priceInfo = computed(() => {
  const raw = props.weeks.map((w) => w.purchaseUnitPrice);
  const firstIdx = raw.findIndex((p) => p != null);
  const valid = raw.filter((p): p is number => p != null);
  const hasPrice = valid.length > 0;
  const filled: (number | null)[] = new Array(raw.length).fill(null);
  if (hasPrice) {
    let last = raw[firstIdx]!;
    for (let i = 0; i < raw.length; i++) {
      if (raw[i] != null) last = raw[i]!;
      filled[i] = last;
    }
  }
  const maxP = hasPrice ? Math.max(...valid) : 1;
  const minP = hasPrice ? Math.min(...valid) : 0;
  const sameValue = hasPrice && maxP === minP;
  return { filled, hasPrice, maxP, minP, sameValue };
});
function weekMidX(i: number): number {
  return x(dayNum(props.weeks[i].weekStart) + 3.5);
}
function priceY(p: number): number {
  const { sameValue, maxP } = priceInfo.value;
  if (sameValue) return padT + innerH * 0.4;
  const range = Math.max(0.01, maxP);
  return baselineY - (p / range) * innerH * 0.85;
}
// 真 step path：水平保持到下一点 x，再垂直到下一点 y
const pricePath = computed(() => {
  const { filled, hasPrice } = priceInfo.value;
  if (!hasPrice) return "";
  let d = "";
  let prevY: number | null = null;
  for (let i = 0; i < filled.length; i++) {
    const p = filled[i];
    if (p == null) continue;
    const px = weekMidX(i);
    const py = priceY(p);
    if (prevY === null) {
      d += `M${px.toFixed(1)},${py.toFixed(1)}`;
    } else {
      d += ` L${px.toFixed(1)},${prevY.toFixed(1)} L${px.toFixed(1)},${py.toFixed(1)}`;
    }
    prevY = py;
  }
  return d;
});
interface Dot { cx: number; cy: number; title: string; }
const dots = computed<Dot[]>(() => {
  const out: Dot[] = [];
  props.weeks.forEach((w, i) => {
    if (w.rawUnitPriceLocal == null || w.purchaseUnitPrice == null) return;
    const cy = priceY(w.purchaseUnitPrice);
    let title = `${w.weekStart}：€${w.purchaseUnitPrice.toFixed(4)}`;
    if (w.currencyLocal === "RMB") {
      title = `${w.weekStart}：€${w.purchaseUnitPrice.toFixed(4)}（落地）← ¥${w.rawUnitPriceLocal}（含汇率+可用海运分摊）`;
    }
    out.push({ cx: weekMidX(i), cy, title });
  });
  return out;
});

// 左轴销量 ticks
const salesTicks = computed(() =>
  [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: baselineY - f * innerH * 0.85,
    label: String(Math.round(maxQ.value * f)),
  })),
);
// 右轴进价 ticks（同价单 tick）
const priceTicks = computed(() => {
  const { hasPrice, sameValue, maxP } = priceInfo.value;
  if (!hasPrice) return [];
  if (sameValue) return [{ y: padT + innerH * 0.4, label: `€${maxP.toFixed(2)}` }];
  return [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: baselineY - f * innerH * 0.85,
    label: `€${(maxP * f).toFixed(2)}`,
  }));
});
// X 月份标签（~7 个）
const xLabels = computed(() => {
  const ms = props.monthlySales;
  if (!ms.length) return [];
  const n = Math.min(7, ms.length);
  const out: { x: number; label: string; anchor: string }[] = [];
  for (let i = 0; i < n; i++) {
    const idx = Math.floor(((ms.length - 1) * i) / Math.max(1, n - 1));
    const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
    out.push({ x: x(dayNum(ms[idx].monthStart)), label: ms[idx].monthStart.slice(0, 7), anchor });
  }
  return out;
});
</script>

<template>
  <div class="tml-wrap">
    <div v-if="!hasData" class="tml-empty">无数据</div>
    <svg v-else class="tml-svg" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="xMidYMid meet">
      <!-- baseline -->
      <line :x1="padL" :x2="W - padR" :y1="baselineY" :y2="baselineY" stroke="var(--line)" stroke-width="1" />
      <!-- 月销量柱 -->
      <rect
        v-for="b in bars" :key="'b' + b.month" class="tml-bar"
        :x="b.x" :y="b.y" :width="b.w" :height="b.h" :data-month="b.month"
        fill="var(--accent)" opacity="0.85" rx="0.5"
      ><title>{{ b.title }}</title></rect>
      <!-- 负净退货三角 -->
      <path
        v-for="r in returnMarks" :key="'r' + r.month" data-kind="net-return" class="tml-return"
        :d="trianglePath(r.cx)" fill="var(--warn)"
      ><title>{{ r.title }}</title></path>
      <!-- 进价折线 -->
      <path v-if="pricePath" class="tml-price-line" :d="pricePath" fill="none"
        stroke="var(--warn)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
      <!-- 进货 dot -->
      <circle v-for="(d, i) in dots" :key="'d' + i" class="tml-dot"
        :cx="d.cx" :cy="d.cy" r="2.5" fill="var(--warn)"><title>{{ d.title }}</title></circle>
      <!-- 左轴销量 ticks -->
      <text v-for="(t, i) in salesTicks" :key="'sl' + i" class="tml-yl"
        :x="padL - 6" :y="t.y + 3" text-anchor="end" fill="var(--ink-2)" font-size="10">{{ t.label }}</text>
      <!-- 右轴进价 ticks -->
      <text v-for="(t, i) in priceTicks" :key="'yr' + i" class="tml-yr"
        :x="W - padR + 6" :y="t.y + 3" text-anchor="start" fill="var(--ink-2)" font-size="10">{{ t.label }}</text>
      <!-- X 月份标签 -->
      <text v-for="(l, i) in xLabels" :key="'xl' + i" class="tml-xlabel"
        :x="l.x" :y="baselineY + 16" :text-anchor="l.anchor" fill="var(--ink-2)" font-size="10">{{ l.label }}</text>
    </svg>
  </div>
</template>

<style scoped>
.tml-wrap { width: 100%; }
.tml-svg { width: 100%; height: auto; display: block; }
.tml-empty { padding: 24px 0; color: var(--ink-2); font-size: var(--fs-sm); text-align: center; }
</style>
```
> 颜色仅用 token 变量。`Date.UTC` 在浏览器/vitest 可用（项目无 workflow-sandbox 限制）。

- [ ] **Step 3: 跑测试**

Run: `cd frontend && npx vitest run src/pages/history/TimelineChart.test.ts`
Expected: 全 PASS。若某断言因几何细节失败，调实现/断言对齐（勿放宽语义：负 height/可命中标记/step 垂直/单 tick/日期域对齐/anchor 必须真成立）。

- [ ] **Step 4: typecheck + commit**

Run: `cd frontend && npm run typecheck` → 0。
```bash
git add frontend/src/pages/history/TimelineChart.vue frontend/src/pages/history/TimelineChart.test.ts
git commit -m "feat(history): Phase 3 TimelineChart.vue（共享日期域+step折线+退货三角+轴）"
```

---

## Task 7: HistoryPage 接线（TDD）

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue`
- Modify: `frontend/src/pages/history/HistoryPage.test.ts`

- [ ] **Step 1: 加失败测试**

在 `HistoryPage.test.ts` 追加（沿用 plain-object mock store 范式）：
```typescript
it("hit triggers timelineStore.load and renders chart after 概况 before SLA", async () => {
  // mock useSkuTimelineStore.vm = { weeks:[...], monthlySales:[...] }
  // 断言 timelineStore.load 被调 + 图容器渲染（含 TimelineChart 或其占位）
});
it("timeline failure shows chart error but P1/2a/2b intact", async () => {
  // timelineStore.error 置位 → 图块错误条; hero/概况/SLA/extras 仍渲染
});
it("timeline 401 → no chart error bar", async () => {});
it("non-hit calls timelineStore.reset", async () => {});
it("HC-B7 gating: stale search (load false) does NOT call timelineStore.load", async () => {});
```
> coder：mock 方式与 HistoryPage.test.ts 现有 analytics/extras store mock 一致；TimelineChart 可 stub（`global.stubs`）只验「图块在位 + load 触发 + 失败隔离」，不重复 TimelineChart 内部断言（那在 Task 6 已覆盖）。

- [ ] **Step 2: 跑确认失败**

Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts` → 新增 FAIL。

- [ ] **Step 3: 改 HistoryPage.vue**

1. `<script setup>` import `useSkuTimelineStore` + `TimelineChart`；`const timelineStore = useSkuTimelineStore()`。
2. runSearch 命中分支（已 `fresh` 门控）并列 `timelineStore.load(bc)`；非命中/失败 else 分支加 `timelineStore.reset()`。`doReset()` 加 `timelineStore.reset()`。
3. 模板：在「概况」块之后、「销售分析 SLA」块之前插入（仅 `store.result?.kind === 'hit'` 时）：
```vue
<section class="history__timeline">
  <div class="history__section-label">销售 / 进价走势</div>
  <div v-if="timelineStore.loading" class="history__hint">走势图加载中…</div>
  <div v-else-if="timelineStore.error" class="history__error history__error--timeline">{{ timelineStore.error }}</div>
  <TimelineChart v-else-if="timelineStore.vm"
    :weeks="timelineStore.vm.weeks" :monthly-sales="timelineStore.vm.monthlySales" />
</section>
```
   class 名沿用页面既有约定；错误条 class 不裹 P1/2a/2b（HC-P3-3）。

- [ ] **Step 4: 跑 + typecheck**

Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts && npm run typecheck` → PASS + 0。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.vue frontend/src/pages/history/HistoryPage.test.ts
git commit -m "feat(history): Phase 3 HistoryPage 接线走势图（概况后 SLA 前 + 失败隔离）"
```

---

## Task 8: no-analytics 守卫改造（HC-P3-5）

**Files:** Modify `frontend/src/pages/history/no-analytics.test.ts`

- [ ] **Step 1: 改守卫 + 自证扫到 skuTimeline**

把 `no-analytics.test.ts` 改为扫描全部新栈 store + 收紧 FORBIDDEN：
```typescript
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const storesDir = join(here, "..", "..", "stores");

// HC-P3-5：货号历史新栈不得调用 legacy analytics 端点（/analytics/sku 覆盖旧
// 胖端点含旧 timeline /analytics/sku/<bc>/timeline）。新瘦端点 /api/history/<bc>/...
// 不含该子串。裸 /timeline 已移除（会误伤新 timeline 瘦端点）。
const FORBIDDEN = ["/analytics/sku"];

const HISTORY_STORES = ["history.ts", "skuAnalytics.ts", "skuExtras.ts", "skuTimeline.ts"];

function sources(): { name: string; text: string }[] {
  const pageFiles = readdirSync(here)
    .filter((f) => (f.endsWith(".ts") || f.endsWith(".vue")) && !f.includes("no-analytics"))
    .map((f) => ({ name: `pages/history/${f}`, text: readFileSync(join(here, f), "utf-8") }));
  const storeFiles = HISTORY_STORES.map((f) => ({
    name: `stores/${f}`,
    text: readFileSync(join(storesDir, f), "utf-8"),
  }));
  return [...pageFiles, ...storeFiles];
}

describe("货号历史新栈不调用 legacy analytics 端点", () => {
  it("扫描集确实包含全部 sku* store（防漏扫假保护）", () => {
    const names = sources().map((s) => s.name);
    for (const f of HISTORY_STORES) expect(names).toContain(`stores/${f}`);
  });
  for (const needle of FORBIDDEN) {
    it(`无文件含 "${needle}"`, () => {
      for (const { text } of sources()) expect(text.includes(needle)).toBe(false);
    });
  }
});
```

- [ ] **Step 2: 跑测试**

Run: `cd frontend && npx vitest run src/pages/history/no-analytics.test.ts`
Expected: 全 PASS（四个 store URL 均不含 `/analytics/sku`：`/api/history/<bc>` `/analytics` `/analytics/extras` `/timeline`）。
> coder：若意外有文件含 `/analytics/sku` → STOP 报告（说明哪个新栈文件回引了旧端点）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/history/no-analytics.test.ts
git commit -m "test(history): no-analytics 守卫扫全部 sku* store + 收紧 /analytics/sku（HC-P3-5）"
```

---

## Task 9: 全量验证

**Files:** 无

- [ ] **Step 1: 后端全量**: `pytest tests/ -q` → 全绿。
- [ ] **Step 2: TS 漂移**: `python tools/gen_ts_types.py --check` → 退出 0。
- [ ] **Step 3: 前端**: `cd frontend && npm run test:unit && npm run typecheck && npm run build` → 全绿 + 0 + 构建成功。
- [ ] **Step 4: ruff**: `ruff check app/ tests/` → clean。
- [ ] **Step 5: 本地浏览器验收（用户）**: `./dev.ps1 -Frontend` → `/ui/history` 查有数据货号，确认「概况」后出走势图（月柱 + 进价阶梯折线 + dot），负净月有退货三角 tooltip，CN 货 dot tooltip 含 ¥/€，无数据货号显「无数据」，图失败不影响其余块，A→B 快切不串。

---

## Self-Review 记录

**Spec 覆盖：** HC-P3-1（additive 不碰旧页/端点/深链 = 全程不动旧物）/ P3-2（瘦端点 key 集合 = Task 1,2）/ P3-3（独立 store 失败隔离 = Task 5,7 + 原子失败 Task 3）/ P3-4（HC-B7 守卫 = Task 5 + runSearch 门控 Task 7）/ P3-5（守卫扩扫 = Task 8）/ P3-6（hasData = Task 6）/ P3-7（负净 max(0)+退货三角 = Task 6）/ P3-8（step/同价/title/CN = Task 6）/ P3-9（日期域+周中点+anchor = Task 6）。全部有 task 落点。

**类型一致：** `SkuTimelineResponse`/`TimelineWeek`/`MonthlySale`（后端）↔ `TimelineVM`/`TimelineWeekVM`/`MonthlySaleVM`（前端）↔ `normalizeTimeline`/`useSkuTimelineStore`/`TimelineChart` props 贯穿一致。store URL `/api/history/<bc>/timeline` 与端点路由一致。

**无占位符：** schema/normalize/store/组件/守卫代码完整；HistoryPage 接线给出 import+触发+模板片段（对照 2a/2b 既有接线落地）。组件测试断言用稳定选择器（class / data-kind / data-month）。
