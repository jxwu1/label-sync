import { mount, flushPromises } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { reactive, nextTick } from "vue";
import type { HistoryResult } from "./types";
import type { ExtrasPageVM } from "./extras-types";

const state = reactive({
  result: null as HistoryResult | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
  reset: vi.fn(),
});
vi.mock("../../stores/history", () => ({ useHistoryStore: () => state }));

const analyticsState = {
  vm: null as import("./analytics-types").AnalyticsVM | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
  reset: vi.fn(),
};
vi.mock("../../stores/skuAnalytics", () => ({ useSkuAnalyticsStore: () => analyticsState }));

const extrasState = {
  vm: null as ExtrasPageVM | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
  reset: vi.fn(),
};
vi.mock("../../stores/skuExtras", () => ({ useSkuExtrasStore: () => extrasState }));

const timelineState = {
  vm: null as { weeks: unknown[]; monthlySales: unknown[] } | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
  reset: vi.fn(),
};
vi.mock("../../stores/skuTimeline", () => ({ useSkuTimelineStore: () => timelineState }));

// Stub TimelineChart so we don't re-test its internals
vi.mock("./TimelineChart.vue", () => ({
  default: { name: "TimelineChart", template: '<div class="stub-timeline-chart" />', props: ["weeks", "monthlySales"] },
}));

// Stub RecentChangesPanel so batch-tab tests don't depend on panel internals / its store.
// Emits drill on a button click so we can exercise HistoryPage.onDrill.
vi.mock("./RecentChangesPanel.vue", () => ({
  default: {
    name: "RecentChangesPanel",
    template: '<div class="stub-recent-changes"><button class="stub-drill" @click="$emit(\'drill\', \'DRILLBC\')">drill</button></div>',
    emits: ["drill"],
  },
}));

// Stub ScanBatchPanel so sub-tab tests don't depend on its store/network.
vi.mock("./ScanBatchPanel.vue", () => ({
  default: {
    name: "ScanBatchPanel",
    template: '<div class="stub-scan-batch" />',
  },
}));

// Stub scanBatches store so ScanBatchPanel stub (and any leakage) doesn't hit real store.
vi.mock("../../stores/scanBatches", () => ({
  useScanBatchesStore: () => ({
    batches: [],
    loading: false,
    error: null,
    ensureLoaded: vi.fn(),
  }),
}));

import HistoryPage from "./HistoryPage.vue";
import RecentChangesPanel from "./RecentChangesPanel.vue";
import ScanBatchPanel from "./ScanBatchPanel.vue";

function reset() {
  state.result = null; state.loading = false; state.error = null;
  state.load = vi.fn(); state.reset = vi.fn();
  analyticsState.vm = null; analyticsState.loading = false; analyticsState.error = null;
  analyticsState.load = vi.fn(); analyticsState.reset = vi.fn();
  extrasState.vm = null; extrasState.loading = false; extrasState.error = null;
  extrasState.load = vi.fn(); extrasState.reset = vi.fn();
  timelineState.vm = null; timelineState.loading = false; timelineState.error = null;
  timelineState.load = vi.fn(); timelineState.reset = vi.fn();
}

