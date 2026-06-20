import type { FilterState } from "./constants";

export interface FilterCtx {
  ordered: Record<string, unknown>;
  suppressed: Record<string, unknown>;
  selected: Set<string>;
}

export function filterPredicate(
  it: any, fil: FilterState, ctx: FilterCtx, opts: { skipSupplier?: boolean } = {},
): boolean {
  const isOrdered = it.barcode in ctx.ordered;
  if (fil.show_ordered) return isOrdered;
  if (isOrdered) return false;

  const isSuppressed = it.barcode in ctx.suppressed;
  if (fil.band === "skipped") {
    if (!isSuppressed) return false;
  } else if (isSuppressed) {
    return false;
  }
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
