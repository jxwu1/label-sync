export interface SalesVM {
  totalQty: number;
  totalRevenue: number;
  uniqueCustomers: number;
  lifespanDays: number;
  trendSlopePctPerWeek: number | null;
}
export interface PurchaseVM {
  stockBalance: number;
  avgMarginPct: number | null;
  purchaseFreq365d: number;
  lastPurchaseDaysAgo: number | null;
}
export interface CustomerEndVM {
  qty: number;
  uniqueCustomers: number;
  maxSingleQty: number;
  lastAt: string | null;
  avgFreqPerMonth: number;
}
export interface AnalyticsVM {
  sales: SalesVM;
  purchase: PurchaseVM;
  cn: CustomerEndVM;
  fo: CustomerEndVM;
}