describe("HistoryPage", () => {
  it("初始态：提示输入 + 不再有「完整分析（旧版）」深链（4c 退役）", () => {
    reset();
    const w = mount(HistoryPage);
    expect(w.text()).toContain("输入条码");
    expect(w.find("a.history__legacy-link").exists()).toBe(false);
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

  it("hit 但事件空 → 空态", async () => {
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
    const w = mount(HistoryPage);
    // HIS card defaults collapsed — open it first so the assertion is against a visible panel
    await w.find("#sbcard-his").trigger("click");
    await nextTick();
    expect(w.find("#sbpanel-his").text()).toContain("暂无历史变更");
    expect(w.find("#sbpanel-his").attributes("style") ?? "").not.toContain("display: none");
  });

  it("RECENT：初始从 localStorage 读出 chips 渲染", () => {
    reset();
    localStorage.setItem("history.recentQueries", JSON.stringify(["8299979002791", "ABC123"]));
    const w = mount(HistoryPage);
    const chips = w.findAll("button.history__recent-chip");
    expect(chips.length).toBe(2);
    expect(w.text()).toContain("8299979002791");
    localStorage.clear();
  });

  it("RECENT：旧 hit 残留 + 新查询失败 → 不写入 RECENT（回归）", async () => {
    reset();
    localStorage.setItem("history.recentQueries", JSON.stringify(["OLD1"]));
    // 模拟：load 失败时 store 把 result 清成 null、error 置位（修复后行为）
    state.load = vi.fn(async () => { state.result = null; state.error = "boom"; return true; });
    const w = mount(HistoryPage);
    await w.find("input.history__input").setValue("FAILQ");
    await w.find("input.history__input").trigger("keydown.enter");
    await Promise.resolve(); await Promise.resolve();
    const stored = JSON.parse(localStorage.getItem("history.recentQueries") || "[]");
    expect(stored).not.toContain("FAILQ");   // 失败查询不得进 RECENT
    expect(stored).toEqual(["OLD1"]);
    localStorage.clear();
  });

  it("RECENT：点击 chip 触发查询（load 被调用）", async () => {
    reset();
    localStorage.setItem("history.recentQueries", JSON.stringify(["CHIP1"]));
    const w = mount(HistoryPage);
    await w.find("button.history__recent-chip").trigger("click");
    expect(state.load).toHaveBeenCalledWith("CHIP1");
    localStorage.clear();
  });

  it("RECENT：命中查询后去重前置写回 localStorage（上限 6）", async () => {
    reset();
    localStorage.setItem("history.recentQueries", JSON.stringify(["OLD1", "ABC123"]));
    // 让 mock load 设成命中（返回 true 表示 fresh，HC-B7 门控需要）
    state.load = vi.fn(async () => {
      state.result = {
        kind: "hit",
        current: {
          barcode: "ABC123", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
          productNameZh: null, productNameLocal: null,
          storeLocations: [], warehouseLocations: [], unknownLocations: [],
          salePrice: null, source: null, updatedAt: null,
        },
        events: [],
      };
      return true;
    });
    const w = mount(HistoryPage);
    await w.find("input.history__input").setValue("ABC123");
    await w.find("input.history__input").trigger("keydown.enter");
    await Promise.resolve(); await Promise.resolve(); // 等 await store.load 链
    const stored = JSON.parse(localStorage.getItem("history.recentQueries") || "[]");
    expect(stored[0]).toBe("ABC123");          // 前置
    expect(stored.filter((x: string) => x === "ABC123").length).toBe(1); // 去重
    expect(stored).toContain("OLD1");
    localStorage.clear();
  });
});

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

it("命中后渲染分析块（销售分析 + 采购面 + 客户拆分）", () => {
  reset(); hitState(); analyticsState.vm = aVm();
  const w = mount(HistoryPage);
  expect(w.text()).toContain("销售分析");
  expect(w.text()).toContain("采购面");
  expect(w.text()).toContain("老外");
});

it("analytics 普通失败：分析块显错，但 P1 hero/概况/时间线仍在（HC-A4）", () => {
  reset(); hitState(); analyticsState.error = "API 500: /api/history/B1/analytics";
  const w = mount(HistoryPage);
  expect(w.text()).toContain("API 500");
  expect(w.text()).toContain("M1");
  expect(w.text()).toContain("名");
  expect(w.text()).toContain("历史时间线");
});

it("analytics 401（error 保持 null）：不显块内错误，P1 部分正常", () => {
  reset(); hitState();
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

// ── 2b extras + restock tests ────────────────────────────────────────────────

function aExtrasVm(restockOverride: ExtrasPageVM["restock"] = aRestock()): ExtrasPageVM {
  return {
    extras: {
      returnQty: 3,
      totalSaleQtyGross: 47,
      returnRatePct: 5,
      priceStats: { mean: 12.5, std: 1.2, min: 10.0, max: 15.0, n: 50 },
      topCustomersCn: [
        { customerId: "C001", customerType: "cn", customerName: "张三", qty: 20, lastAt: "2026-05-01" },
      ],
      topCustomersForeign: [
        { customerId: "G001", customerType: "fo", customerName: "Nikos", qty: 10, lastAt: "2026-04-10" },
      ],
      retailSummary: { qty: 5, revenue: 62.5, nTransactions: 3, lastAt: "2026-05-15", avgTicketQty: 1.7 },
      firstEventAt: "2024-01-01",
      lastEventAt: "2026-06-01",
      isHistoryTruncated: false,
    },
    holding: { avgDays: 14, nPairs: 10, oldestHeldDays: 30 },
    heatmap: {
      years: ["2024", "2025"],
      matrix: {
        "2024": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "2025": [2, 0, 1, 3, 5, 0, 4, 2, 0, 1, 3, 8],
      },
      maxQty: 12,
    },
    forecast: { quarterMu: 30, quarterP98: 50, computedAt: "2026-06-01", isStale: false, stockoutWeeksExcluded: 0 },
    restock: restockOverride,
  };
}

function aRestock(): NonNullable<ExtrasPageVM["restock"]> {
  return {
    masterSalePriceEur: 12.5,
    saleNetAvg: 11.0,
    retailPriceObserved: 25.0,
    retailPriceEstimate: 25.0,
    retailQty26w: 5,
    lastPurchaseUnitPrice: 7.0,
    masterStockPriceEur: 7.0,
    marginPct: 44,
    qtyTotal: 20,
    inventorySaleValueEur: 250.0,
    inventoryCostValueEur: 140.0,
    weeksOfCover: 8.5,
    lifetimeInvestedEur: 700.0,
    lifetimePurchaseQty: 100,
    lifetimeSaleRevenueEur: 625.0,
    lifetimeSaleQty: 50,
    realizedProfitEur: 200.0,
    netCashflowEur: 60.0,
    inventoryImbalancePct: 5,
    weeklyVelocity: 2.5,
    weeklyRevenue: 31.25,
    nActiveWeeks26w: 18,
    lastPurchaseDaysAgo: 45,
    urgencyScore: 72,
    urgencyBreakdown: { cover: 20, recency: 8, velocity: 25, margin: 19, demandValidity: null },
  };
}

it("2b: hit → extrasStore.load(barcode) 被调用，两面板渲染", async () => {
  reset();
  state.load = vi.fn(async () => {
    state.result = {
      kind: "hit",
      current: {
        barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
        productNameZh: null, productNameLocal: null,
        storeLocations: [], warehouseLocations: [], unknownLocations: [],
        salePrice: null, source: null, updatedAt: null,
      },
      events: [],
    };
    return true;
  });
  extrasState.vm = aExtrasVm();
  const w = mount(HistoryPage);
  await w.find("input.history__input").setValue("B1");
  await w.find("input.history__input").trigger("keydown.enter");
  await Promise.resolve(); await Promise.resolve();
  expect(extrasState.load).toHaveBeenCalledWith("B1");
  expect(w.text()).toContain("退货率");
  expect(w.text()).toContain("月度热力图");
  expect(w.text()).toContain("💰 财务");
  expect(w.text()).toContain("📦 库存");
  // RST card header always shows "补货决策快照"; the body shows restock data when vm.restock is set
  expect(w.text()).toContain("补货决策快照");
});

it("2b: extras 失败 → 2b 错误条，但 P1 hero / 2a / 时间线仍在（HC-B3）", () => {
  reset(); hitState(); extrasState.error = "API 500: extras";
  const w = mount(HistoryPage);
  expect(w.text()).toContain("深度分析加载失败");
  expect(w.text()).toContain("M1");      // P1 hero
  expect(w.text()).toContain("历史时间线");
});

it("2b: extras 401（error null）→ 不显 2b 错误条，P1 正常", () => {
  reset(); hitState();
  // extrasState.error stays null (store swallowed 401)
  const w = mount(HistoryPage);
  expect(w.text()).not.toContain("深度分析加载失败");
  expect(w.text()).toContain("M1");
});

it("2b: forecast null → '序列太短未训出'", () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(aRestock());
  extrasState.vm!.forecast = null;
  const w = mount(HistoryPage);
  expect(w.text()).toContain("序列太短未训出");
});

it("2b: forecast.isStale → '预测过期' badge", () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(aRestock());
  extrasState.vm!.forecast = { quarterMu: 10, quarterP98: 20, computedAt: null, isStale: true, stockoutWeeksExcluded: 0 };
  const w = mount(HistoryPage);
  expect(w.text()).toContain("预测过期");
});

it("2b: restock null → RST 卡显暂无补货快照，无财务内容", () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(null);
  const w = mount(HistoryPage);
  expect(w.text()).toContain("退货率");          // extras (left deep panel) present
  // RST card always exists; body shows "暂无补货快照" when vm.restock is null
  expect(w.find("#sbpanel-rst").text()).toContain("暂无补货快照");
  expect(w.text()).not.toContain("💰 财务");      // no financial data
});

it("2b: 热力图每行渲染 12 个单元格", () => {
  reset(); hitState(); extrasState.vm = aExtrasVm();
  const w = mount(HistoryPage);
  const rows = w.findAll("table.heat-mini tbody tr");
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    // 1 hy cell + 12 month cells = 13 td
    const tds = row.findAll("td");
    expect(tds.length).toBe(13);
  }
});

