import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";

const apiGet = vi.fn();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiGet: (...a: unknown[]) => apiGet(...a) };
});

import { useSkuExtrasStore } from "./skuExtras";
import { UnauthenticatedError } from "../api/client";

const okPayload = {
  ok: true,
  extras: { return_qty: 0, total_sale_qty_gross: 0, return_rate_pct: null,
    price_stats: { mean: null, std: null, min: null, max: null, n: 0 },
    top_customers_cn: [], top_customers_foreign: [],
    retail_summary: { qty: 0, revenue: 0, n_transactions: 0, last_at: null, avg_ticket_qty: null },
    first_event_at: null, last_event_at: null, is_history_truncated: false },
  holding: { avg_days: null, n_pairs: 0, oldest_held_days: null },
  heatmap: { years: [], matrix: {}, max_qty: 0 },
  forecast: null, restock: null,
};

beforeEach(() => { setActivePinia(createPinia()); apiGet.mockReset(); });

describe("useSkuExtrasStore", () => {
  it("load fills vm and calls right endpoint", async () => {
    apiGet.mockResolvedValueOnce(okPayload);
    const s = useSkuExtrasStore();
    await s.load("12345");
    expect(apiGet).toHaveBeenCalledWith("/api/history/12345/analytics/extras");
    expect(s.vm).not.toBeNull();
  });

  it("load failure fills error", async () => {
    apiGet.mockRejectedValueOnce(new Error("boom"));
    const s = useSkuExtrasStore();
    await s.load("12345");
    expect(s.error).toBe("boom");
    expect(s.vm).toBeNull();
  });

  it("swallows UnauthenticatedError (error stays null)", async () => {
    apiGet.mockRejectedValueOnce(new UnauthenticatedError());
    const s = useSkuExtrasStore();
    await s.load("12345");
    expect(s.error).toBeNull();
  });

  it("old vm cleared when new load fails", async () => {
    apiGet.mockResolvedValueOnce(okPayload);
    const s = useSkuExtrasStore();
    await s.load("A");
    expect(s.vm).not.toBeNull();
    apiGet.mockRejectedValueOnce(new Error("x"));
    await s.load("B");
    expect(s.vm).toBeNull();
  });

  it("HC-B7 stale: A resolves after B, B wins (A does not write)", async () => {
    let resolveA: (v: unknown) => void = () => {};
    apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
    apiGet.mockResolvedValueOnce({ ...okPayload, extras: { ...okPayload.extras, return_qty: 999 } });
    const s = useSkuExtrasStore();
    const pA = s.load("A");
    const pB = s.load("B");
    await pB;
    resolveA(okPayload);
    await pA;
    expect(s.vm?.extras.returnQty).toBe(999);
  });

  it("HC-B7 reset cancels pending (resolve after reset does not write)", async () => {
    let resolveA: (v: unknown) => void = () => {};
    apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
    const s = useSkuExtrasStore();
    const pA = s.load("A");
    s.reset();
    resolveA(okPayload);
    await pA;
    expect(s.vm).toBeNull();
  });
});
