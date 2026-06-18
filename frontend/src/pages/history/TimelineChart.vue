<script setup lang="ts">
import { computed } from "vue";
import type { TimelineWeekVM, MonthlySaleVM } from "./timeline-types";

const props = defineProps<{ weeks: TimelineWeekVM[]; monthlySales: MonthlySaleVM[] }>();

// viewBox 几何（单位 = viewBox units，非 CSS px）
const W = 1000, H = 260, padL = 44, padR = 52, padT = 16, padB = 28;
const innerW = W - padL - padR;
const innerH = H - padT - padB;
const baselineY = padT + innerH;
const BAR_GAP = 3;

function dayNum(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86400000;
}
function nextMonthDayNum(monthStartIso: string): number {
  const [y, m] = monthStartIso.slice(0, 10).split("-").map(Number);
  const ny = m === 12 ? y + 1 : y;
  const nm = m === 12 ? 1 : m + 1;
  return Date.UTC(ny, nm - 1, 1) / 86400000;
}

const hasData = computed(
  () =>
    props.monthlySales.some((m) => m.saleQty + m.retailQty !== 0) ||
    props.weeks.some((w) => w.purchaseUnitPrice != null),
);

// 共享日期域（HC-P3-9）
const domain = computed(() => {
  const starts: number[] = [];
  if (props.weeks.length) starts.push(dayNum(props.weeks[0].weekStart));
  if (props.monthlySales.length) starts.push(dayNum(props.monthlySales[0].monthStart));
  const ends: number[] = [];
  if (props.weeks.length) ends.push(dayNum(props.weeks[props.weeks.length - 1].weekStart) + 7);
  if (props.monthlySales.length)
    ends.push(nextMonthDayNum(props.monthlySales[props.monthlySales.length - 1].monthStart));
  const t0 = starts.length ? Math.min(...starts) : 0;
  const t1 = ends.length ? Math.max(...ends) : t0 + 1;
  return { t0, span: Math.max(1, t1 - t0) };
});
function x(day: number): number {
  const { t0, span } = domain.value;
  return padL + ((day - t0) / span) * innerW;
}

const maxQ = computed(() =>
  Math.max(1, ...props.monthlySales.map((m) => Math.max(0, m.saleQty + m.retailQty))),
);

interface Bar { x: number; w: number; h: number; y: number; title: string; month: string; }
interface ReturnMark { cx: number; title: string; month: string; }
const bars = computed<Bar[]>(() => {
  const out: Bar[] = [];
  for (const m of props.monthlySales) {
    const net = m.saleQty + m.retailQty;
    if (net <= 0) continue;
    const x0 = x(dayNum(m.monthStart));
    const x1 = x(nextMonthDayNum(m.monthStart));
    const h = (net / maxQ.value) * innerH * 0.85;
    out.push({
      x: x0 + BAR_GAP / 2,
      w: Math.max(1, x1 - x0 - BAR_GAP),
      h,
      y: baselineY - h,
      title: `${m.monthStart.slice(0, 7)}：${net} 件`,
      month: m.monthStart,
    });
  }
  return out;
});
const returnMarks = computed<ReturnMark[]>(() => {
  const out: ReturnMark[] = [];
  for (const m of props.monthlySales) {
    const net = m.saleQty + m.retailQty;
    if (net >= 0) continue;
    const x0 = x(dayNum(m.monthStart));
    const x1 = x(nextMonthDayNum(m.monthStart));
    out.push({
      cx: (x0 + x1) / 2,
      title: `${m.monthStart.slice(0, 7)}：净退货 ${Math.abs(net)} 件`,
      month: m.monthStart,
    });
  }
  return out;
});
// 退货三角 path（底 8 × 高 6 viewBox units，尖朝上，底贴 baseline 上方 1）
function trianglePath(cx: number): string {
  const half = 4, h = 6, baseY = baselineY - 1;
  return `M${(cx - half).toFixed(1)},${baseY} L${(cx + half).toFixed(1)},${baseY} L${cx.toFixed(1)},${(baseY - h).toFixed(1)} Z`;
}

