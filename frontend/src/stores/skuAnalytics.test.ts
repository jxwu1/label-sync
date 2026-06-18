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
    await s.load("A");
    expect(s.vm).not.toBeNull();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load("B");
    expect(s.vm).toBeNull();
    expect(s.error).toBe("boom");
  });

  it("reset() 清 vm/error", async () => {
    const s = useSkuAnalyticsStore();
    await s.load("A");
    s.reset();
    expect(s.vm).toBeNull();
    expect(s.error).toBeNull();
  });

  const makePayload = (totalQty: number) => ({
    ok: true,
    sales: { total_qty: totalQty, total_revenue: 62.5, unique_customers: 2, lifespan_days: 30, trend_slope_pct_per_week: 1.2 },
    purchase: { stock_balance: 5, avg_margin_pct: 40.0, purchase_freq_365d: 1, last_purchase_days_ago: 47 },
    customer_split: {
      cn: { qty: 3, unique_customers: 1, max_single_qty: 3, last_at: "2026-05-08", avg_freq_per_month: 0.5 },
      fo: { qty: 2, unique_customers: 1, max_single_qty: 2, last_at: null, avg_freq_per_month: 0.0 },
    },
  });

  it("HC-B7 stale: A resolves after B, B wins", async () => {
    let resolveA: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
    vi.mocked(apiGet).mockResolvedValueOnce(makePayload(42));
    const s = useSkuAnalyticsStore();
    const pA = s.load("A");
    const pB = s.load("B");
    await pB;
    resolveA(makePayload(99));
    await pA;
    expect(s.vm?.sales.totalQty).toBe(42); // B wins, not A's 99
  });

  it("HC-B7 reset cancels pending", async () => {
    let resolveA: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
    const s = useSkuAnalyticsStore();
    const pA = s.load("A");
    s.reset();
    resolveA(makePayload(99));
    await pA;
    expect(s.vm).toBeNull();
  });
});
