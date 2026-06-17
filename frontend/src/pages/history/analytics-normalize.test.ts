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
