# 晨间简报 Vue 呈现层迁移 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已批准的晨间简报（5 卡片 + 3 行动清单）从裸 JSON 骨架正确落到新 Vue 栈 `/ui/briefing`，并修好 3 个深链使其经 `/?page=` 激活旧 Alpine SPA 对应 tab。

**Architecture:** 后端零改动，只消费既有 `/api/briefing/data`。前端在 API 边界用唯一 `normalizeBriefing()` 把弱类型 payload 收窄成 `BriefingViewModel`（异常 block → `Unavailable`，绝不整页 throw）；组件只吃 VM。深链解析抽成 classic 纯函数 `static/js/nav-resolve.js`（禁 ESM），旧 SPA `store.js` 调它。

**Tech Stack:** Vue 3 `<script setup>` + Pinia + vue-router；vitest（unit=jsdom）+ @vue/test-utils；classic vanilla JS（旧 SPA）。

**Spec:** `docs/superpowers/specs/2026-06-15-briefing-vue-presentation-design.md`（数据口径源 = `2026-06-09-morning-briefing-design.md`）

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `static/js/nav-resolve.js` | classic 纯函数 `resolveInitialPage`，深链 tab 解析 | 新建 |
| `static/js/store.js` | `initFromStorage()` 改调 `resolveInitialPage` | 改（1 处） |
| `templates/index.html` | 在 store.js 前 `<script defer>` 加载 nav-resolve.js | 改（1 行） |
| `frontend/src/legacy/nav-resolve.test.ts` | fs 读文件 + eval 测 `resolveInitialPage` | 新建 |
| `frontend/src/pages/briefing/types.ts` | view-model 类型 | 新建 |
| `frontend/src/pages/briefing/normalize.ts` | `normalizeBriefing(raw): BriefingViewModel` | 新建 |
| `frontend/src/pages/briefing/normalize.test.ts` | normalize 单测（含降级/malformed） | 新建 |
| `frontend/src/stores/briefing.ts` | 存 VM 而非 raw | 改 |
| `frontend/src/stores/briefing.test.ts` | 适配 VM | 改 |
| `frontend/src/pages/briefing/StatCard.vue` | 状态小卡 | 新建 |
| `frontend/src/pages/briefing/StatCard.test.ts` | StatCard 渲染测 | 新建 |
| `frontend/src/pages/briefing/SalesHealthHero.vue` | 销售健康 hero | 新建 |
| `frontend/src/pages/briefing/SalesHealthHero.test.ts` | Hero 各 status 测 | 新建 |
| `frontend/src/pages/briefing/ActionList.vue` | 通用行动清单表格 | 新建 |
| `frontend/src/pages/briefing/ActionList.test.ts` | ActionList 测 | 新建 |
| `frontend/src/pages/briefing/BriefingPage.vue` | 编排页（重写） | 改 |
| `frontend/src/pages/briefing/BriefingPage.test.ts` | 页面态测 | 新建 |

---

## Task 1: legacy 深链解析纯函数 `resolveInitialPage`

**Files:**
- Create: `static/js/nav-resolve.js`
- Test: `frontend/src/legacy/nav-resolve.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/legacy/nav-resolve.test.ts`：
```ts
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// nav-resolve.js 是 classic 脚本（无 export，禁 ESM），不能 import；
// 读文件 + new Function eval 取出全局函数（spec §8）。
const here = dirname(fileURLToPath(import.meta.url)); // .../frontend/src/legacy
const file = resolve(here, "../../../static/js/nav-resolve.js"); // → 仓库根 static/js
const code = readFileSync(file, "utf8");
const resolveInitialPage = new Function(
  code + "; return resolveInitialPage;",
)() as (p: string, s: string, ids: string[]) => string | null;

const IDS = ["dashboard", "restock", "purchase", "data_quality"];

describe("resolveInitialPage", () => {
  it("?page= 命中 → 返回该 id", () => {
    expect(resolveInitialPage("/", "?page=restock", IDS)).toBe("restock");
    expect(resolveInitialPage("/", "?page=purchase", IDS)).toBe("purchase");
    expect(resolveInitialPage("/", "?page=data_quality", IDS)).toBe("data_quality");
  });
  it("query 命中优先于 pathname", () => {
    expect(resolveInitialPage("/data_quality", "?page=restock", IDS)).toBe("restock");
  });
  it("query 未命中 → 回退 pathname 首段", () => {
    expect(resolveInitialPage("/data_quality", "", IDS)).toBe("data_quality");
    expect(resolveInitialPage("/data_quality", "?page=nope", IDS)).toBe("data_quality");
  });
  it("都不命中 → null", () => {
    expect(resolveInitialPage("/", "", IDS)).toBeNull();
    expect(resolveInitialPage("/unknown", "?page=bad", IDS)).toBeNull();
  });
  it("非法 page 值 → null（不回退到它）", () => {
    expect(resolveInitialPage("/", "?page=<script>", IDS)).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/legacy/nav-resolve.test.ts`
Expected: FAIL（`ENOENT` 读不到文件 / `resolveInitialPage is not defined`）

- [ ] **Step 3: 写最小实现**

`static/js/nav-resolve.js`：
```js
// 旧 SPA tab 深链解析。classic script —— 禁 ESM export/import（index.html 以
// <script defer> 加载，加 export 会让旧 SPA 首页语法错）。顶层函数声明即全局。
// 优先级：query ?page= 命中 pageIds > pathname 首段命中 > null（spec §7 硬验收 #4）。
function resolveInitialPage(pathname, search, pageIds) {
  try {
    var ids = Array.isArray(pageIds) ? pageIds : [];
    var qp = new URLSearchParams(search || "").get("page");
    if (qp && ids.indexOf(qp) !== -1) return qp;
    var seg = String(pathname || "").split("/").filter(Boolean)[0];
    if (seg && ids.indexOf(seg) !== -1) return seg;
  } catch (_) {
    /* ignore */
  }
  return null;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/legacy/nav-resolve.test.ts`
Expected: PASS（5 tests）

- [ ] **Step 5: 提交**

```bash
git add static/js/nav-resolve.js frontend/src/legacy/nav-resolve.test.ts
git commit -m "feat(briefing): legacy 深链解析纯函数 resolveInitialPage(classic,禁ESM)"
```

