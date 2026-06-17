import { describe, expect, it } from "vitest";
import type { ForecastEvalData } from "../../api/types.gen";
import { normalizeForecastEval } from "./normalize";

const EMPTY: ForecastEvalData = {
  ok: true, run_id: null, backtest_date: null, forecast_skus: 0, scored_skus: 0,
  tiers: { high: 0, medium: 0, low: 0 },
  headline: { n: 0, median_mase: null, beats_naive_pct: null, avg_coverage_p98: null },
  by_sku_type: [], models: [],
};

describe("normalizeForecastEval", () => {
  it("空数据 → missing=true，计数归零", () => {
    const vm = normalizeForecastEval(EMPTY);
    expect(vm.missing).toBe(true);
    expect(vm.tiers).toEqual({ high: 0, medium: 0, low: 0 });
    expect(vm.byType).toEqual([]);
    expect(vm.models).toEqual([]);
  });

  it("有 run → missing=false，字段转 camelCase", () => {
    const vm = normalizeForecastEval({
      ...EMPTY,
      run_id: 44,
      backtest_date: "2026-06-15T01:00:00",
      forecast_skus: 100,
      scored_skus: 80,
      tiers: { high: 10, medium: 30, low: 60 },
      headline: { n: 80, median_mase: 0.83, beats_naive_pct: 62.5, avg_coverage_p98: 0.97 },
      by_sku_type: [
        { sku_type: "retail_dominant", n: 50, median_mase: 0.8, beats_naive_pct: 70, avg_coverage_p98: 0.98 },
      ],
      models: [
        { model_name: "EmpiricalQuantile", run_id: 44, created_at: "2026-06-15", is_production: true, n: 80, median_mase: 0.83, beats_naive_pct: 62.5, avg_coverage_p98: 0.97 },
      ],
    });
    expect(vm.missing).toBe(false);
    expect(vm.runId).toBe(44);
    expect(vm.headline.beatsNaivePct).toBe(62.5);
    expect(vm.byType[0].skuType).toBe("retail_dominant");
    expect(vm.models[0].isProduction).toBe(true);
  });
});
