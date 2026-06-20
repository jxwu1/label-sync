import { describe, it, expect } from "vitest";
import { supplierSummary, allSuppliersSummary } from "./supplier-summary";
import { filterPredicate, type FilterCtx } from "./filter";
import { INITIAL_FILTER } from "./constants";

const ctx: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set() };
function it_(p: any) {
  return { barcode: "b" + Math.random(), is_truly_discontinued: false, is_new_item: false,
    weeks_of_cover: 1, ...p };
}

describe("supplier-summary", () => {
  it("红队：origin=FOREIGN 时 CN 供应商不漏出", () => {
    const items = [
      it_({ origin: "FOREIGN", supplier_id: "GR1", urgency_score: 90 }),
      it_({ origin: "CN", supplier_id: "CN9", urgency_score: 95 }),
    ];
    const hot = supplierSummary(items, { ...INITIAL_FILTER, origin: "FOREIGN" }, ctx, filterPredicate);
    expect(hot.map((s) => s.supplier_id)).toEqual(["GR1"]);
    expect(hot.find((s) => s.supplier_id === "CN9")).toBeUndefined();
  });
  it("折叠按 hot_count desc；展开按 max desc 全量", () => {
    const items = [
      it_({ origin: "FOREIGN", supplier_id: "A", urgency_score: 90 }),
      it_({ origin: "FOREIGN", supplier_id: "A", urgency_score: 80 }),
      it_({ origin: "FOREIGN", supplier_id: "B", urgency_score: 60 }),
    ];
    const hot = supplierSummary(items, { ...INITIAL_FILTER, origin: "FOREIGN" }, ctx, filterPredicate);
    expect(hot[0].supplier_id).toBe("A");
    const all = allSuppliersSummary(items, { ...INITIAL_FILTER, origin: "FOREIGN" }, ctx, filterPredicate);
    expect(all.map((s) => s.supplier_id)).toEqual(["A", "B"]);
  });
});
