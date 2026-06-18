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
    expect(s.vm?.monthlySales.length).toBe(1);
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
