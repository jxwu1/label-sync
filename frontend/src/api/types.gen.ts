// 由 tools/gen_ts_types.py 生成 — 不要手改。来源: app/schemas_api.py

export interface BriefingActions {
  restock: Record<string, unknown>;
  follow_up: Record<string, unknown>;
  review_anomalies: Record<string, unknown>;
}

export interface BriefingCards {
  sales_health: Record<string, unknown>;
  restock_risk: Record<string, unknown>;
  stockout_impact: Record<string, unknown>;
  overstock_risk: Record<string, unknown>;
  data_health: Record<string, unknown>;
}

export interface BriefingData {
  ok: boolean;
  generated_at: string;
  data_week: string | null;
  data_week_complete: boolean;
  cards: BriefingCards;
  actions: BriefingActions;
}

export interface MeData {
  display_name: string;
  is_admin: boolean;
}

export interface ForecastEvalByType {
  sku_type: string;
  n: number;
  median_mase: number | null;
  beats_naive_pct: number | null;
  avg_coverage_p98: number | null;
}

export interface ForecastEvalMetrics {
  n: number;
  median_mase: number | null;
  beats_naive_pct: number | null;
  avg_coverage_p98: number | null;
}

export interface ForecastEvalModelRow {
  model_name: string;
  run_id: number;
  created_at: string | null;
  is_production: boolean;
  n: number;
  median_mase: number | null;
  beats_naive_pct: number | null;
  avg_coverage_p98: number | null;
}

export interface ForecastEvalTiers {
  high: number;
  medium: number;
  low: number;
}

export interface ForecastEvalData {
  ok: boolean;
  run_id: number | null;
  backtest_date: string | null;
  forecast_skus: number;
  scored_skus: number;
  tiers: ForecastEvalTiers;
  headline: ForecastEvalMetrics;
  by_sku_type: ForecastEvalByType[];
  models: ForecastEvalModelRow[];
}
