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