it("2b: 热力图 maxQty=0 → 所有数据格显示 '—'", () => {
  reset(); hitState();
  extrasState.vm = aExtrasVm();
  extrasState.vm!.heatmap = {
    years: ["2025"],
    matrix: { "2025": new Array(12).fill(0) },
    maxQty: 0,
  };
  const w = mount(HistoryPage);
  const tbody = w.find("table.heat-mini tbody");
  // all month cells should show —
  const cells = tbody.findAll("td.hc");
  expect(cells.length).toBe(12);
  for (const cell of cells) {
    expect(cell.text()).toBe("—");
  }
});

it("2b: notfound → extrasStore.reset 调用，面板不渲染", async () => {
  reset();
  state.load = vi.fn(async () => {
    state.result = { kind: "notfound" };
    return true;
  });
  const w = mount(HistoryPage);
  await w.find("input.history__input").setValue("NOPE");
  await w.find("input.history__input").trigger("keydown.enter");
  await Promise.resolve(); await Promise.resolve();
  expect(extrasState.reset).toHaveBeenCalled();
  expect(w.text()).not.toContain("退货率");
});

it("2b: HC-B7 门控 — store.load 返回 false → analyticsStore.load / extrasStore.load 均不调用", async () => {
  reset();
  state.load = vi.fn(async () => false);
  const w = mount(HistoryPage);
  await w.find("input.history__input").setValue("B1");
  await w.find("input.history__input").trigger("keydown.enter");
  await Promise.resolve(); await Promise.resolve();
  expect(analyticsState.load).not.toHaveBeenCalled();
  expect(extrasState.load).not.toHaveBeenCalled();
});

