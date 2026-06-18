import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { HistoryResult } from "./types";
import type { ExtrasPageVM } from "./extras-types";

const state = {
  result: null as HistoryResult | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
};
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

import HistoryPage from "./HistoryPage.vue";

function reset() {
  state.result = null; state.loading = false; state.error = null; state.load = vi.fn();
  analyticsState.vm = null; analyticsState.loading = false; analyticsState.error = null;
  analyticsState.load = vi.fn(); analyticsState.reset = vi.fn();
  extrasState.vm = null; extrasState.loading = false; extrasState.error = null;
  extrasState.load = vi.fn(); extrasState.reset = vi.fn();
}

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
  expect(w.text()).toContain("补货快照");
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

it("2b: restock null → 不渲染补货快照面板", () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(null);
  const w = mount(HistoryPage);
  expect(w.text()).toContain("退货率");          // extras panel present
  expect(w.text()).not.toContain("补货快照");     // restock panel absent
  expect(w.text()).not.toContain("💰 财务");
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
