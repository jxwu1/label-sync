export function fmtEurOrDash(v: number | null | undefined): string {
  return v == null ? "—" : "€" + fmt(v, 2);
}

export function fmt(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
}

export function fmtDays(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 1) return "今天";
  if (n < 30) return `${n} 天前`;
  if (n < 365) return `${Math.round(n / 30)} 月前`;
  return `${(n / 365).toFixed(1)} 年前`;
}

export function coverTone(w: number | null | undefined, T: number): string {
  if (w === null || w === undefined) return "ok";
  if (w < T * 0.5) return "crit";
  if (w < T) return "low";
  if (w < T * 2) return "ok";
  return "high";
}

export function urgencyLevel(score: number): "high" | "mid" | "low" {
  return score >= 70 ? "high" : score >= 40 ? "mid" : "low";
}

export function wocLevel(woc: number): string {
  if (woc <= 2) return "crit";
  if (woc <= 4) return "warn";
  if (woc >= 20) return "cold";
  return "";
}

export function marginLevel(m: number): string {
  if (m >= 50) return "great";
  if (m >= 30) return "good";
  if (m >= 10) return "meh";
  return "bad";
}

const COVER_CAP = 13.0; // 微条满刻度（与 THRESH.COVER_CAP 同值，restock.js COVER_CAP）

// 毛利单元格字段子集（marginTooltip / marginSrcMark 用）
interface MarginFields {
  margin_pct: number | null | undefined;
  margin_source?: string | null;
  margin_price_source?: string | null;
  master_stock_price_eur?: number | null;
  master_sale_price_eur?: number | null;
  last_purchase_unit_price?: number | null;
  sale_net_avg?: number | null;
}

// 毛利 tooltip（restock.js:227-251；spec line 30 明列保留，用扁平字段）
export function marginTooltip(it: MarginFields): string {
  if (it.margin_pct === null || it.margin_pct === undefined) return "缺进货价或售价";
  const costIsMaster = it.margin_source === "master";
  const priceIsMaster = it.margin_price_source === "master";
  const cost = costIsMaster ? it.master_stock_price_eur : it.last_purchase_unit_price;
  const costLabel = costIsMaster ? "主档参考进价" : "上次进价";
  const salePrice = priceIsMaster ? it.master_sale_price_eur : it.sale_net_avg;
  const saleLabel = priceIsMaster ? "主档售价" : "批发均价";
  return `毛利 ${it.margin_pct}%\n${saleLabel} €${salePrice}\n${costLabel} €${cost}`;
}

// 任一端用主档兜底/参考价 → "~"（restock.js:248）
export function marginSrcMark(it: MarginFields): string {
  if (it.margin_pct === null || it.margin_pct === undefined) return "";
  return it.margin_source === "master" || it.margin_price_source === "master" ? "~" : "";
}

// 来源徽标前缀（restock.js:109 originBadge）
export function originBadge(origin: string): { char: string; cls: string } {
  if (origin === "FOREIGN") return { char: "🇬🇷", cls: "fo" };
  if (origin === "CN") return { char: "🇨🇳", cls: "cn" };
  return { char: "?", cls: "unk" };
}

// 盈亏列 badge（restock.js:274 profitBadgeRow；inv 缺省 0）
export function profitBadge(
  realizedProfitEur: number | null | undefined,
  inventoryCostValueEur: number | null | undefined,
): { label: string; cls: string } {
  if (realizedProfitEur === null || realizedProfitEur === undefined) {
    return { label: "缺成本", cls: "unknown" };
  }
  const inv = inventoryCostValueEur ?? 0;
  if (realizedProfitEur > 0) return { label: "已回本", cls: "good" };
  if (realizedProfitEur + inv > 0) return { label: "压货中", cls: "mid" };
  return { label: "未回本", cls: "bad" };
}

// 可撑微条几何（restock.js:196 coverCell；knob 交互省略，仅静态 num+track+fill+safe）
export function coverBar(
  w: number | null | undefined, T: number,
): { tone: string; fillPct: number; safePct: number } | null {
  if (w === null || w === undefined) return null;
  return {
    tone: coverTone(w, T),
    fillPct: Math.min((w / COVER_CAP) * 100, 100),
    safePct: Math.min((T / COVER_CAP) * 100, 100),
  };
}

// 趋势着色档（restock.js:362 sparkColor by trend_slope_pct_per_week）
export function sparkTrend(trend: number | null | undefined): "up" | "down" | "flat" {
  if (trend === null || trend === undefined || trend === 0) return "flat";
  return trend > 0 ? "up" : "down";
}

// 12 周净销量数组兜底（restock.js:254 realBars；非 12 长度 → 全 0）
export function realBars(weekly: number[] | null | undefined): number[] {
  return Array.isArray(weekly) && weekly.length === 12 ? weekly : new Array(12).fill(0);
}

// SVG polyline 点串（restock.js:262 sparkline；viewBox 60×20，12 周点）
export function sparklinePoints(values: number[]): string {
  const max = Math.max(...values, 1);
  const n = values.length;
  return values.map((v, i) => {
    const x = (n > 1 ? (i / (n - 1)) * 56 : 28) + 2;
    const y = 18 - (v / max) * 16; // 2(顶) .. 18(底)
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}
