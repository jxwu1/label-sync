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

export interface HistoryChange {
  field: string;
  old: string | null;
  new: string | null;
  old_split?: HistoryLocSplit | null;
  new_split?: HistoryLocSplit | null;
}

export interface HistoryCurrent {
  barcode: string;
  model: string;
  location: string;
  is_active: boolean;
  source: string | null;
  created_at: string | null;
  updated_at: string | null;
  product_name_zh: string | null;
  product_name_local: string | null;
  erp_category_raw: string | null;
  erp_category_code: string | null;
  manual_grade: number | null;
  stock_price: number | null;
  sale_price: number | null;
  is_truly_discontinued: boolean;
  store_locations: string[];
  warehouse_locations: string[];
  unknown_locations: string[];
}

export interface HistoryEvent {
  at: string;
  change_type: string | null;
  source: string | null;
  summary?: string | null;
  changes: HistoryChange[];
}

export interface HistoryFuzzyMatch {
  barcode: string;
  model: string;
  location: string | null;
  is_active: boolean;
}

export interface HistoryLocSplit {
  stores: string[];
  warehouses: string[];
  unknown: string[];
}

export interface HistorySearchData {
  ok: boolean;
  found: boolean;
  current?: HistoryCurrent | null;
  events?: HistoryEvent[] | null;
  fuzzy_matches?: HistoryFuzzyMatch[] | null;
}

export interface SkuCustomerEnd {
  qty: number;
  unique_customers: number;
  max_single_qty: number;
  last_at: string | null;
  avg_freq_per_month: number;
}

export interface SkuCustomerSplit {
  cn: SkuCustomerEnd;
  fo: SkuCustomerEnd;
}

export interface SkuPurchaseMetrics {
  stock_balance: number;
  avg_margin_pct: number | null;
  purchase_freq_365d: number;
  last_purchase_days_ago: number | null;
}

export interface SkuSalesMetrics {
  total_qty: number;
  total_revenue: number;
  unique_customers: number;
  lifespan_days: number;
  trend_slope_pct_per_week: number | null;
}

export interface SkuAnalyticsData {
  ok: boolean;
  sales: SkuSalesMetrics;
  purchase: SkuPurchaseMetrics;
  customer_split: SkuCustomerSplit;
}

export interface ForecastBrief {
  quarter_mu: number;
  quarter_p98: number;
  computed_at: string | null;
  is_stale: boolean;
  stockout_weeks_excluded: number;
}

export interface HeatmapData {
  years: string[];
  matrix: Record<string, unknown>;
  max_qty: number;
}

export interface HoldingData {
  avg_days: number | null;
  n_pairs: number;
  oldest_held_days: number | null;
}

export interface PriceStats {
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  n: number;
}

export interface RestockSnapshot {
  master_sale_price_eur: number | null;
  sale_net_avg: number | null;
  retail_price_observed: number | null;
  retail_price_estimate: number | null;
  retail_qty_26w: number;
  last_purchase_unit_price: number | null;
  master_stock_price_eur: number | null;
  margin_pct: number | null;
  qty_total: number | null;
  inventory_sale_value_eur: number | null;
  inventory_cost_value_eur: number | null;
  weeks_of_cover: number | null;
  lifetime_invested_eur: number | null;
  lifetime_purchase_qty: number;
  lifetime_sale_revenue_eur: number;
  lifetime_sale_qty: number;
  realized_profit_eur: number | null;
  net_cashflow_eur: number | null;
  inventory_imbalance_pct: number | null;
  weekly_velocity: number;
  weekly_revenue: number;
  n_active_weeks_26w: number;
  last_purchase_days_ago: number | null;
  urgency_score: number | null;
  urgency_breakdown: UrgencyBreakdown | null;
}

export interface RetailSummary {
  qty: number;
  revenue: number;
  n_transactions: number;
  last_at: string | null;
  avg_ticket_qty: number | null;
}

export interface SkuExtras {
  return_qty: number;
  total_sale_qty_gross: number;
  return_rate_pct: number | null;
  price_stats: PriceStats;
  top_customers_cn: TopCustomer[];
  top_customers_foreign: TopCustomer[];
  retail_summary: RetailSummary;
  first_event_at: string | null;
  last_event_at: string | null;
  is_history_truncated: boolean;
}

export interface TopCustomer {
  customer_id: string | null;
  customer_type: string;
  customer_name: string | null;
  qty: number;
  last_at: string | null;
}

export interface UrgencyBreakdown {
  cover: number;
  recency: number;
  velocity: number;
  margin: number;
  demand_validity: number | null;
}

export interface SkuExtrasResponse {
  ok: boolean;
  extras: SkuExtras;
  holding: HoldingData;
  heatmap: HeatmapData;
  forecast: ForecastBrief | null;
  restock: RestockSnapshot | null;
}

export interface MonthlySale {
  month_start: string;
  sale_qty: number;
  retail_qty: number;
}

export interface TimelineWeek {
  week_start: string;
  sale_qty: number;
  purchase_unit_price: number | null;
  raw_unit_price_local: number | null;
  currency_local: string;
}

export interface SkuTimelineResponse {
  ok: boolean;
  timeline: TimelineWeek[];
  monthly_sales: MonthlySale[];
}
