import { describe, it, expect } from "vitest";
import { filterPredicate, type FilterCtx } from "./filter";
import { applySort } from "./sort";
import { INITIAL_FILTER, type FilterState } from "./constants";

// spec §8 line 218：新 filter+sort 纯计算中位 ≤ **旧移植参照中位 × 1.5**（相对阈值）。
// 可靠性要点（第2轮审查）：
//  ① 基线必须忠实复刻旧 restock.js:285-340 _filterPredicate 的【全部分支 + opts 签名】，
//     否则基线工作量偏低→比值虚高→在 1.5× 边界 flaky。
//  ② 新/旧【交错采样】（同一轮先新后旧），消运行顺序 / JIT 预热 / GC 漂移的系统性偏差。
// 两者同算法，交错后比值≈1.0，1.5× 留 50% 余量 → 稳定。

interface Row {
  barcode: string; model: string; name_zh: string; origin: string; supplier_id: string;
  is_truly_discontinued: boolean; is_new_item: boolean;
  urgency_score: number | null; weeks_of_cover: number | null;
}

function makeItems(): Row[] {
  return Array.from({ length: 27000 }, (_, i) => ({
    barcode: "b" + i, model: "M" + i, name_zh: "名" + i, origin: "FOREIGN", supplier_id: "GR1",
    is_truly_discontinued: false, is_new_item: false,
    urgency_score: i % 100, weeks_of_cover: i % 10,
  }));
}

// ── 旧移植参照：逐分支忠实复刻 restock.js:285-330 _filterPredicate（含 opts={} 签名、
//    skipSupplier 守卫、flagged band、search hay、精确 null 守卫）──
function baselineFilter(
  it: Row, fil: FilterState, ctx: FilterCtx, opts: { skipSupplier?: boolean } = {},
): boolean {
  const isOrdered = it.barcode in ctx.ordered;
  if (fil.show_ordered) { return isOrdered; }
  if (isOrdered) return false;
  const isSuppressed = it.barcode in ctx.suppressed;
  if (fil.band === "skipped") { if (!isSuppressed) return false; } else if (isSuppressed) return false;
  if (fil.origin && it.origin !== fil.origin) return false;
  if (!opts.skipSupplier && fil.supplier && it.supplier_id !== fil.supplier) return false;
  if (fil.search) {
    const q = fil.search.toLowerCase();
    const hay = `${it.supplier_id ?? ""} ${it.barcode ?? ""} ${it.model ?? ""} ${it.name_zh ?? ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  const vw = fil.views;
  const isActive = !it.is_truly_discontinued && !it.is_new_item;
  const viewMatch =
    (vw.active && isActive) || (vw.new && it.is_new_item) || (vw.disc && it.is_truly_discontinued);
  if (!viewMatch) return false;
  const score = it.urgency_score ?? -1;
  switch (fil.band) {
    case "urgent": if (score < 70) return false; break;
    case "watch": if (score < 40 || score >= 70) return false; break;
    case "ok": if (score >= 40) return false; break;
    case "flagged": if (!ctx.selected.has(it.barcode)) return false; break;
    default: break;
  }
  if (fil.coverMax !== null && vw.active) {
    if (it.weeks_of_cover !== null && it.weeks_of_cover !== undefined && it.weeks_of_cover > fil.coverMax) {
      return false;
    }
  }
  return true;
}
function baselineSort(items: Row[], key: keyof Row, dir: "asc" | "desc"): Row[] {
  const mul = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = a[key], bv = b[key];
    if (av === null || av === undefined) return 1; // 旧 comparator 偏离（无视 b）
    if (bv === null || bv === undefined) return -1;
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
}

function med(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

describe("perf", () => {
  it("27k filter+sort 中位 ≤ 旧移植参照 × 1.5（忠实基线 + 交错采样）", () => {
    const items = makeItems();
    const ctx: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set<string>() };
    const newRun = () =>
      applySort(items.filter((x) => filterPredicate(x, INITIAL_FILTER, ctx)),
        { key: "urgency_score", dir: "desc" });
    const baseRun = () =>
      baselineSort(items.filter((x) => baselineFilter(x, INITIAL_FILTER, ctx)), "urgency_score", "desc");

    // 预热双方（JIT 稳态）
    for (let i = 0; i < 5; i++) { newRun(); baseRun(); }

    // 交错采样：每轮先新后旧 → 任何单调漂移（GC / 频率调节）对两者等量作用
    const N = 40;
    const newTimes: number[] = [], baseTimes: number[] = [];
    for (let i = 0; i < N; i++) {
      let t = performance.now(); newRun(); newTimes.push(performance.now() - t);
      t = performance.now(); baseRun(); baseTimes.push(performance.now() - t);
    }
    const newMed = med(newTimes);
    const baseMed = med(baseTimes);
    // 基线极快时给 0.5ms 地板，免除零 / 抖动放大
    expect(newMed).toBeLessThanOrEqual(Math.max(baseMed, 0.5) * 1.5);
  });
});
