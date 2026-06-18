import type { SkuTimelineResponse } from "../../api/types.gen";
import type { TimelineVM } from "./timeline-types";

export function normalizeTimeline(raw: SkuTimelineResponse): TimelineVM {
  return {
    weeks: (raw.timeline ?? []).map((w) => ({
      weekStart: w.week_start,
      saleQty: w.sale_qty ?? 0,
      purchaseUnitPrice: w.purchase_unit_price ?? null,
      rawUnitPriceLocal: w.raw_unit_price_local ?? null,
      currencyLocal: w.currency_local,
    })),
    monthlySales: (raw.monthly_sales ?? []).map((m) => ({
      monthStart: m.month_start,
      saleQty: m.sale_qty ?? 0,
      retailQty: m.retail_qty ?? 0,
    })),
  };
}
