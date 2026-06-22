import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
vi.mock("../../stores/restockDetail", () => {
  const state: any = { entries: {}, cache: {}, errorMsg: {}, load: vi.fn() };
  return { useRestockDetailStore: () => state, __state: state };
});
import { mount } from "@vue/test-utils";
import RestockDrawer from "./RestockDrawer.vue";
import * as restockDetailStore from "../../stores/restockDetail";
const __state = (restockDetailStore as unknown as { __state: any }).__state;

const detail = () => ({
  barcode: "b1", master_sale_price_eur: 6, sale_net_avg: 5.8, retail_price_observed: 5.5,
  retail_price_estimate: 6.2, last_purchase_unit_price: 3, master_stock_price_eur: 3.2,
  margin_source: "purchase", margin_pct: 35, qty_total: 100, inventory_sale_value_eur: 600,
  inventory_cost_value_eur: 320, weeks_of_cover: 2, realized_profit_eur: 500,
  lifetime_invested_eur: 320, lifetime_purchase_qty: 60, lifetime_sale_revenue_eur: 800,
  lifetime_sale_qty: 70, net_cashflow_eur: 480, inventory_imbalance_pct: 12,
  is_history_truncated: false, first_event_at: "2021-07-01", total_qty: 700,
  n_active_weeks_26w: 18, weekly_velocity: 12.5, weekly_revenue: 80, retail_qty_26w: 3,
  retail_revenue_26w: 16.5, retail_share_26w: 0.04, urgency_score: 88.5,
  urgency_breakdown: { velocity: 25, cover: 28, recency: 8, margin: 22, demand_validity: 0.75, velocity_pctile: 0.83, margin_pctile: 0.61 },
});

beforeEach(() => {
  setActivePinia(createPinia());
  __state.entries = {}; __state.cache = {}; __state.errorMsg = {}; __state.load = vi.fn();
});

describe("RestockDrawer", () => {
  it("ready 渲染 5 段 + 无操作按钮", () => {
    __state.entries["b1"] = "ready"; __state.cache["b1"] = detail();
    const w = mount(RestockDrawer, { props: { barcode: "b1" } });
    expect(w.findAll(".rs-drawer-sec").length).toBe(5);
    expect(w.find(".rs-drawer-actions").exists()).toBe(false);
  });
  it("销售概况：累计批发 + per-week，不出现 ×26 外推", () => {
    __state.entries["b1"] = "ready"; __state.cache["b1"] = detail();
    const w = mount(RestockDrawer, { props: { barcode: "b1" } });
    const txt = w.text();
    expect(txt).toContain("累计批发");
    expect(txt).not.toContain("×26");
  });
  it("missing/error/loading 三态占位", () => {
    __state.entries["b1"] = "missing";
    let w = mount(RestockDrawer, { props: { barcode: "b1" } });
    expect(w.text()).toContain("无补货明细");
    __state.entries["b2"] = "error"; __state.errorMsg["b2"] = "boom";
    w = mount(RestockDrawer, { props: { barcode: "b2" } });
    expect(w.text()).toContain("明细加载失败");
    __state.entries["b3"] = "loading";
    w = mount(RestockDrawer, { props: { barcode: "b3" } });
    expect(w.text()).toContain("加载中");
  });
  it("onMounted 触发 load(barcode) 一次", () => {
    mount(RestockDrawer, { props: { barcode: "b9" } });
    expect(__state.load).toHaveBeenCalledTimes(1);
    expect(__state.load).toHaveBeenCalledWith("b9");
  });
});
