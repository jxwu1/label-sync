export interface Unavailable {
  available: false;
}

export type SalesStatus = "ok" | "week_incomplete" | "coverage_insufficient" | "no_previous_week";

export interface SalesHealthVM {
  available: true;
  status: SalesStatus;
  deltaPct: number | null;
  currentQty: number | null;
  previousQty: number | null;
  forecastNextP50: number | null;
  modelBiasUnits: number | null;
  coveredSkus: number;
}
export interface RestockRiskVM {
  available: true;
  total: number;
  urgent: number;
}
export interface StockoutSample {
  barcode: string;
  model: string | null;
  zeroWeeks: number | null;
  qtyTotal: number | null;
}
export interface StockoutImpactVM {
  available: true;
  total: number;
  samples: StockoutSample[];
}
export interface OverstockSample {
  barcode: string;
  model: string | null;
  qtyTotal: number | null;
  costValueEur: number | null;
}
export interface OverstockVM {
  available: true;
  total: number;
  stockQty: number;
  costAvailable: boolean;
  costedSkus: number;
  overstockValueEur: number | null;
  samples: OverstockSample[];
}
export interface DataHealthVM {
  available: true;
  lastImportDate: string | null;
  daysSince: number | null;
  stale: boolean;
  scrapeStale: boolean;
  costCoveragePct: number | null;
}
export interface RestockActionRow {
  barcode: string;
  model: string | null;
  qtyTotal: number | null;
  weeklyVelocity: number | null;
  restockQtyP50: number | null;
  weeksOfCover: number | null;
}
export interface RestockActionVM {
  available: true;
  items: RestockActionRow[];
  total: number;
}
export interface FollowUpRow {
  id: number;
  supplierName: string | null;
  orderDate: string | null;
  totalQty: number | null;
  overdueDays: number | null;
  overdueState: "overdue" | "not_due" | "unknown";
}
export interface FollowUpActionVM {
  available: true;
  items: FollowUpRow[];
  total: number;
}
export interface ReviewRow {
  kind: string;
  count: number;
}
export interface ReviewActionVM {
  available: true;
  items: ReviewRow[];
  total: number;
}

export interface BriefingViewModel {
  dataWeek: string | null;
  dataWeekComplete: boolean;
  salesHealth: SalesHealthVM | Unavailable;
  restockRisk: RestockRiskVM | Unavailable;
  stockoutImpact: StockoutImpactVM | Unavailable;
  overstockRisk: OverstockVM | Unavailable;
  dataHealth: DataHealthVM | Unavailable;
  restockAction: RestockActionVM | Unavailable;
  followUpAction: FollowUpActionVM | Unavailable;
  reviewAction: ReviewActionVM | Unavailable;
}
