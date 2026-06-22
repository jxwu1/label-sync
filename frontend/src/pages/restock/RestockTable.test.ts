import { describe, it, expect, vi } from "vitest";
import { mount } from "@vue/test-utils";
import RestockTable from "./RestockTable.vue";

vi.mock("../../stores/restockDetail", () => ({
  useRestockDetailStore: () => ({ entries: {}, cache: {}, errorMsg: {}, load: () => {} }),
}));

function rows(n: number): any[] {
  return Array.from({ length: n }, (_, i) => ({
    barcode: "b" + i, model: "M" + i, name_zh: "名" + i, origin: "FOREIGN",
    supplier_id: "GR1", urgency_score: 50, qty_total: 1, weeks_of_cover: 1,
    weekly_velocity: 1, weekly_revenue: 1, margin_pct: 20, weekly_qty_12w: new Array(12).fill(0),
    restock_qty_p50: 5, restock_qty_p98: 9, restock_source: "forecast:CrostonSBA",
    last_purchase_qty: 3, last_purchase_days_ago: 1,
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
  it("键盘可达：Enter/Space 触发排序，且 aria-sort 反映状态", async () => {
    const w = mount(RestockTable, {
      props: { rows: rows(1), coverThreshold: 4, sort: { key: "margin_pct", dir: "asc" } },
    });
    const th = w.find('[data-sort="qty_total"]');
    expect(th.attributes("tabindex")).toBe("0");
    expect(th.attributes("aria-sort")).toBe("none");
    await th.trigger("keydown", { key: "Enter" });
    expect(w.emitted("sort-change")?.[0]).toEqual(["qty_total"]);
    await th.trigger("keydown", { key: " " });
    expect(w.emitted("sort-change")?.[1]).toEqual(["qty_total"]);
    // 当前排序列 aria-sort 反映方向
    expect(w.find('[data-sort="margin_pct"]').attributes("aria-sort")).toBe("ascending");
  });
  it("P50/P98 表头去废弃 RL-1 公式（红线 A4：周分位×8），行单元格暴露 restock_source", () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4 } });
    for (const key of ["restock_qty_p50", "restock_qty_p98"]) {
      const t = w.find(`[data-sort="${key}"]`).attributes("title") || "";
      expect(t).not.toContain("8周");      // 禁「× 8周」RL-1 复发文案
      expect(t).not.toMatch(/[×x]\s*8/);   // 禁 ×8 / x8
      expect(t).not.toContain("× 8");
    }
    // 真实来源走行单元格（旧 restock.js:401 在 p50 td 上的 restock_source title）
    const recCells = w.findAll("tr.rs-row td.rs-rec-g");
    expect(recCells[0].attributes("title")).toBe("forecast:CrostonSBA"); // P50
    expect(recCells[1].attributes("title")).toBe("forecast:CrostonSBA"); // P98
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

  // Phase 2 Task 8: inline drawer expand tests
  it("点行非按钮区 emit toggle-expand", async () => {
    const w = mount(RestockTable, { props: { rows: rows(2), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" } } });
    await w.findAll("tr.rs-row")[0].find(".rs-model").trigger("click");
    expect(w.emitted("toggle-expand")?.[0]).toEqual(["b0"]);
  });
  it("命中 expandedBarcode 插 drawer 行（colspan=14，单行）", () => {
    const w = mount(RestockTable, { props: { rows: rows(3), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" }, expandedBarcode: "b1" } });
    const drawerRows = w.findAll("tr.rs-drawer-row");
    expect(drawerRows.length).toBe(1);
    expect(drawerRows[0].find("td").attributes("colspan")).toBe("14");
    expect(w.find('tr.rs-row[aria-expanded="true"]').exists()).toBe(true);
  });
  it("红队 click：点货号/供应商不 emit toggle-expand", async () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" } } });
    await w.find(".rs-bc-link").trigger("click");
    await w.find(".rs-supplier").trigger("click");
    expect(w.emitted("toggle-expand")).toBeUndefined();
  });
  it("红队 keydown：聚焦货号按 Enter 不展开（.self）；聚焦行 Enter 展开", async () => {
    const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" } } });
    await w.find(".rs-bc-link").trigger("keydown", { key: "Enter" });
    expect(w.emitted("toggle-expand")).toBeUndefined();
    await w.find("tr.rs-row").trigger("keydown.enter");
    expect(w.emitted("toggle-expand")?.[0]).toEqual(["b0"]);
  });
});
