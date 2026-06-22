import { describe, it, expect } from "vitest";
import { filterPredicate, type FilterCtx } from "./filter";
import { applySort } from "./sort";
import { INITIAL_FILTER } from "./constants";

// 27k 行 filter + sort 端到端中位：宽松上限防回归（PR 记录实测中位）。
describe("perf", () => {
  it("27k filter+sort 中位 < 100ms", () => {
    const items = Array.from({ length: 27000 }, (_, i) => ({
      barcode: "b" + i, origin: "FOREIGN", supplier_id: "GR1",
      is_truly_discontinued: false, is_new_item: false,
      urgency_score: i % 100, weeks_of_cover: i % 10,
    }));
    const ctx: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set<string>() };
    const run = () =>
      applySort(
        items.filter((it) => filterPredicate(it, INITIAL_FILTER, ctx)),
        { key: "urgency_score", dir: "desc" },
      );
    for (let i = 0; i < 3; i++) run(); // 预热
    const ts: number[] = [];
    for (let i = 0; i < 20; i++) {
      const t = performance.now();
      run();
      ts.push(performance.now() - t);
    }
    ts.sort((a, b) => a - b);
    const median = ts[10];
    expect(median).toBeLessThan(100);
  });
});