it("2b: demandValidity < 1.0 → ×dv 标签同时出现在库存和距进货行", () => {
  reset(); hitState();
  const restock = aRestock();
  restock.urgencyBreakdown = { cover: 20, recency: 8, velocity: 25, margin: 19, demandValidity: 0.25 };
  extrasState.vm = aExtrasVm(restock);
  const w = mount(HistoryPage);
  // Both cover and recency rows must contain the ×0.25 tag
  const dvTags = w.findAll("span.rs-dv-tag");
  expect(dvTags.length).toBe(2);
  for (const tag of dvTags) {
    expect(tag.text()).toBe("×0.25");
    expect(tag.attributes("title")).toBe("长尾活跃度折扣");
  }
});

it("2b: demandValidity === 1.0 → 不渲染 ×dv 标签", () => {
  reset(); hitState();
  const restock = aRestock();
  restock.urgencyBreakdown = { cover: 20, recency: 8, velocity: 25, margin: 19, demandValidity: 1.0 };
  extrasState.vm = aExtrasVm(restock);
  const w = mount(HistoryPage);
  expect(w.findAll("span.rs-dv-tag").length).toBe(0);
});

it("2b: demandValidity === null → 不渲染 ×dv 标签", () => {
  reset(); hitState();
  const restock = aRestock();
  restock.urgencyBreakdown = { cover: 20, recency: 8, velocity: 25, margin: 19, demandValidity: null };
  extrasState.vm = aExtrasVm(restock);
  const w = mount(HistoryPage);
  expect(w.findAll("span.rs-dv-tag").length).toBe(0);
});

// ── Phase 3: TimelineChart 接线 ──────────────────────────────────────────────

function aTimelineVm() {
  return {
    weeks: [{ weekStart: "2026-01-05", saleQty: 3, purchaseUnitPrice: 7.5, rawUnitPriceLocal: null, currencyLocal: "EUR" }],
    monthlySales: [{ monthStart: "2026-01-01", saleQty: 10, retailQty: 2 }],
  };
}

