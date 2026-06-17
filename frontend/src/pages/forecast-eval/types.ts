export interface MetricsVM {
  n: number;
  medianMase: number | null;
  beatsNaivePct: number | null;
  avgCoverageP98: number | null;
}
export interface ByTypeRow extends MetricsVM {
  skuType: string;
}
export interface ModelRow extends MetricsVM {
  modelName: string;
  runId: number;
  createdAt: string | null;
  isProduction: boolean;
}
export interface ForecastEvalViewModel {
  missing: boolean; // run_id == null：尚无回测数据
  runId: number | null;
  backtestDate: string | null;
  forecastSkus: number;
  scoredSkus: number;
  tiers: { high: number; medium: number; low: number };
  headline: MetricsVM;
  byType: ByTypeRow[];
  models: ModelRow[];
}
