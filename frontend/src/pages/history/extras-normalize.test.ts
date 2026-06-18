import { describe, it, expect } from "vitest";
import { normalizeExtras } from "./extras-normalize";
import type { SkuExtrasResponse } from "../../api/types.gen";

const base: SkuExtrasResponse = {
  ok: true,
  extras: {
    return_qty: 2, total_sale_qty_gross: 100, return_rate_pct: 1.96,
    price_stats: { mean: 5.5, std: 0.2, min: 5, max: 6, n: 10 },
    top_customers_cn: [{ customer_id: "c1", customer_type: "chinese", customer_name: "张三", qty: 50, last_at: "2025-01-01" }],
    top_customers_foreign: [],
    retail_summary: { qty: 3, revenue: 30, n_transactions: 2, last_at: "2025-02-01", avg_ticket_qty: 1.5 },
    first_event_at: "2021-01-01", last_event_at: "2025-02-01", is_history_truncated: true,
  },
  holding: { avg_days: 30.5, n_pairs: 40, oldest_held_days: 90 },
  heatmap: { years: ["2025", "2026"], matrix: { "2025": Array(12).fill(0), "2026": Array(12).fill(0) }, max_qty: 0 },
  forecast: { quarter_mu: 13, quarter_p98: 26, computed_at: "2026-06-01", is_stale: false, stockout_weeks_excluded: 1 },
  restock: null,
} as unknown as SkuExtrasResponse;

describe("normalizeExtras", () => {
  it("maps snake_case to camelCase", () => {
    const vm = normalizeExtras(base);
    expect(vm.extras.returnRatePct).toBe(1.96);
    expect(vm.extras.topCustomersCn[0].customerName).toBe("张三");
    expect(vm.forecast?.stockoutWeeksExcluded).toBe(1);
    expect(vm.restock).toBeNull();
  });

  it("pads each heatmap year to exactly 12 months", () => {
    const raw = { ...base, heatmap: { years: ["2026"], matrix: { "2026": [1, 2, 3] }, max_qty: 3 } } as unknown as SkuExtrasResponse;
    const vm = normalizeExtras(raw);
    expect(vm.heatmap.matrix["2026"]).toHaveLength(12);
    expect(vm.heatmap.matrix["2026"].slice(3)).toEqual(Array(9).fill(0));
  });

  it("defaults maxQty to 0 when missing", () => {
    const raw = { ...base, heatmap: { years: [], matrix: {}, max_qty: undefined } } as unknown as SkuExtrasResponse;
    const vm = normalizeExtras(raw);
    expect(vm.heatmap.maxQty).toBe(0);
  });

  it("maps restock projection when present", () => {
    const raw = { ...base, restock: {
      master_sale_price_eur: 10, sale_net_avg: null, retail_price_observed: null,
      retail_price_estimate: null, retail_qty_26w: 0, last_purchase_unit_price: 5,
      master_stock_price_eur: null, margin_pct: 50, qty_total: 100,
      inventory_sale_value_eur: 1000, inventory_cost_value_eur: 500, weeks_of_cover: 8.5,
      lifetime_invested_eur: 500, lifetime_purchase_qty: 100, lifetime_sale_revenue_eur: 900,
      lifetime_sale_qty: 90, realized_profit_eur: 400, net_cashflow_eur: 400,
      inventory_imbalance_pct: 10, weekly_velocity: 2, weekly_revenue: 20,
      n_active_weeks_26w: 12, last_purchase_days_ago: 30, urgency_score: 75,
      urgency_breakdown: { cover: 20, recency: 5, velocity: 25, margin: 25, demand_validity: 1 },
    } } as unknown as SkuExtrasResponse;
    const vm = normalizeExtras(raw);
    expect(vm.restock?.weeksOfCover).toBe(8.5);
    expect(vm.restock?.urgencyBreakdown?.demandValidity).toBe(1);
    expect(vm.restock?.qtyTotal).toBe(100);
  });

  it("keeps qtyTotal null when backend sends null (not coerced to 0)", () => {
    const raw = { ...base, restock: {
      master_sale_price_eur: null, sale_net_avg: null, retail_price_observed: null,
      retail_price_estimate: null, retail_qty_26w: 0, last_purchase_unit_price: null,
      master_stock_price_eur: null, margin_pct: null, qty_total: null,
      inventory_sale_value_eur: null, inventory_cost_value_eur: null, weeks_of_cover: null,
      lifetime_invested_eur: null, lifetime_purchase_qty: 0, lifetime_sale_revenue_eur: 0,
      lifetime_sale_qty: 0, realized_profit_eur: null, net_cashflow_eur: null,
      inventory_imbalance_pct: null, weekly_velocity: 0, weekly_revenue: 0,
      n_active_weeks_26w: 0, last_purchase_days_ago: null, urgency_score: null,
      urgency_breakdown: null,
    } } as unknown as SkuExtrasResponse;
    const vm = normalizeExtras(raw);
    expect(vm.restock?.qtyTotal).toBeNull();
  });
});