it("P3: TML 折叠卡含区块标题「销售/进价时间线」；打开后 TimelineChart 渲染", async () => {
  reset();
  state.result = {
    kind: "hit",
    current: {
      barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
      productNameZh: null, productNameLocal: null,
      storeLocations: [], warehouseLocations: [], unknownLocations: [],
      salePrice: null, source: null, updatedAt: null,
    },
    events: [],
  };
  timelineState.vm = aTimelineVm();
  const w = mount(HistoryPage);
  // TML card header always visible
  expect(w.find("#sbcard-tml").text()).toContain("销售/进价时间线");
  // Open TML card to render chart
  await w.find("#sbcard-tml").trigger("click");
  expect(w.find("#sbpanel-tml").isVisible()).toBe(true);
  expect(w.find(".stub-timeline-chart").exists()).toBe(true);
});

it("P3: hit → timelineStore.load(bc) 调用，TML 卡存在；打开后 stub 渲染", async () => {
  reset();
  state.load = vi.fn(async () => {
    state.result = {
      kind: "hit",
      current: {
        barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
        productNameZh: null, productNameLocal: null,
        storeLocations: [], warehouseLocations: [], unknownLocations: [],
        salePrice: null, source: null, updatedAt: null,
      },
      events: [],
    };
    return true;
  });
  timelineState.vm = aTimelineVm();
  const w = mount(HistoryPage);
  await w.find("input.history__input").setValue("B1");
  await w.find("input.history__input").trigger("keydown.enter");
  await Promise.resolve(); await Promise.resolve();
  expect(timelineState.load).toHaveBeenCalledWith("B1");
  // TML card always exists in right column
  expect(w.find("#sbcard-tml").exists()).toBe(true);
  // Open TML to confirm chart stub mounts
  await w.find("#sbcard-tml").trigger("click");
  expect(w.find(".stub-timeline-chart").exists()).toBe(true);
});

it("P3: 顺序 — 右栏卡片徽章顺序为 SLA→PUR→RST→TML→HIS", () => {
  reset();
  state.result = {
    kind: "hit",
    current: {
      barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
      productNameZh: null, productNameLocal: null,
      storeLocations: [], warehouseLocations: [], unknownLocations: [],
      salePrice: null, source: null, updatedAt: null,
    },
    events: [],
  };
  timelineState.vm = aTimelineVm();
  analyticsState.vm = aVm();
  const w = mount(HistoryPage);
  const badges = w.findAll(".history__foldcard-badge").map((b) => b.text());
  expect(badges).toEqual(["SLA", "PUR", "RST", "TML", "HIS"]);
});

it("P3: HC-P3-3 走势图失败 → TML 卡打开后显错误条；P1 hero/概况 + SLA + extras 仍在", async () => {
  reset();
  state.result = {
    kind: "hit",
    current: {
      barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
      productNameZh: "品名X", productNameLocal: null,
      storeLocations: [], warehouseLocations: [], unknownLocations: [],
      salePrice: null, source: null, updatedAt: null,
    },
    events: [],
  };
  timelineState.error = "走势图 API 500";
  analyticsState.vm = aVm();
  extrasState.vm = aExtrasVm();
  const w = mount(HistoryPage);
  // Open TML card to see the error
  await w.find("#sbcard-tml").trigger("click");
  expect(w.find("#sbpanel-tml").text()).toContain("走势图 API 500");
  // P1 still present
  expect(w.text()).toContain("M1");
  expect(w.text()).toContain("品名X");
  // 2a SLA still present (card is open by default)
  expect(w.text()).toContain("销售分析");
  // 2b extras still present (in left deep panel)
  expect(w.text()).toContain("退货率");
});

it("P3: 走势图 401（error null, vm null）→ 不显走势图错误条", () => {
  reset();
  state.result = {
    kind: "hit",
    current: {
      barcode: "B1", model: "M1", isTrulyDiscontinued: false, manualGrade: null,
      productNameZh: null, productNameLocal: null,
      storeLocations: [], warehouseLocations: [], unknownLocations: [],
      salePrice: null, source: null, updatedAt: null,
    },
    events: [],
  };
  // error stays null (store swallowed 401), vm null
  const w = mount(HistoryPage);
  expect(w.find(".history__timeline-chart-error").exists()).toBe(false);
});

