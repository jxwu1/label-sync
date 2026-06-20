import { THRESH } from "./constants";
import type { FilterState } from "./constants";
import type { FilterCtx } from "./filter";

export interface SupplierRow { supplier_id: string; count: number; hot_count: number; max: number; }

function aggregate(
  items: any[], fil: FilterState, ctx: FilterCtx,
  predicate: (it: any, f: FilterState, c: FilterCtx, o?: any) => boolean,
): Map<string, SupplierRow> {
  const pool = items.filter((it) => predicate(it, fil, ctx, { skipSupplier: true }));
  const byS = new Map<string, SupplierRow>();
  for (const it of pool) {
    if (!it.supplier_id || it.urgency_score == null) continue;
    const k = it.supplier_id;
    if (!byS.has(k)) byS.set(k, { supplier_id: k, count: 0, hot_count: 0, max: 0 });
    const e = byS.get(k)!;
    if (it.urgency_score >= THRESH.SUPPLIER_OVERVIEW_HOT) e.hot_count += 1;
    e.count += 1;
    if (it.urgency_score > e.max) e.max = it.urgency_score;
  }
  return byS;
}

export function supplierSummary(items: any[], fil: FilterState, ctx: FilterCtx, predicate: any): SupplierRow[] {
  return Array.from(aggregate(items, fil, ctx, predicate).values())
    .filter((s) => s.hot_count > 0)
    .sort((a, b) => b.hot_count - a.hot_count);
}

export function allSuppliersSummary(items: any[], fil: FilterState, ctx: FilterCtx, predicate: any): SupplierRow[] {
  return Array.from(aggregate(items, fil, ctx, predicate).values())
    .sort((a, b) => b.max - a.max);
}
