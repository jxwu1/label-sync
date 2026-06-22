import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import RestockTable from "./RestockTable.vue";

function rows(n: number): any[] {
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
  it("点可排序表头 emit sort-change(key)", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    w.find('[data-sort="qty_total"]').trigger("click");
    expect(w.emitted("sort-change")?.[0]).toEqual(["qty_total"]);
  });
  it("当前排序列显示方向指示（desc→↓），其余列无", () => {
    const w = mount(RestockTable, {
      props: { rows: rows(1), coverThreshold: 4, sort: { key: "margin_pct", dir: "desc" } },
    });
    expect(w.find('[data-sort="margin_pct"]').text()).toContain("↓");
    expect(w.find('[data-sort="qty_total"]').text()).not.toContain("↓");
    expect(w.find('[data-sort="margin_pct"]').classes()).toContain("rs-th-sort--active");
  });
  it("asc 显示 ↑", () => {
    const w = mount(RestockTable, {
      props: { rows: rows(1), coverThreshold: 4, sort: { key: "qty_total", dir: "asc" } },
    });
    expect(w.find('[data-sort="qty_total"]').text()).toContain("↑");
  });
  it("货号/供应商/盈亏/趋势/上次量 列不可排序（无 .rs-th-sort）", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    const sortableKeys = w.findAll("th.rs-th-sort").map((th) => th.attributes("data-sort"));
    // 9 可排序列恰好；不含 supplier/profit/spark/last_qty
    expect(sortableKeys.sort()).toEqual(
      ["last_purchase_days_ago", "margin_pct", "qty_total", "restock_qty_p50",
       "restock_qty_p98", "urgency_score", "weekly_revenue", "weekly_velocity", "weeks_of_cover"],
    );
  });
});