it("P3: non-hit (notfound) → timelineStore.reset 调用，走势图块不渲染", async () => {
  reset();
  state.load = vi.fn(async () => {
    state.result = { kind: "notfound" };
    return true;
  });
  const w = mount(HistoryPage);
  await w.find("input.history__input").setValue("NOPE");
  await w.find("input.history__input").trigger("keydown.enter");
  await Promise.resolve(); await Promise.resolve();
  expect(timelineState.reset).toHaveBeenCalled();
  expect(w.find(".history__timeline-chart").exists()).toBe(false);
});

it("P3: HC-B7 门控 — store.load 返回 false → timelineStore.load 不调用", async () => {
  reset();
  state.load = vi.fn(async () => false);
  const w = mount(HistoryPage);
  await w.find("input.history__input").setValue("B1");
  await w.find("input.history__input").trigger("keydown.enter");
  await Promise.resolve(); await Promise.resolve();
  expect(timelineState.load).not.toHaveBeenCalled();
});

it("P3: doReset → timelineStore.reset 调用", async () => {
  reset();
  const w = mount(HistoryPage);
  await w.find("button.history__btn--ghost").trigger("click");
  expect(timelineState.reset).toHaveBeenCalled();
});

// ── Phase 4a: tab 壳 + 最近改动接线 + 守卫 ──────────────────────────────────────

it("4a: 初始两个 tab，默认 search active，搜索 UI 可见", () => {
  reset();
  const w = mount(HistoryPage);
  const tabs = w.findAll("button.history__tab");
  expect(tabs.length).toBe(2);
  expect(w.text()).toContain("货号查询");
  expect(w.text()).toContain("批次记录");
  // 默认 search tab 内容可见
  expect(w.find("input.history__input").isVisible()).toBe(true);
});

it("4a: 批次 tab 懒挂载 — 激活前 RecentChangesPanel 不存在", () => {
  reset();
  const w = mount(HistoryPage);
  expect(w.findComponent(RecentChangesPanel).exists()).toBe(false);
});

it("4a: 点击批次记录 → panel 挂载且可见，搜索 UI 隐藏", async () => {
  reset();
  const w = mount(HistoryPage);
  const batchTab = w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!;
  await batchTab.trigger("click");
  expect(w.findComponent(RecentChangesPanel).exists()).toBe(true);
  expect(w.find("div.stub-recent-changes").isVisible()).toBe(true);
  // 搜索 UI 元素仍存在但不可见 (v-show=false)
  expect(w.find("input.history__input").isVisible()).toBe(false);
});

it("4a: 切回货号查询 → 搜索 UI 复现可见，panel 保持挂载（batchVisited 黏住）", async () => {
  reset();
  const w = mount(HistoryPage);
  const batchTab = w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!;
  const searchTab = w.findAll("button.history__tab").find((b) => b.text().includes("货号查询"))!;
  await batchTab.trigger("click");
  expect(w.findComponent(RecentChangesPanel).exists()).toBe(true);
  await searchTab.trigger("click");
  expect(w.find("input.history__input").isVisible()).toBe(true);
  // panel 仍挂载（懒挂载后不卸载）
  expect(w.findComponent(RecentChangesPanel).exists()).toBe(true);
  expect(w.find("div.stub-recent-changes").isVisible()).toBe(false);
});

it("4a: drill — panel emit drill → 切回 search tab + q=barcode + runSearch(load) 调用", async () => {
  reset();
  const w = mount(HistoryPage);
  const batchTab = w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!;
  await batchTab.trigger("click");
  // emit drill from stub
  await w.find("button.stub-drill").trigger("click");
  await Promise.resolve(); await Promise.resolve();
  // 切回 search：搜索 UI 可见
  expect(w.find("input.history__input").isVisible()).toBe(true);
  // q 被写入
  expect((w.find("input.history__input").element as HTMLInputElement).value).toBe("DRILLBC");
  // runSearch 执行 → store.load(barcode)
  expect(state.load).toHaveBeenCalledWith("DRILLBC");
});

it("4a: 批次 tab 失败隔离 — 搜索 tab 仍可独立工作", async () => {
  reset();
  const w = mount(HistoryPage);
  // 先访问批次 tab（懒挂载）
  const batchTab = w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!;
  await batchTab.trigger("click");
  const searchTab = w.findAll("button.history__tab").find((b) => b.text().includes("货号查询"))!;
  await searchTab.trigger("click");
  // 搜索仍能触发 load
  await w.find("input.history__input").setValue("XYZ");
  await w.find("input.history__input").trigger("keydown.enter");
  expect(state.load).toHaveBeenCalledWith("XYZ");
});

