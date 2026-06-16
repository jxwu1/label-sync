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
