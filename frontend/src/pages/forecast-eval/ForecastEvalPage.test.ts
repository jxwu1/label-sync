import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { ForecastEvalViewModel } from "./types";

function vmStub(over: Partial<ForecastEvalViewModel> = {}): ForecastEvalViewModel {
  return {
    missing: false, runId: 44, backtestDate: "2026-06-15", forecastSkus: 100, scoredSkus: 80,
    tiers: { high: 10, medium: 30, low: 60 },
    headline: { n: 80, medianMase: 0.83, beatsNaivePct: 62.5, avgCoverageP98: 0.97 },
    byType: [{ skuType: "retail_dominant", n: 50, medianMase: 0.8, beatsNaivePct: 70, avgCoverageP98: 0.98 }],
    models: [{ modelName: "EmpiricalQuantile", runId: 44, createdAt: "2026-06-15", isProduction: true, n: 80, medianMase: 0.83, beatsNaivePct: 62.5, avgCoverageP98: 0.97 }],
    ...over,
  };
}

const state = { vm: null as ForecastEvalViewModel | null, loading: false, error: null as string | null, load: vi.fn() };
vi.mock("../../stores/forecastEval", () => ({ useForecastEvalStore: () => state }));

import ForecastEvalPage from "./ForecastEvalPage.vue";

describe("ForecastEvalPage", () => {
  it("loading 时显示加载中", () => {
    state.vm = null; state.loading = true; state.error = null;
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("加载中");
  });

  it("missing 时显示空态提示", () => {
    state.loading = false; state.error = null;
    state.vm = vmStub({ missing: true, runId: null, backtestDate: null, forecastSkus: 0, scoredSkus: 0, tiers: { high: 0, medium: 0, low: 0 }, byType: [], models: [] });
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("尚无回测数据");
  });

  it("有数据时渲染 KPI + tier 计数 + 模型行", () => {
    state.loading = false; state.error = null; state.vm = vmStub();
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("63%");
    expect(w.text()).toContain("retail_dominant");
    expect(w.text()).toContain("EmpiricalQuantile");
    expect(w.text()).toContain("60");
  });

  it("系统级 error → 整页错误态", () => {
    state.vm = null; state.loading = false; state.error = "API 500: /api/forecast-eval/data";
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("API 500");
  });
});
