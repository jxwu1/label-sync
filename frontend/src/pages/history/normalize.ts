import type {
  HistoryChange, HistoryCurrent, HistoryEvent, HistoryFuzzyMatch,
  HistoryLocSplit, HistorySearchData,
} from "../../api/types.gen";
import type { ChangeVM, CurrentVM, EventVM, FuzzyVM, HistoryResult, LocSplitVM } from "./types";

function arr(x: unknown): unknown[] { return Array.isArray(x) ? x : []; }
function str(x: unknown): string | null { return typeof x === "string" ? x : null; }
function num(x: unknown): number | null { return typeof x === "number" && Number.isFinite(x) ? x : null; }
function strList(x: unknown): string[] { return arr(x).filter((s): s is string => typeof s === "string"); }

function split(s: HistoryLocSplit | null | undefined): LocSplitVM | null {
  if (!s) return null;
  return { stores: strList(s.stores), warehouses: strList(s.warehouses), unknown: strList(s.unknown) };
}

function change(c: HistoryChange): ChangeVM {
  return { field: c.field, old: str(c.old), new: str(c.new), oldSplit: split(c.old_split), newSplit: split(c.new_split) };
}

function event(e: HistoryEvent): EventVM {
  return {
    at: e.at, changeType: str(e.change_type), source: str(e.source), summary: str(e.summary),
    changes: arr(e.changes).map((c) => change(c as HistoryChange)),
  };
}

function current(c: HistoryCurrent): CurrentVM {
  return {
    barcode: c.barcode, model: c.model,
    isTrulyDiscontinued: c.is_truly_discontinued === true,
    manualGrade: num(c.manual_grade),
    productNameZh: str(c.product_name_zh), productNameLocal: str(c.product_name_local),
    storeLocations: strList(c.store_locations), warehouseLocations: strList(c.warehouse_locations),
    unknownLocations: strList(c.unknown_locations),
    salePrice: num(c.sale_price), source: str(c.source), updatedAt: str(c.updated_at),
  };
}

/** API 边界唯一收窄点（HC-5）：组件只吃 HistoryResult，不碰 raw。 */
export function normalizeHistory(raw: HistorySearchData): HistoryResult {
  if (raw.found === true && raw.current) {
    return { kind: "hit", current: current(raw.current), events: arr(raw.events).map((e) => event(e as HistoryEvent)) };
  }
  const matches = arr(raw.fuzzy_matches);
  if (matches.length) {
    return {
      kind: "fuzzy",
      matches: matches.map((m): FuzzyVM => {
        const f = m as HistoryFuzzyMatch;
        return { barcode: f.barcode, model: f.model, location: str(f.location), isActive: f.is_active === true };
      }),
    };
  }
  return { kind: "notfound" };
}
