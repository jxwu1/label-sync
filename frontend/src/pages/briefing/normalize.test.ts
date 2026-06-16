import { describe, expect, it } from "vitest";
import type { BriefingData } from "../../api/types.gen";
import { normalizeBriefing } from "./normalize";

function raw(over: Partial<BriefingData> = {}): BriefingData {
  return {
    ok: true,
    generated_at: "2026-06-12T09:00:00",
    data_week: "2026-06-08",
    data_week_complete: true,
    cards: {
      sales_health: { ok: true, status: "ok", delta_pct: 12, current_qty: 4715, previous_qty: 4210, forecast_next_p50: 380, model_bias_units: 6, covered_skus: 42 },
      restock_risk: { ok: true, total: 38, urgent: 12 },
      stockout_impact: { ok: true, total: 12, samples: [{ barcode: "5828079342495", model: "34249", zero_weeks: 3, qty_total: 0 }] },
      overstock_risk: { ok: true, total: 396, stock_qty: 124991, cost_available: true, costed_skus: 392, overstock_value_eur: 83382.82, samples: [{ barcode: "5828079342495", model: "34249", qty_total: 4884, cost_value_eur: 2176.8 }] },
      data_health: { ok: true, last_import_date: "2026-06-15", days_since: 0, stale: false, scrape_stale: false, cost_coverage_pct: 59 },
    },
    actions: {
      restock: { ok: true, total: 38, items: [{ barcode: "5828079342495", model: "34249", qty_total: 4884, weekly_velocity: 50, restock_qty_p50: 120, weeks_of_cover: 2.1 }] },
      follow_up: { ok: true, status: "ok", total: 2, items: [{ id: 7, supplier_name: "供应商A", supplier_id: "A", order_date: "2026-06-01", total_qty: 500, overdue_days: 5, overdue_state: "overdue" }] },
      review_anomalies: { ok: true, total: 3, items: [{ kind: "条码超长", count: 7, samples: ["5828"] }] },
    },
    ...over,
  } as BriefingData;
}

describe("normalizeBriefing", () => {
  it("正常 payload → 各 block available", () => {
    const vm = normalizeBriefing(raw());
    expect(vm.dataWeek).toBe("2026-06-08");
    expect(vm.salesHealth).toMatchObject({ available: true, status: "ok", deltaPct: 12 });
    expect(vm.restockRisk).toMatchObject({ available: true, total: 38, urgent: 12 });
    expect(vm.overstockRisk).toMatchObject({ available: true, costAvailable: true, overstockValueEur: 83382.82 });
    expect(vm.restockAction).toMatchObject({ available: true, total: 38 });
    if (vm.restockAction.available) expect(vm.restockAction.items[0].weeksOfCover).toBe(2.1);
  });

  it("block ok:false → 该 block Unavailable，其余正常（不 throw）", () => {
    const r = raw();
    r.cards.restock_risk = { ok: false, error: "boom" };
    const vm = normalizeBriefing(r);
    expect(vm.restockRisk.available).toBe(false);
    expect(vm.salesHealth.available).toBe(true);
  });

  it("malformed / 缺字段 block → Unavailable（不 throw）", () => {
    const r = raw();
    // @ts-expect-error 故意塞坏数据
    r.cards.sales_health = "not-an-object";
    r.cards.data_health = { ok: true };
    const vm = normalizeBriefing(r);
    expect(vm.salesHealth.available).toBe(false);
    // data_health 无 status 要求，缺字段降级为 null 而非 unavailable
    expect(vm.dataHealth.available).toBe(true);
    if (vm.dataHealth.available) expect(vm.dataHealth.daysSince).toBeNull();
  });

  it("sales_health 非法 status → Unavailable", () => {
    const r = raw();
    r.cards.sales_health = { ok: true, status: "weird" };
    expect(normalizeBriefing(r).salesHealth.available).toBe(false);
  });

  it("压货 cost_available:false → overstockValueEur 为 null", () => {
    const r = raw();
    r.cards.overstock_risk = { ok: true, total: 396, stock_qty: 124991, cost_available: false, costed_skus: 0, overstock_value_eur: null, samples: [] };
    const vm = normalizeBriefing(r);
    if (vm.overstockRisk.available) {
      expect(vm.overstockRisk.costAvailable).toBe(false);
      expect(vm.overstockRisk.overstockValueEur).toBeNull();
    }
  });

  it("空库 data_week:null → dataWeek null，不 throw", () => {
    const vm = normalizeBriefing(raw({ data_week: null, data_week_complete: false }));
    expect(vm.dataWeek).toBeNull();
  });
});