// 进价：前向填充 + 反向外推
const priceInfo = computed(() => {
  const raw = props.weeks.map((w) => w.purchaseUnitPrice);
  const firstIdx = raw.findIndex((p) => p != null);
  const valid = raw.filter((p): p is number => p != null);
  const hasPrice = valid.length > 0;
  const filled: (number | null)[] = new Array(raw.length).fill(null);
  if (hasPrice) {
    let last = raw[firstIdx]!;
    for (let i = 0; i < raw.length; i++) {
      if (raw[i] != null) last = raw[i]!;
      filled[i] = last;
    }
  }
  const maxP = hasPrice ? Math.max(...valid) : 1;
  const minP = hasPrice ? Math.min(...valid) : 0;
  const sameValue = hasPrice && maxP === minP;
  return { filled, hasPrice, maxP, minP, sameValue };
});
function weekMidX(i: number): number {
  return x(dayNum(props.weeks[i].weekStart) + 3.5);
}
function priceY(p: number): number {
  const { sameValue, maxP } = priceInfo.value;
  if (sameValue) return padT + innerH * 0.4;
  const range = Math.max(0.01, maxP);
  return baselineY - (p / range) * innerH * 0.85;
}
// 真 step path：水平保持到下一点 x，再垂直到下一点 y
const pricePath = computed(() => {
  const { filled, hasPrice } = priceInfo.value;
  if (!hasPrice) return "";
  let d = "";
  let prevY: number | null = null;
  for (let i = 0; i < filled.length; i++) {
    const p = filled[i];
    if (p == null) continue;
    const px = weekMidX(i);
    const py = priceY(p);
    if (prevY === null) {
      d += `M${px.toFixed(1)},${py.toFixed(1)}`;
    } else if (py === prevY) {
      d += ` L${px.toFixed(1)},${py.toFixed(1)}`;          // 水平保持，无变化不画竖直
    } else {
      d += ` L${px.toFixed(1)},${prevY.toFixed(1)} L${px.toFixed(1)},${py.toFixed(1)}`;  // 水平保持 + 垂直跳变
    }
    prevY = py;
  }
  return d;
});
interface Dot { cx: number; cy: number; title: string; }
const dots = computed<Dot[]>(() => {
  const out: Dot[] = [];
  props.weeks.forEach((w, i) => {
    if (w.rawUnitPriceLocal == null || w.purchaseUnitPrice == null) return;
    const cy = priceY(w.purchaseUnitPrice);
    let title = `${w.weekStart}：€${w.purchaseUnitPrice.toFixed(4)}`;
    if (w.currencyLocal === "RMB") {
      title = `${w.weekStart}：€${w.purchaseUnitPrice.toFixed(4)}（落地）← ¥${w.rawUnitPriceLocal}（含汇率+可用海运分摊）`;
    }
    out.push({ cx: weekMidX(i), cy, title });
  });
  return out;
});

// 左轴销量 ticks（4 ticks，高→低，整数去重，低 maxQ 时不出现重复标签）
const salesTicks = computed(() => {
  const seen = new Set<number>();
  const out: { y: number; label: string }[] = [];
  for (const f of [1, 0.75, 0.5, 0.25]) {
    const val = Math.round(maxQ.value * f);
    if (seen.has(val)) continue;
    seen.add(val);
    out.push({ y: baselineY - f * innerH * 0.85, label: String(val) });
  }
  return out;
});
// 右轴进价 ticks（同价单 tick）
const priceTicks = computed(() => {
  const { hasPrice, sameValue, maxP } = priceInfo.value;
  if (!hasPrice) return [];
  if (sameValue) return [{ y: padT + innerH * 0.4, label: `€${maxP.toFixed(2)}` }];
  return [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: baselineY - f * innerH * 0.85,
    label: `€${(maxP * f).toFixed(2)}`,
  }));
});
// X 月份标签（~7 个）
const xLabels = computed(() => {
  const ms = props.monthlySales;
  if (!ms.length) return [];
  const n = Math.min(7, ms.length);
  const out: { x: number; label: string; anchor: string }[] = [];
  for (let i = 0; i < n; i++) {
    const idx = Math.floor(((ms.length - 1) * i) / Math.max(1, n - 1));
    const anchor = n === 1 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle";
    out.push({ x: x(dayNum(ms[idx].monthStart)), label: ms[idx].monthStart.slice(0, 7), anchor });
  }
  return out;
});
</script>

<template>
  <div class="tml-wrap">
    <div v-if="!hasData" class="tml-empty">无数据</div>
    <svg v-else class="tml-svg" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="xMidYMid meet">
      <!-- baseline -->
      <line :x1="padL" :x2="W - padR" :y1="baselineY" :y2="baselineY" stroke="var(--line)" stroke-width="1" />
      <!-- 月销量柱 -->
      <rect
        v-for="b in bars" :key="'b' + b.month" class="tml-bar"
        :x="b.x" :y="b.y" :width="b.w" :height="b.h" :data-month="b.month"
        fill="var(--accent)" opacity="0.85" rx="0.5"
      ><title>{{ b.title }}</title></rect>
      <!-- 负净退货三角 -->
      <path
        v-for="r in returnMarks" :key="'r' + r.month" data-kind="net-return" class="tml-return"
        :d="trianglePath(r.cx)" fill="var(--warn)"
      ><title>{{ r.title }}</title></path>
      <!-- 进价折线 -->
      <path v-if="pricePath" class="tml-price-line" :d="pricePath" fill="none"
        stroke="var(--warn)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
      <!-- 进货 dot -->
      <circle v-for="(d, i) in dots" :key="'d' + i" class="tml-dot"
        :cx="d.cx" :cy="d.cy" r="2.5" fill="var(--warn)"><title>{{ d.title }}</title></circle>
      <!-- 左轴销量 ticks -->
      <text v-for="(t, i) in salesTicks" :key="'sl' + i" class="tml-yl"
        :x="padL - 6" :y="t.y + 3" text-anchor="end" fill="var(--ink-2)" font-size="10">{{ t.label }}</text>
      <!-- 右轴进价 ticks -->
      <text v-for="(t, i) in priceTicks" :key="'yr' + i" class="tml-yr"
        :x="W - padR + 6" :y="t.y + 3" text-anchor="start" fill="var(--ink-2)" font-size="10">{{ t.label }}</text>
      <!-- X 月份标签 -->
      <text v-for="(l, i) in xLabels" :key="'xl' + i" class="tml-xlabel"
        :x="l.x" :y="baselineY + 16" :text-anchor="l.anchor" fill="var(--ink-2)" font-size="10">{{ l.label }}</text>
    </svg>
  </div>
</template>

<style scoped>
.tml-wrap { width: 100%; }
.tml-svg { width: 100%; height: auto; display: block; }
.tml-empty { padding: 24px 0; color: var(--ink-2); font-size: var(--fs-sm); text-align: center; }
</style>
