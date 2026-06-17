import type {
  ForecastEvalByType,
  ForecastEvalData,
  ForecastEvalMetrics,
  ForecastEvalModelRow,
} from "../../api/types.gen";
import type { ByTypeRow, ForecastEvalViewModel, MetricsVM, ModelRow } from "./types";

function num(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}
function metrics(m: ForecastEvalMetrics): MetricsVM {
  return {
    n: num(m.n) ?? 0,
    medianMase: num(m.median_mase),
    beatsNaivePct: num(m.beats_naive_pct),
    avgCoverageP98: num(m.avg_coverage_p98),
  };
}

/** API 边界唯一收窄点：组件只吃 ForecastEvalViewModel，不碰 raw。 */
export function normalizeForecastEval(raw: ForecastEvalData): ForecastEvalViewModel {
  const byType: ByTypeRow[] = (raw.by_sku_type ?? []).map((r: ForecastEvalByType) => ({
    skuType: r.sku_type,
    ...metrics(r),
  }));
  const models: ModelRow[] = (raw.models ?? []).map((m: ForecastEvalModelRow) => ({
    modelName: m.model_name,
    runId: num(m.run_id) ?? 0,
    createdAt: m.created_at ?? null,
    isProduction: m.is_production === true,
    ...metrics(m),
  }));
  return {
    missing: raw.run_id == null,
    runId: num(raw.run_id),
    backtestDate: raw.backtest_date ?? null,
    forecastSkus: num(raw.forecast_skus) ?? 0,
    scoredSkus: num(raw.scored_skus) ?? 0,
    tiers: {
      high: num(raw.tiers?.high) ?? 0,
      medium: num(raw.tiers?.medium) ?? 0,
      low: num(raw.tiers?.low) ?? 0,
    },
    headline: metrics(raw.headline),
    byType,
    models,
  };
}
