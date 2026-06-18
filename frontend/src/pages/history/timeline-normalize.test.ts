import { describe, it, expect } from "vitest";
import { normalizeTimeline } from "./timeline-normalize";
import type { SkuTimelineResponse } from "../../api/types.gen";

const raw: SkuTimelineResponse = {
  ok: true,
  timeline: [
    { week_start: "2024-01-01", sale_qty: 3, purchase_unit_price: 5.5, raw_unit_price_local: 42, currency_local: "RMB" },
    { week_start: "2024-01-08", sale_qty: 0, purchase_unit_price: null, raw_unit_price_local: null, currency_local: "RMB" },
  ],
  monthly_sales: [
    { month_start: "2024-01-01", sale_qty: 10, retail_qty: 2 },
    { month_start: "2024-02-01", sale_qty: -4, retail_qty: 0 },
  ],
} as unknown as SkuTimelineResponse;

describe("normalizeTimeline", () => {
  it("maps snake to camel, preserves nulls and negative", () => {
    const vm = normalizeTimeline(raw);
    expect(vm.weeks[0].purchaseUnitPrice).toBe(5.5);
    expect(vm.weeks[0].rawUnitPriceLocal).toBe(42);
    expect(vm.weeks[1].purchaseUnitPrice).toBeNull();
    expect(vm.monthlySales[1].saleQty).toBe(-4);
    expect(vm.weeks).toHaveLength(2);
    expect(vm.monthlySales).toHaveLength(2);
  });
});
