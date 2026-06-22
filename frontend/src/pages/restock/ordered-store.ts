import { THRESH } from "./constants";

export const LS_KEY_ORDERED = "restock_ordered_v1";

export function loadOrdered(): Record<string, { marked_at: string }> {
  try {
    const raw = localStorage.getItem(LS_KEY_ORDERED);
    if (!raw) return {};
    const data = JSON.parse(raw);
    const cutoff = Date.now() - THRESH.ORDERED_EXPIRY_DAYS * 86400000;
    const cleaned: Record<string, { marked_at: string }> = {};
    for (const [bc, v] of Object.entries<any>(data || {})) {
      if (v && v.marked_at && Date.parse(v.marked_at) >= cutoff) cleaned[bc] = v;
    }
    return cleaned;
  } catch {
    return {};
  }
}

export function saveOrdered(ordered: Record<string, unknown>): void {
  try { localStorage.setItem(LS_KEY_ORDERED, JSON.stringify(ordered)); } catch { /* quota */ }
}

export function autoClearOrderedByPurchase(
  ordered: Record<string, { marked_at: string }>, items: any[],
): boolean {
  let changed = false;
  for (const bc of Object.keys(ordered)) {
    const it = items.find((x) => x.barcode === bc);
    if (!it || !it.last_purchase_at) continue;
    const last = Date.parse(it.last_purchase_at);
    const marked = Date.parse(ordered[bc].marked_at);
    if (Number.isFinite(last) && last > marked) { delete ordered[bc]; changed = true; }
  }
  return changed;
}
