export interface LocSplitVM { stores: string[]; warehouses: string[]; unknown: string[]; }
export interface ChangeVM {
  field: string;
  old: string | null;
  new: string | null;
  oldSplit: LocSplitVM | null;
  newSplit: LocSplitVM | null;
}
export interface EventVM {
  at: string;
  changeType: string | null;
  source: string | null;
  summary: string | null;
  changes: ChangeVM[];
}
// CurrentVM 仅暴露 Phase 1 UI 字段（HC-6：schema 校验完整 raw，VM 只取所需）
export interface CurrentVM {
  barcode: string;
  model: string;
  isTrulyDiscontinued: boolean;
  manualGrade: number | null;
  productNameZh: string | null;
  productNameLocal: string | null;
  storeLocations: string[];
  warehouseLocations: string[];
  unknownLocations: string[];
  salePrice: number | null;
  source: string | null;
  updatedAt: string | null;
}
export interface FuzzyVM { barcode: string; model: string; location: string | null; isActive: boolean; }
export type HistoryResult =
  | { kind: "notfound" }
  | { kind: "fuzzy"; matches: FuzzyVM[] }
  | { kind: "hit"; current: CurrentVM; events: EventVM[] };
