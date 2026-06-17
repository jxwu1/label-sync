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

const analyticsState = {
  vm: null as import("./analytics-types").AnalyticsVM | null,
  loading: false,
  error: null as string | null,
  load: vi.fn(),
  reset: vi.fn(),
};
vi.mock("../../stores/skuAnalytics", () => ({ useSkuAnalyticsStore: () => analyticsState }));

import HistoryPage from "./HistoryPage.vue";

function reset() {
  state.result = null; state.loading = false; state.error = null; state.load = vi.fn();
  analyticsState.vm = null; analyticsState.loading = false; analyticsState.error = null;
  analyticsState.load = vi.fn(); analyticsState.reset = vi.fn();
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
    state.load = vi.fn(async () => { state.result = null; state.error = "boom"; });
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
    // 让 mock load 设成命中
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
