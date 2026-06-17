import type {
  SkuAnalyticsData, SkuCustomerEnd, SkuPurchaseMetrics, SkuSalesMetrics,
} from "../../api/types.gen";
import type { AnalyticsVM, CustomerEndVM, PurchaseVM, SalesVM } from "./analytics-types";

function num(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}
function str(x: unknown): string | null {
  return typeof x === "string" ? x : null;
}

function sales(s: SkuSalesMetrics): SalesVM {
  return {
    totalQty: num(s.total_qty) ?? 0,
    totalRevenue: num(s.total_revenue) ?? 0,
    uniqueCustomers: num(s.unique_customers) ?? 0,
    lifespanDays: num(s.lifespan_days) ?? 0,
    trendSlopePctPerWeek: num(s.trend_slope_pct_per_week),
  };
}
function purchase(p: SkuPurchaseMetrics): PurchaseVM {
  return {
    stockBalance: num(p.stock_balance) ?? 0,
    avgMarginPct: num(p.avg_margin_pct),
    purchaseFreq365d: num(p.purchase_freq_365d) ?? 0,
    lastPurchaseDaysAgo: num(p.last_purchase_days_ago),
  };
}
function end(c: SkuCustomerEnd): CustomerEndVM {
  return {
    qty: num(c.qty) ?? 0,
    uniqueCustomers: num(c.unique_customers) ?? 0,
    maxSingleQty: num(c.max_single_qty) ?? 0,
    lastAt: str(c.last_at),
    avgFreqPerMonth: num(c.avg_freq_per_month) ?? 0,
  };
}

/** API 边界唯一收窄点（HC-A5）：只收 sales/purchase/customer_split，不碰任何 2b 字段。 */
export function normalizeAnalytics(raw: SkuAnalyticsData): AnalyticsVM {
  return {
    sales: sales(raw.sales),
    purchase: purchase(raw.purchase),
    cn: end(raw.customer_split.cn),
    fo: end(raw.customer_split.fo),
  };
}
