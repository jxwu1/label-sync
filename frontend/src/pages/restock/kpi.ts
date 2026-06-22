import type { FilterState } from "./constants";
import type { FilterCtx } from "./filter";

export interface Kpi { hot: number; watch: number; ok: number; spend: number; }

export function computeKpi(
  items: any[], fil: FilterState, ctx: FilterCtx,
  predicate: (it: any, f: FilterState, c: FilterCtx, o?: any) => boolean,
): Kpi {
  const pool = items.filter(
    (it) => !it.is_truly_discontinued && !it.is_new_item &&
      !(it.barcode in ctx.ordered) && !(it.barcode in ctx.suppressed),
  );
  const hot = pool.filter((it) => (it.urgency_score ?? -1) >= 70).length;
  const watch = pool.filter((it) => { const s = it.urgency_score ?? -1; return s >= 40 && s < 70; }).length;
  const ok = pool.filter((it) => { const s = it.urgency_score ?? -1; return s >= 0 && s < 40; }).length;
  let spend = 0;
  for (const it of items.filter((x) => predicate(x, fil, ctx))) {
    const qty = it.restock_qty_p50;
    const cost = it.last_purchase_unit_price ?? it.master_stock_price_eur;
    if (qty && cost) spend += qty * cost;
  }
  return { hot, watch, ok, spend };
}
