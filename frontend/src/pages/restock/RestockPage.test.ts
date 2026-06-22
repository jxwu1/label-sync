import { describe, it, expect, vi, beforeEach } from "vitest";
vi.mock("../../api/client", () => ({
  apiGet: vi.fn(), UnauthenticatedError: class extends Error {},
}));
vi.mock("../../stores/restockDetail", () => ({
  useRestockDetailStore: () => ({ entries: {}, cache: {}, errorMsg: {}, load: () => {} }),
}));
import { mount, flushPromises } from "@vue/test-utils";
import { apiGet, UnauthenticatedError } from "../../api/client";
import RestockPage from "./RestockPage.vue";
import { INITIAL_FILTER } from "./constants";

const item = (p: any) => ({ barcode: "b" + Math.random(), model: "M", name_zh: "n",
  origin: "FOREIGN", supplier_id: "GR1", is_truly_discontinued: false, is_new_item: false,
  qty_total: 1, weeks_of_cover: 8, weekly_velocity: 1, weekly_revenue: 1, margin_pct: 20,
  master_stock_price_eur: 1, master_sale_price_eur: 2, last_purchase_unit_price: 1, sale_net_avg: 1,
  margin_source: null, margin_price_source: null, weekly_qty_12w: new Array(12).fill(0),
  trend_slope_pct_per_week: 0, realized_profit_eur: 1, inventory_cost_value_eur: 1,
  last_purchase_days_ago: 1, last_purchase_at: null, restock_qty_p50: 5, restock_qty_p98: 9,
  restock_source: "x", last_purchase_qty: 3, urgency_score: 90, stockout_zero_weeks_last8: 0, ...p });

beforeEach(() => { vi.mocked(apiGet).mockReset(); localStorage.clear(); });

describe("RestockPage", () => {
  it("红队：点供应商清 coverMax，weeks_of_cover=8 行可见", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path === "/api/restock/items") return { ok: true, total: 1, items: [item({ weeks_of_cover: 8 })] } as any;
      return { ok: true, items: {} } as any;
    });
    const w = mount(RestockPage);
    await flushPromises();
    expect(w.findAll("tr.rs-row").length).toBe(0);
    w.findComponent({ name: "SupplierOverview" }).vm.$emit("select-supplier", "GR1");
    await flushPromises();
    expect(w.findAll("tr.rs-row").length).toBe(1);
  });

  it("点表头排序：异列→desc 重排，再点同列→asc 翻转", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path === "/api/restock/items") return {
        ok: true, total: 3,
        items: [
          item({ barcode: "lo", qty_total: 10, weeks_of_cover: 1, urgency_score: 50 }),
          item({ barcode: "hi", qty_total: 99, weeks_of_cover: 1, urgency_score: 50 }),
          item({ barcode: "mid", qty_total: 50, weeks_of_cover: 1, urgency_score: 50 }),
        ],
      } as any;
      return { ok: true, items: {} } as any;
    });
    const w = mount(RestockPage);
    await flushPromises();
    const codes = () => w.findAll("tr.rs-row .rs-bc-link").map((b) => b.text());

    // 点「库存」表头 → qty_total desc：99,50,10
    await w.find('[data-sort="qty_total"]').trigger("click");
    await flushPromises();
    expect(codes()).toEqual(["hi", "mid", "lo"]);
    expect(w.find('[data-sort="qty_total"]').text()).toContain("↓");

    // 再点同列 → asc 翻转：10,50,99
    await w.find('[data-sort="qty_total"]').trigger("click");
    await flushPromises();
    expect(codes()).toEqual(["lo", "mid", "hi"]);
    expect(w.find('[data-sort="qty_total"]').text()).toContain("↑");
  });

  it("401 中性态：apiGet 抛 UnauthenticatedError → 中性「加载中…」，非业务错误/空态", async () => {
    vi.mocked(apiGet).mockRejectedValue(new UnauthenticatedError("unauth"));
    const w = mount(RestockPage);
    await flushPromises();
    // client 已跳登录；页面停在中性占位，不显业务「加载失败」，不渲染行/空态
    expect(w.text()).toContain("加载中…");
    expect(w.text()).not.toContain("加载失败");
    expect(w.findAll("tr.rs-row").length).toBe(0);
  });

  it("点行展开 drawer 行；再点收起", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path === "/api/restock/items") return { ok: true, total: 2, items: [item({ barcode: "x", weeks_of_cover: 1 }), item({ barcode: "y", weeks_of_cover: 1 })] } as any;
      return { ok: true, items: {} } as any;
    });
    const w = mount(RestockPage);
    await flushPromises();
    await w.findAll("tr.rs-row")[0].trigger("click");
    await flushPromises();
    expect(w.findAll("tr.rs-drawer-row").length).toBe(1);
    await w.findAll("tr.rs-row")[0].trigger("click"); // 同行收起
    await flushPromises();
    expect(w.findAll("tr.rs-drawer-row").length).toBe(0);
  });

  it("筛选变化收起已展开行", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path === "/api/restock/items") return { ok: true, total: 1, items: [item({ barcode: "x", weeks_of_cover: 1 })] } as any;
      return { ok: true, items: {} } as any;
    });
    const w = mount(RestockPage);
    await flushPromises();
    await w.findAll("tr.rs-row")[0].trigger("click");
    await flushPromises();
    expect(w.findAll("tr.rs-drawer-row").length).toBe(1);
    // 触发筛选变化（FilterBar emit update）→ 收起
    w.findComponent({ name: "FilterBar" }).vm.$emit("update", { ...INITIAL_FILTER, search: "changed" });
    await flushPromises();
    expect(w.findAll("tr.rs-drawer-row").length).toBe(0);
  });

  it("排序变化收起已展开行", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path === "/api/restock/items") return { ok: true, total: 1, items: [item({ barcode: "x", weeks_of_cover: 1 })] } as any;
      return { ok: true, items: {} } as any;
    });
    const w = mount(RestockPage);
    await flushPromises();
    await w.findAll("tr.rs-row")[0].trigger("click");
    await flushPromises();
    expect(w.findAll("tr.rs-drawer-row").length).toBe(1);
    // 点表头排序列 → onSortChange 收起
    await w.find('[data-sort="qty_total"]').trigger("click");
    await flushPromises();
    expect(w.findAll("tr.rs-drawer-row").length).toBe(0);
  });
});
