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