---

## Task 2: 接线 nav-resolve 到旧 SPA（store.js + index.html）

**Files:**
- Modify: `static/js/store.js`（`initFromStorage`，约 219-226 行）
- Modify: `templates/index.html:13`（在 store.js 前加 script）

> 本任务是 classic 接线，无新增单测（解析逻辑已由 Task 1 覆盖）；Step 4 做手动冒烟。

- [ ] **Step 1: index.html 在 store.js 前加载 nav-resolve.js**

`templates/index.html`，在第 13 行 `<script defer src="...store.js">` **之前**插入一行（defer 按序执行，确保 store.js 运行时全局函数已就绪）：
```html
<script defer src="{{ url_for('static', filename='js/nav-resolve.js') }}"></script>
```

- [ ] **Step 2: store.js initFromStorage 改调 resolveInitialPage**

`static/js/store.js`，把现有 pathname 首段解析块：
```js
      // 直达带页面前缀的 URL → 激活对应 tab, 否则停在默认 current。
      // pathname 首段匹配某个 page.id 才切, 防误判。(/briefing 已迁 /ui, 不再命中此表)
      try {
        const seg = window.location.pathname.split("/").filter(Boolean)[0];
        if (seg && this.pages.some((p) => p.id === seg)) {
          this.current = seg;
        }
      } catch (_) {
        /* ignore */
      }
```
替换为：
```js
      // 深链 tab 解析（query ?page= 优先 > pathname 首段）抽到 nav-resolve.js 纯函数,
      // /ui 简报页深链 /?page=restock 等经此激活对应 tab。(/briefing 已迁 /ui)
      try {
        const seg = resolveInitialPage(
          window.location.pathname,
          window.location.search,
          this.pages.map((p) => p.id),
        );
        if (seg) this.current = seg;
      } catch (_) {
        /* ignore */
      }
```

- [ ] **Step 3: 启本地服务器**

Run: `python server.py`（另起终端，或 `./dev.ps1`）

- [ ] **Step 4: 手动冒烟三页深链**

浏览器依次访问（登录后）：
- `http://127.0.0.1:5000/?page=restock` → 旧 SPA 停在「补货决策」tab
- `http://127.0.0.1:5000/?page=purchase` → 停在「采购导入」tab
- `http://127.0.0.1:5000/?page=data_quality` → 停在「数据质量」tab
- `http://127.0.0.1:5000/`（无参数）→ 停在默认 tab（dashboard），不报 JS 语法错（控制台干净）

Expected: 三个 `?page=` 各激活对应 tab；无参数页正常；控制台无 `Unexpected token 'export'` 类错误。

- [ ] **Step 5: 提交**

```bash
git add static/js/store.js templates/index.html
git commit -m "feat(briefing): 旧 SPA 接 resolveInitialPage —— /?page= 深链激活 tab"
```

---

## Task 3: view-model 类型 + normalizeBriefing（API 唯一收窄边界）

**Files:**
- Create: `frontend/src/pages/briefing/types.ts`
- Create: `frontend/src/pages/briefing/normalize.ts`
- Test: `frontend/src/pages/briefing/normalize.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/pages/briefing/normalize.test.ts`：
```ts
import { describe, expect, it } from "vitest";
import type { BriefingData } from "../../api/types.gen";
import { normalizeBriefing } from "./normalize";

function raw(over: Partial<BriefingData> = {}): BriefingData {
  return {
    ok: true,
    generated_at: "2026-06-12T09:00:00",
    data_week: "2026-06-08",
    data_week_complete: true,
    cards: {
      sales_health: { ok: true, status: "ok", delta_pct: 12, current_qty: 4715, previous_qty: 4210, forecast_next_p50: 380, model_bias_units: 6, covered_skus: 42 },
      restock_risk: { ok: true, total: 38, urgent: 12 },
      stockout_impact: { ok: true, total: 12, samples: [{ barcode: "5828079342495", model: "34249", zero_weeks: 3, qty_total: 0 }] },
      overstock_risk: { ok: true, total: 396, stock_qty: 124991, cost_available: true, costed_skus: 392, overstock_value_eur: 83382.82, samples: [{ barcode: "5828079342495", model: "34249", qty_total: 4884, cost_value_eur: 2176.8 }] },
      data_health: { ok: true, last_import_date: "2026-06-15", days_since: 0, stale: false, scrape_stale: false, cost_coverage_pct: 59 },
    },
    actions: {
      restock: { ok: true, total: 38, items: [{ barcode: "5828079342495", model: "34249", qty_total: 4884, weekly_velocity: 50, restock_qty_p50: 120, weeks_of_cover: 2.1 }] },
      follow_up: { ok: true, status: "ok", total: 2, items: [{ id: 7, supplier_name: "供应商A", supplier_id: "A", order_date: "2026-06-01", total_qty: 500, overdue_days: 5, overdue_state: "overdue" }] },
      review_anomalies: { ok: true, total: 3, items: [{ kind: "条码超长", count: 7, samples: ["5828"] }] },
    },
    ...over,
  } as BriefingData;
}

describe("normalizeBriefing", () => {
  it("正常 payload → 各 block available", () => {
    const vm = normalizeBriefing(raw());
    expect(vm.dataWeek).toBe("2026-06-08");
    expect(vm.salesHealth).toMatchObject({ available: true, status: "ok", deltaPct: 12 });
    expect(vm.restockRisk).toMatchObject({ available: true, total: 38, urgent: 12 });
    expect(vm.overstockRisk).toMatchObject({ available: true, costAvailable: true, overstockValueEur: 83382.82 });
    expect(vm.restockAction).toMatchObject({ available: true, total: 38 });
    if (vm.restockAction.available) expect(vm.restockAction.items[0].weeksOfCover).toBe(2.1);
  });

  it("block ok:false → 该 block Unavailable，其余正常（不 throw）", () => {
    const r = raw();
    r.cards.restock_risk = { ok: false, error: "boom" };
    const vm = normalizeBriefing(r);
    expect(vm.restockRisk.available).toBe(false);
    expect(vm.salesHealth.available).toBe(true);
  });

  it("malformed / 缺字段 block → Unavailable（不 throw）", () => {
    const r = raw();
    // @ts-expect-error 故意塞坏数据
    r.cards.sales_health = "not-an-object";
    // @ts-expect-error 故意缺 status
    r.cards.data_health = { ok: true };
    const vm = normalizeBriefing(r);
    expect(vm.salesHealth.available).toBe(false);
    // data_health 无 status 要求，缺字段降级为 null 而非 unavailable
    expect(vm.dataHealth.available).toBe(true);
    if (vm.dataHealth.available) expect(vm.dataHealth.daysSince).toBeNull();
  });

  it("sales_health 非法 status → Unavailable", () => {
    const r = raw();
    // @ts-expect-error
    r.cards.sales_health = { ok: true, status: "weird" };
    expect(normalizeBriefing(r).salesHealth.available).toBe(false);
  });

  it("压货 cost_available:false → overstockValueEur 为 null", () => {
    const r = raw();
    r.cards.overstock_risk = { ok: true, total: 396, stock_qty: 124991, cost_available: false, costed_skus: 0, overstock_value_eur: null, samples: [] };
    const vm = normalizeBriefing(r);
    if (vm.overstockRisk.available) {
      expect(vm.overstockRisk.costAvailable).toBe(false);
      expect(vm.overstockRisk.overstockValueEur).toBeNull();
    }
  });

  it("空库 data_week:null → dataWeek null，不 throw", () => {
    const vm = normalizeBriefing(raw({ data_week: null, data_week_complete: false }));
    expect(vm.dataWeek).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/briefing/normalize.test.ts`
