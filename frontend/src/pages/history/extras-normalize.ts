import type { SkuExtrasResponse, TopCustomer } from "../../api/types.gen";
import type {
  ExtrasPageVM, TopCustomerVM, ForecastBriefVM, RestockVM,
} from "./extras-types";

function num(v: number | null | undefined): number {
  return typeof v === "number" ? v : 0;
}

function topCustomers(rows: TopCustomer[]): TopCustomerVM[] {
  return (rows ?? []).map((c) => ({
    customerId: c.customer_id ?? null,
    customerType: c.customer_type,
    customerName: c.customer_name ?? null,
    qty: num(c.qty),
    lastAt: c.last_at ?? null,
  }));
}

export function normalizeExtras(raw: SkuExtrasResponse): ExtrasPageVM {
  const e = raw.extras;
  const ps = e.price_stats;
  const rs = e.retail_summary;
  const h = raw.holding;
  const hm = raw.heatmap;

  // HC-B4 纵深防御: 每年恰 12 项
  const matrix: Record<string, number[]> = {};
  for (const [year, months] of Object.entries((hm?.matrix ?? {}) as Record<string, number[]>)) {
    matrix[year] = Array.from({ length: 12 }, (_, i) => num((months as number[])[i]));
  }

  const fc: ForecastBriefVM | null = raw.forecast
    ? {
        quarterMu: num(raw.forecast.quarter_mu),
        quarterP98: num(raw.forecast.quarter_p98),
        computedAt: raw.forecast.computed_at ?? null,
        isStale: raw.forecast.is_stale,
        stockoutWeeksExcluded: num(raw.forecast.stockout_weeks_excluded),
      }
    : null;

  const r = raw.restock;
  const restock: RestockVM | null = r
    ? {
        masterSalePriceEur: r.master_sale_price_eur ?? null,
        saleNetAvg: r.sale_net_avg ?? null,
        retailPriceObserved: r.retail_price_observed ?? null,
        retailPriceEstimate: r.retail_price_estimate ?? null,
        retailQty26w: num(r.retail_qty_26w),
        lastPurchaseUnitPrice: r.last_purchase_unit_price ?? null,
        masterStockPriceEur: r.master_stock_price_eur ?? null,
        marginPct: r.margin_pct ?? null,
        qtyTotal: r.qty_total ?? null,
        inventorySaleValueEur: r.inventory_sale_value_eur ?? null,
        inventoryCostValueEur: r.inventory_cost_value_eur ?? null,
        weeksOfCover: r.weeks_of_cover ?? null,
        lifetimeInvestedEur: r.lifetime_invested_eur ?? null,
        lifetimePurchaseQty: num(r.lifetime_purchase_qty),
        lifetimeSaleRevenueEur: num(r.lifetime_sale_revenue_eur),
        lifetimeSaleQty: num(r.lifetime_sale_qty),
        realizedProfitEur: r.realized_profit_eur ?? null,
        netCashflowEur: r.net_cashflow_eur ?? null,
        inventoryImbalancePct: r.inventory_imbalance_pct ?? null,
        weeklyVelocity: num(r.weekly_velocity),
        weeklyRevenue: num(r.weekly_revenue),
        nActiveWeeks26w: num(r.n_active_weeks_26w),
        lastPurchaseDaysAgo: r.last_purchase_days_ago ?? null,
        urgencyScore: r.urgency_score ?? null,
        urgencyBreakdown: r.urgency_breakdown
          ? {
              cover: num(r.urgency_breakdown.cover),
              recency: num(r.urgency_breakdown.recency),
              velocity: num(r.urgency_breakdown.velocity),
              margin: num(r.urgency_breakdown.margin),
              demandValidity: r.urgency_breakdown.demand_validity ?? null,
            }
          : null,
      }
    : null;

  return {
    extras: {
      returnQty: num(e.return_qty),
      totalSaleQtyGross: num(e.total_sale_qty_gross),
      returnRatePct: e.return_rate_pct ?? null,
      priceStats: {
        mean: ps.mean ?? null, std: ps.std ?? null,
        min: ps.min ?? null, max: ps.max ?? null, n: num(ps.n),
      },
      topCustomersCn: topCustomers(e.top_customers_cn),
      topCustomersForeign: topCustomers(e.top_customers_foreign),
      retailSummary: {
        qty: num(rs.qty), revenue: num(rs.revenue),
        nTransactions: num(rs.n_transactions),
        lastAt: rs.last_at ?? null, avgTicketQty: rs.avg_ticket_qty ?? null,
      },
      firstEventAt: e.first_event_at ?? null,
      lastEventAt: e.last_event_at ?? null,
      isHistoryTruncated: e.is_history_truncated,
    },
    holding: { avgDays: h.avg_days ?? null, nPairs: num(h.n_pairs), oldestHeldDays: h.oldest_held_days ?? null },
    heatmap: { years: hm?.years ?? [], matrix, maxQty: num(hm?.max_qty) },
    forecast: fc,
    restock,
  };
}
