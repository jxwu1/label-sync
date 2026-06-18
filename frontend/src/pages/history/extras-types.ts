export interface PriceStatsVM {
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  n: number;
}
export interface TopCustomerVM {
  customerId: string | null;
  customerType: string;
  customerName: string | null;
  qty: number;
  lastAt: string | null;
}
export interface RetailSummaryVM {
  qty: number;
  revenue: number;
  nTransactions: number;
  lastAt: string | null;
  avgTicketQty: number | null;
}
export interface ExtrasVM {
  returnQty: number;
  totalSaleQtyGross: number;
  returnRatePct: number | null;
  priceStats: PriceStatsVM;
  topCustomersCn: TopCustomerVM[];
  topCustomersForeign: TopCustomerVM[];
  retailSummary: RetailSummaryVM;
  firstEventAt: string | null;
  lastEventAt: string | null;
  isHistoryTruncated: boolean;
}
export interface HoldingVM {
  avgDays: number | null;
  nPairs: number;
  oldestHeldDays: number | null;
}
export interface HeatmapVM {
  years: string[];
  matrix: Record<string, number[]>; // 每年恰 12 项
  maxQty: number;
}
export interface ForecastBriefVM {
  quarterMu: number;
  quarterP98: number;
  computedAt: string | null;
  isStale: boolean;
  stockoutWeeksExcluded: number;
}
export interface UrgencyBreakdownVM {
  cover: number;
  recency: number;
  velocity: number;
  margin: number;
  demandValidity: number | null;
}
export interface RestockVM {
  masterSalePriceEur: number | null;
  saleNetAvg: number | null;
  retailPriceObserved: number | null;
  retailPriceEstimate: number | null;
  retailQty26w: number;
  lastPurchaseUnitPrice: number | null;
  masterStockPriceEur: number | null;
  marginPct: number | null;
  qtyTotal: number | null;
  inventorySaleValueEur: number | null;
  inventoryCostValueEur: number | null;
  weeksOfCover: number | null;
  lifetimeInvestedEur: number | null;
  lifetimePurchaseQty: number;
  lifetimeSaleRevenueEur: number;
  lifetimeSaleQty: number;
  realizedProfitEur: number | null;
  netCashflowEur: number | null;
  inventoryImbalancePct: number | null;
  weeklyVelocity: number;
  weeklyRevenue: number;
  nActiveWeeks26w: number;
  lastPurchaseDaysAgo: number | null;
  urgencyScore: number | null;
  urgencyBreakdown: UrgencyBreakdownVM | null;
}
export interface ExtrasPageVM {
  extras: ExtrasVM;
  holding: HoldingVM;
  heatmap: HeatmapVM;
  forecast: ForecastBriefVM | null;
  restock: RestockVM | null;
}