Expected: FAIL（`Cannot find module './normalize'`）

- [ ] **Step 3: 写类型**

`frontend/src/pages/briefing/types.ts`：
```ts
export interface Unavailable {
  available: false;
}

export type SalesStatus = "ok" | "week_incomplete" | "coverage_insufficient" | "no_previous_week";

export interface SalesHealthVM {
  available: true;
  status: SalesStatus;
  deltaPct: number | null;
  currentQty: number | null;
  previousQty: number | null;
  forecastNextP50: number | null;
  modelBiasUnits: number | null;
  coveredSkus: number;
}
export interface RestockRiskVM {
  available: true;
  total: number;
  urgent: number;
}
export interface StockoutSample {
  barcode: string;
  model: string | null;
  zeroWeeks: number | null;
  qtyTotal: number | null;
}
export interface StockoutImpactVM {
  available: true;
  total: number;
  samples: StockoutSample[];
}
export interface OverstockSample {
  barcode: string;
  model: string | null;
  qtyTotal: number | null;
  costValueEur: number | null;
}
export interface OverstockVM {
  available: true;
  total: number;
  stockQty: number;
  costAvailable: boolean;
  costedSkus: number;
  overstockValueEur: number | null;
  samples: OverstockSample[];
}
export interface DataHealthVM {
  available: true;
  lastImportDate: string | null;
  daysSince: number | null;
  stale: boolean;
  scrapeStale: boolean;
  costCoveragePct: number | null;
}
export interface RestockActionRow {
  barcode: string;
  model: string | null;
  qtyTotal: number | null;
  weeklyVelocity: number | null;
  restockQtyP50: number | null;
  weeksOfCover: number | null;
}
export interface RestockActionVM {
  available: true;
  items: RestockActionRow[];
  total: number;
}
export interface FollowUpRow {
  id: number;
  supplierName: string | null;
  orderDate: string | null;
  totalQty: number | null;
  overdueDays: number | null;
  overdueState: "overdue" | "not_due" | "unknown";
}
export interface FollowUpActionVM {
  available: true;
  items: FollowUpRow[];
  total: number;
}
export interface ReviewRow {
  kind: string;
  count: number;
}
export interface ReviewActionVM {
  available: true;
  items: ReviewRow[];
  total: number;
}

export interface BriefingViewModel {
  dataWeek: string | null;
  dataWeekComplete: boolean;
  salesHealth: SalesHealthVM | Unavailable;
  restockRisk: RestockRiskVM | Unavailable;
  stockoutImpact: StockoutImpactVM | Unavailable;
  overstockRisk: OverstockVM | Unavailable;
  dataHealth: DataHealthVM | Unavailable;
  restockAction: RestockActionVM | Unavailable;
  followUpAction: FollowUpActionVM | Unavailable;
  reviewAction: ReviewActionVM | Unavailable;
}
```

- [ ] **Step 4: 写 normalize 实现**

