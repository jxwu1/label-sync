import type { RestockDetailUrgencyBreakdown } from "../../api/types.gen";

// drawer 盈亏状态档（restock.js:430-446）。亏损档标签 = "账面亏损"（旧 drawer:444 原文），
// 与 cells.ts profitBadge 的行内 "未回本"（restock.js:282）有意不同——旧页两处本就异文案，1:1 保留。
export function profitStatus(
  rp: number | null | undefined, inv: number | null | undefined,
): { cls: string; label: string } {
  if (rp === null || rp === undefined) return { cls: "unknown", label: "缺成本" };
  const i = inv ?? 0;
  if (rp > 0) return { cls: "good", label: "已回本" };
  if (rp + i > 0) return { cls: "mid", label: "压货中" };
  return { cls: "bad", label: "账面亏损" };
}

export function retailPriceLine(
  observed: number | null | undefined, estimate: number | null | undefined,
  retailQty26w: number,
): { kind: "both" | "observed" | "estimate" | "none"; observed: number | null; estimate: number | null; qty: number } {
  const o = observed ?? null;
  const e = estimate ?? null;
  const kind = o != null && e != null ? "both" : o != null ? "observed" : e != null ? "estimate" : "none";
  return { kind, observed: o, estimate: e, qty: retailQty26w };
}

export function cashflowImbalance(imb: number | null | undefined): { warn: boolean; pct: number | null } {
  return { warn: imb != null && imb > 30, pct: imb ?? null };
}

export function scoreSegments(bd: RestockDetailUrgencyBreakdown): Array<{
  val: number; max: number; cls: string; label: string; widthPct: number; fillPct: number;
}> {
  const defs = [
    { val: bd.velocity, max: 30, cls: "v", label: `销额 ${bd.velocity}/30` },
    { val: bd.cover, max: 30, cls: "c", label: `库存 ${bd.cover}/30` },
    { val: bd.recency, max: 10, cls: "r", label: `距进货 ${bd.recency}/10` },
    { val: bd.margin, max: 30, cls: "m", label: `毛利 ${bd.margin}/30` },
  ];
  // widthPct = 各维满分（销30/库30/距10/利30），四者恰好和为 100 → 直接当百分比段宽用。
  // 若未来改评分权重使其不再和为 100，此处需改为按总分归一化。
  return defs.map((d) => ({
    ...d,
    widthPct: d.max,
    fillPct: Math.max(0, Math.min(100, (d.val / d.max) * 100)),
  }));
}