// ── Phase 4b: 批次记录子-tab 接线 ─────────────────────────────────────────────

it("4b: 批次 tab 下默认子-tab 为最近改动，ScanBatchPanel 未挂载", async () => {
  reset();
  const w = mount(HistoryPage);
  const batchTab = w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!;
  await batchTab.trigger("click");
  // 子-tab 按钮存在
  expect(w.text()).toContain("最近改动");
  expect(w.text()).toContain("扫描批次");
  // ScanBatchPanel 尚未挂载（scanVisited=false）
  expect(w.findComponent(ScanBatchPanel).exists()).toBe(false);
});

it("4b: 点击扫描批次子-tab → ScanBatchPanel 挂载且可见", async () => {
  reset();
  const w = mount(HistoryPage);
  const batchTab = w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!;
  await batchTab.trigger("click");
  const scanSubTab = w.findAll("button.history__sub-tab").find((b) => b.text().includes("扫描批次"))!;
  await scanSubTab.trigger("click");
  // ScanBatchPanel 现在已挂载
  expect(w.findComponent(ScanBatchPanel).exists()).toBe(true);
  expect(w.find("div.stub-scan-batch").isVisible()).toBe(true);
  // RecentChangesPanel 仍挂载但不可见
  expect(w.findComponent(RecentChangesPanel).exists()).toBe(true);
  expect(w.find("div.stub-recent-changes").isVisible()).toBe(false);
});

it("4b: 切回最近改动子-tab → ScanBatchPanel 保持挂载（scanVisited 黏住）但不可见", async () => {
  reset();
  const w = mount(HistoryPage);
  const batchTab = w.findAll("button.history__tab").find((b) => b.text().includes("批次记录"))!;
  await batchTab.trigger("click");
  const scanSubTab = w.findAll("button.history__sub-tab").find((b) => b.text().includes("扫描批次"))!;
  await scanSubTab.trigger("click");
  expect(w.findComponent(ScanBatchPanel).exists()).toBe(true);
  const recentSubTab = w.findAll("button.history__sub-tab").find((b) => b.text().includes("最近改动"))!;
  await recentSubTab.trigger("click");
  // ScanBatchPanel 仍挂载（不销毁）
  expect(w.findComponent(ScanBatchPanel).exists()).toBe(true);
  expect(w.find("div.stub-scan-batch").isVisible()).toBe(false);
  // RecentChangesPanel 重新可见
  expect(w.find("div.stub-recent-changes").isVisible()).toBe(true);
});

// ── Phase 4b.5: 两栏布局 / 折叠卡 / 左tab切换 / watch重置 ────────────────────────

it("4b.5: 命中态渲染两栏；右栏卡片顺序 SLA→PUR→RST→TML→HIS", () => {
  reset(); hitState();
  const w = mount(HistoryPage);
  expect(w.find(".history__cols").exists()).toBe(true);
  expect(w.findAll(".history__foldcard-badge").map((b) => b.text())).toEqual(["SLA", "PUR", "RST", "TML", "HIS"]);
});

it("4b.5: 概况/深度 切换换左栏内容且不影响右卡", async () => {
  reset(); hitState(); extrasState.vm = aExtrasVm();
  const w = mount(HistoryPage);
  const deepBtn = w.findAll(".history__lefttab").find((b) => b.text() === "深度")!;
  // initial state: overview visible (no display:none), deep hidden
  expect(w.find(".history__overview").attributes("style") ?? "").not.toContain("display: none");
  expect(w.find(".history__deep").attributes("style") ?? "").toContain("display: none");
  await deepBtn.trigger("click");
  expect(deepBtn.attributes("aria-pressed")).toBe("true");
  // after click: overview hidden, deep visible, right cards unaffected
  expect(w.find(".history__overview").attributes("style") ?? "").toContain("display: none");
  expect(w.find(".history__deep").attributes("style") ?? "").not.toContain("display: none");
  expect(w.find("#sbpanel-sla").attributes("style") ?? "").not.toContain("display: none"); // 右卡不受左tab影响
});

