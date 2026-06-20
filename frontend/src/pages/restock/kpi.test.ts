import { describe, it, expect } from "vitest";
import { computeKpi } from "./kpi";
import { filterPredicate, type FilterCtx } from "./filter";
import { INITIAL_FILTER } from "./constants";

const ctx: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set() };
function it_(p: any = {}) {
  return { barcode: "b" + Math.random(), is_truly_discontinued: false, is_new_item: false,
    urgency_score: 80, restock_qty_p50: 10, last_purchase_unit_price: 2,
    master_stock_price_eur: 1, origin: "FOREIGN", weeks_of_cover: 1, ...p };
}

describe("computeKpi", () => {
  it("分档计数 + 充足排除 null", () => {
    const items = [it_({ urgency_score: 80 }), it_({ urgency_score: 50 }),
                   it_({ urgency_score: 10 }), it_({ urgency_score: null })];
    const k = computeKpi(items, INITIAL_FILTER, ctx, filterPredicate);
    expect(k.hot).toBe(1); expect(k.watch).toBe(1); expect(k.ok).toBe(1);
  });
  it("spend = Σ可见 p50×(last_pp ?? master_pp)", () => {
    const k = computeKpi([it_({ restock_qty_p50: 10, last_purchase_unit_price: 2 })],
      INITIAL_FILTER, ctx, filterPredicate);
    expect(k.spend).toBe(20);
  });
});
