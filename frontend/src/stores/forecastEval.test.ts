import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(async () => ({
    ok: true, run_id: 44, backtest_date: "2026-06-15", forecast_skus: 100, scored_skus: 80,
    tiers: { high: 10, medium: 30, low: 60 },
    headline: { n: 80, median_mase: 0.83, beats_naive_pct: 62.5, avg_coverage_p98: 0.97 },
    by_sku_type: [], models: [],
  })),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useForecastEvalStore } from "./forecastEval";

describe("forecastEval store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 填充 vm 并清 loading", async () => {
    const s = useForecastEvalStore();
    const p = s.load();
    expect(s.loading).toBe(true);
    await p;
    expect(s.loading).toBe(false);
    expect(s.vm?.runId).toBe(44);
    expect(s.vm?.missing).toBe(false);
    expect(s.error).toBeNull();
  });

  it("load 失败 → error 填充，vm 保持 null", async () => {
    const s = useForecastEvalStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load();
    expect(s.error).toBe("boom");
    expect(s.vm).toBeNull();
  });

  it("未登录错误被吞掉，不污染 error", async () => {
    const s = useForecastEvalStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    await s.load();
    expect(s.error).toBeNull();
  });
});
