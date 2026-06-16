import type { BriefingData } from "../../api/types.gen";
import type {
  BriefingViewModel,
  DataHealthVM,
  FollowUpActionVM,
  FollowUpRow,
  OverstockVM,
  RestockActionVM,
  RestockActionRow,
  RestockRiskVM,
  ReviewActionVM,
  ReviewRow,
  SalesHealthVM,
  SalesStatus,
  StockoutImpactVM,
  StockoutSample,
  Unavailable,
} from "./types";

type Rec = Record<string, unknown>;
const NA: Unavailable = { available: false };

function rec(x: unknown): Rec | null {
  return x !== null && typeof x === "object" && !Array.isArray(x) ? (x as Rec) : null;
}
function okRec(x: unknown): Rec | null {
  const r = rec(x);
  return r && r.ok === true ? r : null;
}
function num(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}
function str(x: unknown): string | null {
  return typeof x === "string" ? x : null;
}
function arr(x: unknown): unknown[] {
  return Array.isArray(x) ? x : [];
}
function safe<T>(fn: () => T | Unavailable): T | Unavailable {
  try {
    return fn();
  } catch {
    return NA; // 硬验收 #2：任何 block 异常都不冒泡到整页
  }
}

const SALES_STATUS: SalesStatus[] = ["ok", "week_incomplete", "coverage_insufficient", "no_previous_week"];

function normSalesHealth(x: unknown): SalesHealthVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const status = r.status;
  if (typeof status !== "string" || !SALES_STATUS.includes(status as SalesStatus)) return NA;
  return {
    available: true,
    status: status as SalesStatus,
    deltaPct: num(r.delta_pct),
    currentQty: num(r.current_qty),
    previousQty: num(r.previous_qty),
    forecastNextTotal: num(r.forecast_next_total),
    modelBiasUnits: num(r.model_bias_units),
    coveredSkus: num(r.covered_skus) ?? 0,
  };
}

function normRestockRisk(x: unknown): RestockRiskVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  return { available: true, total: num(r.total) ?? 0, urgent: num(r.urgent) ?? 0 };
}

function normStockout(x: unknown): StockoutImpactVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const samples: StockoutSample[] = arr(r.samples).map((s) => {
    const sr = rec(s) ?? {};
    return {
      barcode: str(sr.barcode) ?? "",
      model: str(sr.model),
      zeroWeeks: num(sr.zero_weeks),
      qtyTotal: num(sr.qty_total),
    };
  });
  return { available: true, total: num(r.total) ?? 0, samples };
}

function normOverstock(x: unknown): OverstockVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const samples = arr(r.samples).map((s) => {
    const sr = rec(s) ?? {};
    return {
      barcode: str(sr.barcode) ?? "",
      model: str(sr.model),
      qtyTotal: num(sr.qty_total),
      costValueEur: num(sr.cost_value_eur),
    };
  });
  return {
    available: true,
    total: num(r.total) ?? 0,
    stockQty: num(r.stock_qty) ?? 0,
    costAvailable: r.cost_available === true,
    costedSkus: num(r.costed_skus) ?? 0,
    overstockValueEur: num(r.overstock_value_eur),
    samples,
  };
}

function normDataHealth(x: unknown): DataHealthVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  return {
    available: true,
    lastImportDate: str(r.last_import_date),
    daysSince: num(r.days_since),
    stale: r.stale === true,
    scrapeStale: r.scrape_stale === true,
    costCoveragePct: num(r.cost_coverage_pct),
  };
}

function normRestockAction(x: unknown): RestockActionVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const items: RestockActionRow[] = arr(r.items).map((i) => {
    const ir = rec(i) ?? {};
    return {
      barcode: str(ir.barcode) ?? "",
      model: str(ir.model),
      qtyTotal: num(ir.qty_total),
      weeklyVelocity: num(ir.weekly_velocity),
      restockQtyP50: num(ir.restock_qty_p50),
      weeksOfCover: num(ir.weeks_of_cover),
    };
  });
  return { available: true, items, total: num(r.total) ?? items.length };
}

function normFollowUp(x: unknown): FollowUpActionVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const states = ["overdue", "not_due", "unknown"];
  const items: FollowUpRow[] = arr(r.items).map((i) => {
    const ir = rec(i) ?? {};
    const st = str(ir.overdue_state);
    return {
      id: num(ir.id) ?? 0,
      supplierName: str(ir.supplier_name),
      orderDate: str(ir.order_date),
      totalQty: num(ir.total_qty),
      overdueDays: num(ir.overdue_days),
      overdueState: (st && states.includes(st) ? st : "unknown") as FollowUpRow["overdueState"],
    };
  });
  return { available: true, items, total: num(r.total) ?? items.length };
}

function normReview(x: unknown): ReviewActionVM | Unavailable {
  const r = okRec(x);
  if (!r) return NA;
  const items: ReviewRow[] = arr(r.items).map((i) => {
    const ir = rec(i) ?? {};
    return { kind: str(ir.kind) ?? "", count: num(ir.count) ?? 0 };
  });
  return { available: true, items, total: num(r.total) ?? items.length };
}

/** API 边界唯一收窄点（spec 硬验收 #1）。组件只吃返回的 BriefingViewModel，不碰 raw。 */
export function normalizeBriefing(raw: BriefingData): BriefingViewModel {
  const cards = rec(raw.cards) ?? {};
  const actions = rec(raw.actions) ?? {};
  return {
    dataWeek: str(raw.data_week),
    dataWeekComplete: raw.data_week_complete === true,
    salesHealth: safe(() => normSalesHealth(cards.sales_health)),
    restockRisk: safe(() => normRestockRisk(cards.restock_risk)),
    stockoutImpact: safe(() => normStockout(cards.stockout_impact)),
    overstockRisk: safe(() => normOverstock(cards.overstock_risk)),
    dataHealth: safe(() => normDataHealth(cards.data_health)),
    restockAction: safe(() => normRestockAction(actions.restock)),
    followUpAction: safe(() => normFollowUp(actions.follow_up)),
    reviewAction: safe(() => normReview(actions.review_anomalies)),
  };
}