`frontend/src/pages/briefing/normalize.ts`：
```ts
import type { BriefingData } from "../../api/types.gen";
import type {
  BriefingViewModel,
  DataHealthVM,
  FollowUpActionVM,
  FollowUpRow,
  OverstockVM,
  RestockActionVM,
  RestockActionRow,
  RestockRiskVM,
  ReviewActionVM,
  ReviewRow,
  SalesHealthVM,
  SalesStatus,
  StockoutImpactVM,
  StockoutSample,
  Unavailable,
} from "./types";

type Rec = Record<string, unknown>;
const NA: Unavailable = { available: false };

function rec(x: unknown): Rec | null {
  return x !== null && typeof x === "object" && !Array.isArray(x) ? (x as Rec) : null;
}
function okRec(x: unknown): Rec | null {
  const r = rec(x);
  return r && r.ok === true ? r : null;
}
function num(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}
function str(x: unknown): string | null {
  return typeof x === "string" ? x : null;
}
function arr(x: unknown): unknown[] {
  return Array.isArray(x) ? x : [];
}
function safe<T>(fn: () => T | Unavailable): T | Unavailable {
  try {
    return fn();
  } catch {
    return NA; // 硬验收 #2：任何 block 异常都不冒泡到整页
  }
}

const SALES_STATUS: SalesStatus[] = ["ok", "week_incomplete", "coverage_insufficient", "no_previous_week"];

function normSalesHealth(x: unknown): SalesHealthVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const status = r.status;
  if (typeof status !== "string" || !SALES_STATUS.includes(status as SalesStatus)) return NA;
  return {
    available: true,
    status: status as SalesStatus,
    deltaPct: num(r.delta_pct),
    currentQty: num(r.current_qty),
    previousQty: num(r.previous_qty),
    forecastNextP50: num(r.forecast_next_p50),
    modelBiasUnits: num(r.model_bias_units),
    coveredSkus: num(r.covered_skus) ?? 0,
  };
}

function normRestockRisk(x: unknown): RestockRiskVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  return { available: true, total: num(r.total) ?? 0, urgent: num(r.urgent) ?? 0 };
}

function normStockout(x: unknown): StockoutImpactVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const samples: StockoutSample[] = arr(r.samples).map((s) => {
    const sr = rec(s) ?? {};
    return {
      barcode: str(sr.barcode) ?? "",
      model: str(sr.model),
      zeroWeeks: num(sr.zero_weeks),
      qtyTotal: num(sr.qty_total),
    };
  });
  return { available: true, total: num(r.total) ?? 0, samples };
}

function normOverstock(x: unknown): OverstockVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const samples = arr(r.samples).map((s) => {
    const sr = rec(s) ?? {};
    return {
      barcode: str(sr.barcode) ?? "",
      model: str(sr.model),
      qtyTotal: num(sr.qty_total),
      costValueEur: num(sr.cost_value_eur),
    };
  });
  return {
    available: true,
    total: num(r.total) ?? 0,
    stockQty: num(r.stock_qty) ?? 0,
    costAvailable: r.cost_available === true,
    costedSkus: num(r.costed_skus) ?? 0,
    overstockValueEur: num(r.overstock_value_eur),
    samples,
  };
}

function normDataHealth(x: unknown): DataHealthVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  return {
    available: true,
    lastImportDate: str(r.last_import_date),
    daysSince: num(r.days_since),
    stale: r.stale === true,
    scrapeStale: r.scrape_stale === true,
    costCoveragePct: num(r.cost_coverage_pct),
  };
}

function normRestockAction(x: unknown): RestockActionVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const items: RestockActionRow[] = arr(r.items).map((i) => {
    const ir = rec(i) ?? {};
    return {
      barcode: str(ir.barcode) ?? "",
      model: str(ir.model),
      qtyTotal: num(ir.qty_total),
      weeklyVelocity: num(ir.weekly_velocity),
      restockQtyP50: num(ir.restock_qty_p50),
      weeksOfCover: num(ir.weeks_of_cover),
    };
  });
  return { available: true, items, total: num(r.total) ?? items.length };
}

function normFollowUp(x: unknown): FollowUpActionVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const states = ["overdue", "not_due", "unknown"];
  const items: FollowUpRow[] = arr(r.items).map((i) => {
    const ir = rec(i) ?? {};
    const st = str(ir.overdue_state);
    return {
      id: num(ir.id) ?? 0,
      supplierName: str(ir.supplier_name),
      orderDate: str(ir.order_date),
      totalQty: num(ir.total_qty),
      overdueDays: num(ir.overdue_days),
      overdueState: (st && states.includes(st) ? st : "unknown") as FollowUpRow["overdueState"],
    };
  });
  return { available: true, items, total: num(r.total) ?? items.length };
}

function normReview(x: unknown): ReviewActionVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const items: ReviewRow[] = arr(r.items).map((i) => {
    const ir = rec(i) ?? {};
    return { kind: str(ir.kind) ?? "", count: num(ir.count) ?? 0 };
  });
  return { available: true, items, total: num(r.total) ?? items.length };
}

/** API 边界唯一收窄点（spec 硬验收 #1）。组件只吃返回的 BriefingViewModel，不碰 raw。 */
export function normalizeBriefing(raw: BriefingData): BriefingViewModel {
  const cards = rec(raw.cards) ?? {};
  const actions = rec(raw.actions) ?? {};
  return {
    dataWeek: str(raw.data_week),
    dataWeekComplete: raw.data_week_complete === true,
    salesHealth: safe(() => normSalesHealth(cards.sales_health)),
    restockRisk: safe(() => normRestockRisk(cards.restock_risk)),
    stockoutImpact: safe(() => normStockout(cards.stockout_impact)),
    overstockRisk: safe(() => normOverstock(cards.overstock_risk)),
    dataHealth: safe(() => normDataHealth(cards.data_health)),
    restockAction: safe(() => normRestockAction(actions.restock)),
    followUpAction: safe(() => normFollowUp(actions.follow_up)),
    reviewAction: safe(() => normReview(actions.review_anomalies)),
  };
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/briefing/normalize.test.ts`
Expected: PASS（6 tests）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/briefing/types.ts frontend/src/pages/briefing/normalize.ts frontend/src/pages/briefing/normalize.test.ts
git commit -m "feat(briefing): BriefingViewModel 类型 + normalizeBriefing 收窄边界"
```

---

## Task 4: store 改存 VM

**Files:**
- Modify: `frontend/src/stores/briefing.ts`
- Modify: `frontend/src/stores/briefing.test.ts`

- [ ] **Step 1: 改测试（先改成期望 VM）**

把 `frontend/src/stores/briefing.test.ts` 中三处对 `s.data` 的断言改为 `s.vm`，并校验已 normalize：
- 第 35 行 `expect(s.data?.data_week).toBe("2026-06-08");` → `expect(s.vm?.dataWeek).toBe("2026-06-08");`
- 第 45 行 `expect(s.data).toBeNull();` → `expect(s.vm).toBeNull();`
- 在第一个 it 末尾追加：`expect(s.vm?.salesHealth.available).toBe(true);`

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/briefing.test.ts`
Expected: FAIL（`s.vm` 未定义 / 仍是 `data`）

- [ ] **Step 3: 改 store 实现**

`frontend/src/stores/briefing.ts` 全文替换为：
```ts
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { BriefingData } from "../api/types.gen";
import { normalizeBriefing } from "../pages/briefing/normalize";
import type { BriefingViewModel } from "../pages/briefing/types";

export const useBriefingStore = defineStore("briefing", () => {
  const vm = ref<BriefingViewModel | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      const raw = await apiGet<BriefingData>("/api/briefing/data");
      vm.value = normalizeBriefing(raw);
    } catch (e) {
      // 未登录由 apiGet 的跳转接管 UX，不渲染一闪而过的误导性错误文案
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  return { vm, loading, error, load };
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/stores/briefing.test.ts`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores/briefing.ts frontend/src/stores/briefing.test.ts
git commit -m "feat(briefing): store 存 normalize 后的 BriefingViewModel"
```

---

## Task 5: StatCard 组件

**Files:**
- Create: `frontend/src/pages/briefing/StatCard.vue`
- Test: `frontend/src/pages/briefing/StatCard.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/pages/briefing/StatCard.test.ts`：
```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import StatCard from "./StatCard.vue";