it("4b.5: 默认折叠态 SLA/PUR 开、RST/TML/HIS 关", () => {
  reset(); hitState();
  const w = mount(HistoryPage);
  expect(w.find("#sbpanel-sla").isVisible()).toBe(true);
  expect(w.find("#sbpanel-pur").isVisible()).toBe(true);
  expect(w.find("#sbpanel-rst").isVisible()).toBe(false);
  expect(w.find("#sbpanel-tml").isVisible()).toBe(false);
  expect(w.find("#sbpanel-his").isVisible()).toBe(false);
});

it("4b.5: 折叠 toggle 翻转 aria-expanded 与卡身可见性", async () => {
  reset(); hitState();
  const w = mount(HistoryPage);
  const hd = w.find("#sbcard-rst");
  expect(hd.attributes("aria-expanded")).toBe("false");
  expect(w.find("#sbpanel-rst").attributes("style") ?? "").toContain("display: none");
  await hd.trigger("click");
  expect(hd.attributes("aria-expanded")).toBe("true");
  expect(w.find("#sbpanel-rst").attributes("style") ?? "").not.toContain("display: none");
});

it("4b.5: 换新 barcode → leftTab 回 overview、折叠态回默认（watch 驱动）", async () => {
  reset(); hitState(); extrasState.vm = aExtrasVm();
  const w = mount(HistoryPage);
  // 切到深度 + 展开 RST（模拟用户在 SKU A 上的交互）
  await w.findAll(".history__lefttab").find((b) => b.text() === "深度")!.trigger("click");
  await w.find("#sbcard-rst").trigger("click");
  expect(w.find(".history__deep").isVisible()).toBe(true);
  expect(w.find("#sbpanel-rst").isVisible()).toBe(true);
  // 命中新 barcode（SKU B）→ 改 reactive 的 result.current.barcode，触发 watch
  state.result = {
    ...(state.result as Extract<HistoryResult, { kind: "hit" }>),
    current: {
      ...(state.result as Extract<HistoryResult, { kind: "hit" }>).current,
      barcode: "NEWBC999",
    },
  };
  await nextTick(); // flush reactive mutation into computed(hitBarcode)
  await nextTick(); // flush watch(hitBarcode) callback
  await nextTick(); // flush DOM update after watch mutates leftTab + cardOpen
  // watch 应已把 leftTab 重置 overview、cardOpen 重置默认
  expect(w.find(".history__overview").isVisible()).toBe(true);  // 回概况
  expect(w.find("#sbpanel-rst").attributes("style") ?? "").toContain("display: none"); // RST 回折叠
});

it("4b.5: extras vm=null（401后）→ 不崩、RST 不误报暂无补货快照（中性占位）", async () => {
  reset(); hitState();
  // extrasState.vm stays null (loading=false, error=null — 401 swallowed)
  // Crash-safety check: mounting must not throw
  expect(() => mount(HistoryPage)).not.toThrow();
  const w = mount(HistoryPage);
  // RST card defaults collapsed — open it first so the panel body is asserted
  await w.find("#sbcard-rst").trigger("click");
  await nextTick();
  // vm===null (401 transient) must NOT falsely claim "no restock data"
  expect(w.find("#sbpanel-rst").text()).not.toContain("暂无补货快照");
  expect(w.find("#sbpanel-rst").attributes("style") ?? "").not.toContain("display: none");
});

it("4b.5: analytics error → SLA 与 PUR 两卡各显错误条", () => {
  reset(); hitState(); analyticsState.error = "boom"; analyticsState.vm = null;
  const w = mount(HistoryPage);
  expect(w.find("#sbpanel-sla").text()).toContain("boom");
  expect(w.find("#sbpanel-pur").text()).toContain("boom");
});

it("4b.5: 左栏在右栏之前（DOM 顺序）", () => {
  reset(); hitState();
  const w = mount(HistoryPage);
  const left = w.find(".history__left").element;
  const right = w.find(".history__right").element;
  expect(left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("4b.5: 非命中态不渲染两栏 .history__cols", () => {
  reset(); // result=null (initial/non-hit state) — no hit, no .history__cols
  const w = mount(HistoryPage);
  expect(w.find(".history__cols").exists()).toBe(false);
});

it("4b.5: extrasStore.error → RST 卡内显示错误", async () => {
  reset(); hitState();
  extrasState.error = "ext boom"; extrasState.vm = null;
  const w = mount(HistoryPage);
  await w.find("#sbcard-rst").trigger("click");
  expect(w.find("#sbpanel-rst").text()).toContain("ext boom");
});
