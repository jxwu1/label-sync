import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import RestockTable from "./RestockTable.vue";

function rows(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    barcode: "b" + i, model: "M" + i, name_zh: "名" + i, origin: "FOREIGN",
    supplier_id: "GR1", urgency_score: 50, qty_total: 1, weeks_of_cover: 1,
    weekly_velocity: 1, weekly_revenue: 1, margin_pct: 20, weekly_qty_12w: new Array(12).fill(0),
    restock_qty_p50: 5, restock_qty_p98: 9, last_purchase_qty: 3, last_purchase_days_ago: 1,
    realized_profit_eur: 1, inventory_cost_value_eur: 1, stockout_zero_weeks_last8: 0,
    is_truly_discontinued: false, is_new_item: false, trend_slope_pct_per_week: 0,
  }));
}

describe("RestockTable", () => {
  it("最多渲染 500 行", () => {
    const w = mount(RestockTable, { props: { rows: rows(600), coverThreshold: 4 } });
    expect(w.findAll("tr.rs-row").length).toBe(500);
  });
  it("p98 列是文本非 input", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    expect(w.find(".rs-qty-input").exists()).toBe(false);
  });
  it("点货号 emit open-history", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    w.find(".rs-bc-link").trigger("click");
    expect(w.emitted("open-history")?.[0]).toEqual(["b0"]);
  });
  it("点供应商 emit select-supplier", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    w.find(".rs-supplier").trigger("click");
    expect(w.emitted("select-supplier")?.[0]).toEqual(["GR1"]);
  });
});