describe("StatCard", () => {
  it("available → 渲染 label/value/hint", () => {
    const w = mount(StatCard, { props: { label: "补货风险", value: "38 项", hint: "其中 12 个紧急", available: true } });
    expect(w.text()).toContain("补货风险");
    expect(w.text()).toContain("38 项");
    expect(w.text()).toContain("其中 12 个紧急");
  });
  it("unavailable → 显「暂不可用」，不渲染 value", () => {
    const w = mount(StatCard, { props: { label: "压货风险", value: "€83k", available: false } });
    expect(w.text()).toContain("暂不可用");
    expect(w.text()).not.toContain("€83k");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/briefing/StatCard.test.ts`
Expected: FAIL（找不到 StatCard.vue）

- [ ] **Step 3: 写组件**

`frontend/src/pages/briefing/StatCard.vue`：
```vue
<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    value?: string;
    hint?: string;
    available?: boolean;
  }>(),
  { available: true, value: "", hint: "" },
);
</script>

<template>
  <div class="stat">
    <div class="stat__label">{{ label }}</div>
    <template v-if="available">
      <div class="stat__value">{{ value }}</div>
      <div v-if="hint" class="stat__hint">{{ hint }}</div>
    </template>
    <div v-else class="stat__na">暂不可用</div>
  </div>
</template>

<style scoped>
.stat {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: var(--sp-4);
}
.stat__label {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-2);
  margin-bottom: var(--sp-2);
}
.stat__value {
  font-family: var(--mono);
  font-size: var(--fs-2xl);
  color: var(--ink-0);
  line-height: 1.1;
}
.stat__hint {
  font-size: var(--fs-sm);
  color: var(--ink-1);
  margin-top: var(--sp-2);
}
.stat__na {
  font-size: var(--fs-sm);
  color: var(--ink-2);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/briefing/StatCard.test.ts`
Expected: PASS（2 tests）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/briefing/StatCard.vue frontend/src/pages/briefing/StatCard.test.ts
git commit -m "feat(briefing): StatCard 状态小卡组件"
```

---

## Task 6: SalesHealthHero 组件

**Files:**
- Create: `frontend/src/pages/briefing/SalesHealthHero.vue`
- Test: `frontend/src/pages/briefing/SalesHealthHero.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/pages/briefing/SalesHealthHero.test.ts`：
```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SalesHealthHero from "./SalesHealthHero.vue";
import type { SalesHealthVM } from "./types";

const ok: SalesHealthVM = {
  available: true, status: "ok", deltaPct: 12, currentQty: 4715, previousQty: 4210,
  forecastNextP50: 380, modelBiasUnits: 6, coveredSkus: 42,
};

describe("SalesHealthHero", () => {
  it("status ok → 显 delta% + 副信息", () => {
    const w = mount(SalesHealthHero, { props: { vm: ok } });
    expect(w.text()).toContain("+12%");
    expect(w.text()).toContain("380");
  });
  it("status coverage_insufficient → 不显 delta%，显覆盖不足文案", () => {
    const w = mount(SalesHealthHero, { props: { vm: { ...ok, status: "coverage_insufficient", deltaPct: null } } });
    expect(w.text()).not.toContain("%");
    expect(w.text()).toContain("覆盖不足");
  });
  it("unavailable → 暂不可用", () => {
    const w = mount(SalesHealthHero, { props: { vm: { available: false } } });
    expect(w.text()).toContain("暂不可用");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/briefing/SalesHealthHero.test.ts`
Expected: FAIL（找不到组件）

- [ ] **Step 3: 写组件**

`frontend/src/pages/briefing/SalesHealthHero.vue`：
```vue
<script setup lang="ts">
import { computed } from "vue";
import type { SalesHealthVM, Unavailable } from "./types";

const props = defineProps<{ vm: SalesHealthVM | Unavailable }>();

const DEGRADED: Record<string, string> = {
  week_incomplete: "数据周未完整，本批次暂不给环比结论。",
  coverage_insufficient: "销售口径覆盖不足，本批次暂不给环比结论。",
  no_previous_week: "上一完整周无数据，仅显示本批次销量。",
};

const isOk = computed(() => props.vm.available && props.vm.status === "ok");
const degradedMsg = computed(() =>
  props.vm.available && props.vm.status !== "ok" ? DEGRADED[props.vm.status] : "",
);
const deltaText = computed(() => {
  if (!props.vm.available || props.vm.deltaPct === null) return "";
  const v = props.vm.deltaPct;
  return `${v > 0 ? "+" : ""}${v}%`;
});
const tone = computed(() => {
  if (!props.vm.available || props.vm.deltaPct === null) return "neutral";
  return props.vm.deltaPct >= 0 ? "up" : "down";
});
</script>

<template>
  <section class="hero" :class="`hero--${tone}`">
    <div class="hero__label">本批次销售健康</div>

    <template v-if="!vm.available">
      <div class="hero__na">暂不可用</div>
    </template>

    <template v-else-if="isOk">
      <div class="hero__delta">{{ deltaText }}</div>
      <div class="hero__sub">
        本批次清洗后销量较上批 {{ deltaText }}（{{ vm.previousQty }} → {{ vm.currentQty }} 件）<br />
        <template v-if="vm.forecastNextP50 !== null">下期系统预期约 {{ vm.forecastNextP50 }} 件</template>
        <template v-if="vm.modelBiasUnits !== null"> · 模型近期校准：回测整体偏移 {{ vm.modelBiasUnits }} 件/周</template>
      </div>
    </template>

    <template v-else>
      <div class="hero__degraded">{{ degradedMsg }}</div>
      <div v-if="vm.currentQty !== null" class="hero__sub">本批次销量 {{ vm.currentQty }} 件</div>
    </template>
  </section>
</template>

<style scoped>
.hero {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-left: 3px solid var(--ink-2);
  border-radius: var(--r-md);
  padding: var(--sp-5) var(--sp-6);
}
.hero--up { border-left-color: var(--success); }
.hero--down { border-left-color: var(--error); }
.hero__label {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-2);
}
.hero__delta {
  font-family: var(--mono);
  font-size: var(--fs-4xl);
  color: var(--ink-0);
  line-height: 1.1;
  margin: var(--sp-2) 0;
}
.hero--up .hero__delta { color: var(--success); }
.hero--down .hero__delta { color: var(--error); }
.hero__sub { font-size: var(--fs-base); color: var(--ink-1); }
.hero__degraded { font-size: var(--fs-lg); color: var(--ink-1); margin-top: var(--sp-2); }
.hero__na { font-size: var(--fs-base); color: var(--ink-2); margin-top: var(--sp-2); }
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/briefing/SalesHealthHero.test.ts`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/briefing/SalesHealthHero.vue frontend/src/pages/briefing/SalesHealthHero.test.ts
git commit -m "feat(briefing): SalesHealthHero —— 含 ok/降级/暂不可用三态"
```

---

## Task 7: ActionList 通用清单组件

**Files:**
- Create: `frontend/src/pages/briefing/ActionList.vue`
- Test: `frontend/src/pages/briefing/ActionList.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/pages/briefing/ActionList.test.ts`：
```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ActionList from "./ActionList.vue";

const columns = [
  { key: "model", label: "型号" },
  { key: "qty", label: "建议量" },
];
const rows = [
  { model: "34249", qty: 120 },
  { model: "25778", qty: 80 },
];

describe("ActionList", () => {
  it("渲染标题、行、查看全部链接（href）", () => {
    const w = mount(ActionList, { props: { title: "建议补货", total: 38, href: "/?page=restock", columns, rows } });
    expect(w.text()).toContain("建议补货");
    expect(w.text()).toContain("34249");
    const a = w.get("a.action__more");
    expect(a.attributes("href")).toBe("/?page=restock");
    expect(a.attributes("href")).not.toContain(" ");
  });
  it("空 rows → 显空态文案", () => {
    const w = mount(ActionList, { props: { title: "建议催单", total: 0, href: "/?page=purchase", columns, rows: [], emptyText: "暂无采购订单" } });
    expect(w.text()).toContain("暂无采购订单");
  });
  it("unavailable → 暂不可用", () => {
    const w = mount(ActionList, { props: { title: "复查异常", total: 0, href: "/?page=data_quality", columns, rows: [], available: false } });
    expect(w.text()).toContain("暂不可用");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/briefing/ActionList.test.ts`
Expected: FAIL（找不到组件）

- [ ] **Step 3: 写组件**

`frontend/src/pages/briefing/ActionList.vue`：
```vue
<script setup lang="ts">
export interface Column {
  key: string;
  label: string;
}
type Cell = string | number | null;

withDefaults(
  defineProps<{
    title: string;
    total: number;
    href: string;
    columns: Column[];
    rows: Record<string, Cell>[];
    available?: boolean;
    emptyText?: string;
  }>(),
  { available: true, emptyText: "暂无数据" },
);
</script>

<template>
  <div class="action">
    <div class="action__head">
      <span class="action__title">{{ title }}<span v-if="available" class="action__count"> · {{ total }}</span></span>
      <a class="action__more" :href="href">查看全部 →</a>
    </div>

    <div v-if="!available" class="action__na">暂不可用</div>
    <div v-else-if="rows.length === 0" class="action__empty">{{ emptyText }}</div>
    <table v-else class="action__table">
      <thead>
        <tr>
          <th v-for="c in columns" :key="c.key">{{ c.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in rows" :key="i">
          <td v-for="c in columns" :key="c.key">{{ row[c.key] ?? "—" }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.action {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: var(--sp-4);
}
.action__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--sp-3);
}
.action__title { font-size: var(--fs-base); color: var(--ink-0); }
.action__count { color: var(--ink-2); }
.action__more { font-size: var(--fs-sm); color: var(--accent); text-decoration: none; }
.action__more:hover { text-decoration: underline; }
.action__na,
.action__empty { font-size: var(--fs-sm); color: var(--ink-2); padding: var(--sp-2) 0; }
.action__table { width: 100%; border-collapse: collapse; }
.action__table th {
  text-align: left;
  font-size: var(--fs-xs);
  text-transform: uppercase;
  color: var(--ink-2);
  font-weight: 500;
  padding: var(--sp-1) 0;
  border-bottom: 1px solid var(--line);
}
.action__table td {
  font-family: var(--mono);
  font-size: var(--fs-sm);
  color: var(--ink-1);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line-soft);
}
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/briefing/ActionList.test.ts`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/briefing/ActionList.vue frontend/src/pages/briefing/ActionList.test.ts
git commit -m "feat(briefing): ActionList 通用行动清单表格组件"
```

---

## Task 8: BriefingPage 重写（编排）

**Files:**
- Modify: `frontend/src/pages/briefing/BriefingPage.vue`
- Test: `frontend/src/pages/briefing/BriefingPage.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/pages/briefing/BriefingPage.test.ts`：
```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { BriefingViewModel } from "./types";

function vmStub(over: Partial<BriefingViewModel> = {}): BriefingViewModel {
  return {
    dataWeek: "2026-06-08",
    dataWeekComplete: true,
    salesHealth: { available: true, status: "ok", deltaPct: 12, currentQty: 4715, previousQty: 4210, forecastNextP50: 380, modelBiasUnits: 6, coveredSkus: 42 },
    restockRisk: { available: true, total: 38, urgent: 12 },
    stockoutImpact: { available: true, total: 12, samples: [] },
    overstockRisk: { available: true, total: 396, stockQty: 124991, costAvailable: true, costedSkus: 392, overstockValueEur: 83382.82, samples: [] },
    dataHealth: { available: true, lastImportDate: "2026-06-15", daysSince: 0, stale: false, scrapeStale: false, costCoveragePct: 59 },
    restockAction: { available: true, total: 38, items: [{ barcode: "5828", model: "34249", qtyTotal: 4884, weeklyVelocity: 50, restockQtyP50: 120, weeksOfCover: 2.1 }] },
    followUpAction: { available: true, total: 0, items: [] },
    reviewAction: { available: true, total: 0, items: [] },
    ...over,
  };
}

const state = { vm: null as BriefingViewModel | null, loading: false, error: null as string | null, load: vi.fn() };
vi.mock("../../stores/briefing", () => ({ useBriefingStore: () => state }));

import BriefingPage from "./BriefingPage.vue";

describe("BriefingPage", () => {
  it("正常 VM → 渲染 hero + 行动清单 + 状态卡，深链 /?page=", () => {
    state.vm = vmStub(); state.loading = false; state.error = null;
    const w = mount(BriefingPage);
    expect(w.text()).toContain("晨间简报");
    expect(w.text()).toContain("+12%");
    expect(w.text()).toContain("建议补货");
    const hrefs = w.findAll("a.action__more").map((a) => a.attributes("href"));
    expect(hrefs).toContain("/?page=restock");
    expect(hrefs).toContain("/?page=purchase");
    expect(hrefs).toContain("/?page=data_quality");
  });

  it("stale + days_since null → 红条显「刷新时间未知」", () => {
    state.vm = vmStub({ dataHealth: { available: true, lastImportDate: null, daysSince: null, stale: true, scrapeStale: false, costCoveragePct: null } });
    const w = mount(BriefingPage);
    expect(w.text()).toContain("刷新时间未知");
  });

  it("stale + days_since 数值 → 红条显「超过 N 天」", () => {
    state.vm = vmStub({ dataHealth: { available: true, lastImportDate: "2026-06-01", daysSince: 14, stale: true, scrapeStale: false, costCoveragePct: 59 } });
    const w = mount(BriefingPage);
    expect(w.text()).toContain("14");
    expect(w.text()).not.toContain("刷新时间未知");
  });

  it("空库 dataWeek null → 友好空态", () => {
    state.vm = vmStub({ dataWeek: null, dataWeekComplete: false });
    const w = mount(BriefingPage);
    expect(w.text()).toContain("暂无完整数据周");
  });

  it("系统级 error → 整页错误态", () => {
    state.vm = null; state.error = "API 500: /api/briefing/data";
    const w = mount(BriefingPage);
    expect(w.text()).toContain("API 500");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/briefing/BriefingPage.test.ts`
Expected: FAIL（旧 BriefingPage 用 `store.data`/`<pre>`，断言不中）

- [ ] **Step 3: 重写 BriefingPage**

`frontend/src/pages/briefing/BriefingPage.vue` 全文替换为：
```vue
<script setup lang="ts">
import { computed, onMounted } from "vue";
import PageHeader from "../../components/PageHeader.vue";
import { useBriefingStore } from "../../stores/briefing";
import ActionList from "./ActionList.vue";
import SalesHealthHero from "./SalesHealthHero.vue";
import StatCard from "./StatCard.vue";

const store = useBriefingStore();
onMounted(() => store.load());

const vm = computed(() => store.vm);

const subtitle = computed(() => {
  if (!vm.value) return undefined;
  const dh = vm.value.dataHealth;
  const imp = dh.available && dh.lastImportDate ? ` · 数据刷新于 ${dh.lastImportDate}` : "";
  return `数据周 ${vm.value.dataWeek ?? "—"}${imp}`;
});

const staleBanner = computed(() => {
  const v = vm.value;
  if (!v || !v.dataHealth.available) return null;
  const dh = v.dataHealth;
  if (!dh.stale && !dh.scrapeStale) return null;
  return dh.daysSince === null ? "数据刷新时间未知，请检查抓取任务" : `数据已超过 ${dh.daysSince} 天未刷新`;
});

const isEmpty = computed(() => !!vm.value && vm.value.dataWeek === null);

// 行动清单列定义
const restockCols = [
  { key: "model", label: "型号" },
  { key: "p50", label: "建议量" },
  { key: "cover", label: "可售周" },
];
const followCols = [
  { key: "supplier", label: "供应商" },
  { key: "qty", label: "数量" },
  { key: "overdue", label: "逾期" },
];
const reviewCols = [
  { key: "kind", label: "类型" },
  { key: "count", label: "数量" },
];

const restockRows = computed(() =>
  vm.value && vm.value.restockAction.available
    ? vm.value.restockAction.items.map((i) => ({ model: i.model, p50: i.restockQtyP50, cover: i.weeksOfCover }))
    : [],
);
const followRows = computed(() =>
  vm.value && vm.value.followUpAction.available
    ? vm.value.followUpAction.items.map((i) => ({
        supplier: i.supplierName,
        qty: i.totalQty,
        overdue: i.overdueState === "overdue" ? `逾期 ${i.overdueDays} 天` : i.overdueState === "not_due" ? "未到期" : "—",
      }))
    : [],
);
const reviewRows = computed(() =>
  vm.value && vm.value.reviewAction.available
    ? vm.value.reviewAction.items.map((i) => ({ kind: i.kind, count: i.count }))
    : [],
);

// 状态卡文案
function eur(n: number | null): string {
  return n === null ? "—" : `€${Math.round(n).toLocaleString()}`;
}
const restockStat = computed(() => {
  const c = vm.value?.restockRisk;
  return c?.available ? { value: `${c.total} 项`, hint: `其中 ${c.urgent} 个紧急（可售 ≤ 2 周）` } : null;
});
const stockoutStat = computed(() => {
  const c = vm.value?.stockoutImpact;
  return c?.available ? { value: `${c.total} 项`, hint: "近期零销疑因缺货" } : null;
});
const overstockStat = computed(() => {
  const c = vm.value?.overstockRisk;
  if (!c?.available) return null;
  return c.costAvailable
    ? { value: eur(c.overstockValueEur), hint: `${c.total} 个滞销 SKU · ${c.stockQty.toLocaleString()} 件` }
    : { value: `${c.stockQty.toLocaleString()} 件`, hint: `${c.total} 个滞销 SKU · 无成本数据` };
});
const dataStat = computed(() => {
  const c = vm.value?.dataHealth;
  if (!c?.available) return null;
  const since = c.daysSince === null ? "刷新时间未知" : `距今 ${c.daysSince} 天`;
  const cov = c.costCoveragePct === null ? "" : ` · 成本覆盖 ${c.costCoveragePct}%`;
  return { value: c.stale || c.scrapeStale ? "注意" : "正常", hint: `${since}${cov}` };
});
</script>

<template>
  <main class="briefing">
    <PageHeader title="晨间简报" :subtitle="subtitle" />

    <p v-if="store.loading" class="briefing__msg">加载中…</p>
    <p v-else-if="store.error" class="briefing__error">{{ store.error }}</p>
    <p v-else-if="isEmpty" class="briefing__msg">本批次暂无完整数据周</p>

    <template v-else-if="vm">
      <div v-if="staleBanner" class="briefing__stale">{{ staleBanner }}</div>

      <SalesHealthHero :vm="vm.salesHealth" />

      <div class="briefing__grouplabel">今天要动手的</div>
      <div class="briefing__actions">
        <ActionList title="建议补货" :total="vm.restockAction.available ? vm.restockAction.total : 0" href="/?page=restock"
          :columns="restockCols" :rows="restockRows" :available="vm.restockAction.available" empty-text="暂无补货建议" />
        <ActionList title="建议催 / 确认" :total="vm.followUpAction.available ? vm.followUpAction.total : 0" href="/?page=purchase"
          :columns="followCols" :rows="followRows" :available="vm.followUpAction.available" empty-text="暂无采购订单" />
        <ActionList title="建议复查异常" :total="vm.reviewAction.available ? vm.reviewAction.total : 0" href="/?page=data_quality"
          :columns="reviewCols" :rows="reviewRows" :available="vm.reviewAction.available" empty-text="暂无异常" />
      </div>

      <div class="briefing__grouplabel">状态</div>
      <div class="briefing__stats">
        <StatCard label="补货风险" :available="!!restockStat" :value="restockStat?.value" :hint="restockStat?.hint" />
        <StatCard label="缺货影响" :available="!!stockoutStat" :value="stockoutStat?.value" :hint="stockoutStat?.hint" />
        <StatCard label="压货风险" :available="!!overstockStat" :value="overstockStat?.value" :hint="overstockStat?.hint" />
        <StatCard label="数据健康" :available="!!dataStat" :value="dataStat?.value" :hint="dataStat?.hint" />
      </div>
    </template>
  </main>
</template>

<style scoped>
.briefing { padding: var(--sp-6); max-width: 1200px; margin: 0 auto; }
.briefing__msg { color: var(--ink-1); }
.briefing__error { color: var(--error); }
.briefing__stale {
  background: var(--error-subtle);
  border: 1px solid var(--error-subtle-border);
  color: var(--error);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-4);
  font-size: var(--fs-base);
}
.briefing__grouplabel {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  letter-spacing: 0.05em;
  margin: var(--sp-6) 0 var(--sp-3);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--line-soft);
}
.briefing__actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-4); }
.briefing__stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-4); }
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/briefing/BriefingPage.test.ts`
Expected: PASS（5 tests）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/briefing/BriefingPage.vue frontend/src/pages/briefing/BriefingPage.test.ts
git commit -m "feat(briefing): 重写 BriefingPage —— 布局 C + 全态渲染（删裸 JSON）"
```

---

## Task 9: 全量验收

**Files:** 无（验证）

- [ ] **Step 1: 前端全量测试**

Run: `cd frontend && npm run test`
Expected: 全绿（含 normalize / nav-resolve / 各组件 / store / 既有 components+client）。

- [ ] **Step 2: 类型检查 + 构建**

Run: `cd frontend && npm run build`
Expected: `vue-tsc --noEmit` 无错 + vite build 成功（无裸 `as` 穿透告警）。

- [ ] **Step 3: TS 类型不漂移（后端未改，预期无变化）**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0（`api/types.gen.ts` 不变）。

- [ ] **Step 4: 确认后端零改动**

Run: `git diff --stat main...HEAD -- app/`
Expected: 空输出（无 `app/` Python 文件改动）。

- [ ] **Step 5: 本地端到端冒烟**

Run: `python server.py`，浏览器开 `http://127.0.0.1:5000/ui/briefing`
Expected:
- 不再有裸 JSON `<pre>`；hero + 3 行动清单 + 4 状态卡按布局 C 渲染。
- 三个「查看全部 →」分别跳 `/?page=restock|purchase|data_quality` 并激活旧 SPA 对应 tab（接 Task 2 冒烟）。

- [ ] **Step 6: 合并前对齐生产后端跑一遍（可选但建议）**

Run: `./test.ps1`（本地 PG + xdist，对齐生产后端）
Expected: 后端测试不受影响（本次未改后端，应与 main 一致全绿）。

---

## 自审记录（spec 覆盖核对）

- §3 布局 C → Task 8（hero/分组/3 栏 actions/4 栏 stats，max-width 1200，无侧栏补偿）。
- §4 组件拆分 → Task 5/6/7/8（StatCard/Hero/ActionList/BriefingPage；复用 PageHeader）。
- §5 normalize 唯一边界 + 禁裸 as（硬验收 #1）→ Task 3（`normalizeBriefing` + 类型守卫，无 `as` 穿透 raw）。
- §5 硬验收 #2 局部 unavailable 不 throw → Task 3 `safe()` + normalize.test「malformed/ok:false」用例。
- §6 状态分支（loading/error/空库/per-block/hero 降级/压货成本缺失/stale）→ Task 6 + Task 8 + 各测试。
- §6 硬验收 #5 `days_since==null` 文案 → Task 8 `staleBanner` + BriefingPage.test 两用例。
- §7 深链 `/?page=`（硬验收 #3 不带空格）→ Task 8 ActionList href + Task 1/Task 7 href 断言。
- §7 硬验收 #4 优先级 + legacy classic 禁 ESM → Task 1（纯函数 + 5 用例）+ Task 2（store.js/index.html 接线）。
- §8 测试（normalize/resolveInitialPage/组件）→ Task 1/3/5/6/7/8。
- §9 验收（构建/gen_ts_types/后端零改动）→ Task 9。
