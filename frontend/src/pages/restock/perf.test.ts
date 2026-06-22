import { describe, it, expect } from "vitest";
import { filterPredicate, type FilterCtx } from "./filter";
import { applySort } from "./sort";
import { INITIAL_FILTER } from "./constants";

// spec §8 line 218：新 filter+sort 纯计算中位 ≤ **旧移植参照中位 × 1.5**（相对阈值，
// 免机器依赖）。绝对 ms 会放行相对退化（审查红队：退化 1.4× 仍 <100ms 被错误放行）。
// 基线 = 旧 restock.js:285-340 算法的忠实内联移植（含旧 comparator av null→1 偏离）。

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

// ── 旧移植参照：忠实镜像旧 restock.js:285-330 filterPredicate **全部**分支
// （含 ordered/suppressed/supplier/search，与新模块同等工作量；否则比较不公平）──
function baselineFilter(
  it: Row, fil: typeof INITIAL_FILTER,
  ctx: { ordered: Record<string, unknown>; suppressed: Record<string, unknown> },
): boolean {
  const isOrdered = it.barcode in ctx.ordered;
  if (fil.show_ordered) return isOrdered;
  if (isOrdered) return false;
  const isSuppressed = it.barcode in ctx.suppressed;
  if (fil.band === "skipped") { if (!isSuppressed) return false; } else if (isSuppressed) return false;
  if (fil.origin && it.origin !== fil.origin) return false;
  if (fil.supplier && it.supplier_id !== fil.supplier) return false;
  if (fil.search) {
    const q = fil.search.toLowerCase();
    const hay = `${it.supplier_id ?? ""} ${it.barcode ?? ""} ${it.model ?? ""} ${it.name_zh ?? ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  const isActive = !it.is_truly_discontinued && !it.is_new_item;
  const viewMatch =
    (fil.views.active && isActive) || (fil.views.new && it.is_new_item) ||
    (fil.views.disc && it.is_truly_discontinued);
  if (!viewMatch) return false;
  const score = it.urgency_score ?? -1;
  switch (fil.band) {
    case "urgent": if (score < 70) return false; break;
    case "watch": if (score < 40 || score >= 70) return false; break;
    case "ok": if (score >= 40) return false; break;
    default: break;
  }
  if (fil.coverMax !== null && fil.views.active) {
    if (it.weeks_of_cover != null && it.weeks_of_cover > fil.coverMax) return false;
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

function median(fn: () => unknown, samples = 20): number {
  for (let i = 0; i < 3; i++) fn(); // 预热
  const ts: number[] = [];
  for (let i = 0; i < samples; i++) {
    const t = performance.now();
    fn();
    ts.push(performance.now() - t);
  }
  ts.sort((a, b) => a - b);
  return ts[Math.floor(samples / 2)];
}

describe("perf", () => {
  it("27k filter+sort 中位 ≤ 旧移植参照 × 1.5（相对阈值）", () => {
    const items = makeItems();
    const ctx: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set<string>() };
    const newRun = () =>
      applySort(items.filter((it) => filterPredicate(it, INITIAL_FILTER, ctx)),
        { key: "urgency_score", dir: "desc" });
    const baselineRun = () =>
      baselineSort(items.filter((it) => baselineFilter(it, INITIAL_FILTER, ctx)), "urgency_score", "desc");

    const baselineMedian = median(baselineRun);
    const newMedian = median(newRun);
    // 相对阈值；基线极快时给 0.5ms 地板免抖动除零
    expect(newMedian).toBeLessThanOrEqual(Math.max(baselineMedian, 0.5) * 1.5);
  });
});
