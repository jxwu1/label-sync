<script setup lang="ts">
import { computed } from "vue";
import { VISIBLE_CAP } from "./constants";
import {
  fmt, fmtDays, urgencyLevel, marginLevel,
  originBadge, profitBadge, coverBar, sparkTrend, sparklinePoints, realBars,
} from "./cells";
import type { RestockItem } from "./types";

const props = defineProps<{ rows: RestockItem[]; coverThreshold: number }>();
const emit = defineEmits<{
  (e: "open-history", bc: string): void;
  (e: "select-supplier", bc: string): void;
}>();
const visible = computed(() => props.rows.slice(0, VISIBLE_CAP));

function sparkPts(it: RestockItem): string {
  return sparklinePoints(realBars(it.weekly_qty_12w));
}
function hasSpark(it: RestockItem): boolean {
  return realBars(it.weekly_qty_12w).some((v) => v > 0);
}
</script>

<template>
  <div class="rs-tbl-wrap">
    <table class="rs-table">
      <thead>
        <tr>
          <th>紧迫分</th>
          <th>货号 / 品名</th>
          <th>供应商</th>
          <th class="rs-num">库存</th>
          <th class="rs-num">可撑</th>
          <th class="rs-num">周销速</th>
          <th class="rs-num">周销额</th>
          <th class="rs-num">毛利率</th>
          <th>12W 趋势</th>
          <th>盈亏</th>
          <th class="rs-num">距进货</th>
          <th class="rs-num rs-rec-g rs-rec-sep">P50</th>
          <th class="rs-num rs-rec-g">P98</th>
          <th class="rs-num rs-rec-g">上次量</th>
        </tr>
      </thead>
      <tbody id="rsTbody">
        <tr v-for="it in visible" :key="it.barcode" class="rs-row">
          <td>
            <span v-if="it.urgency_score != null" class="rs-urg">
              <span class="rs-urg-bar"><span :class="`rs-urg-fill rs-urg-fill--${urgencyLevel(it.urgency_score)}`"
                :style="{ width: Math.max(0, Math.min(100, it.urgency_score)) + '%' }"></span></span>
              <span :class="`rs-urg-num rs-urg-num--${urgencyLevel(it.urgency_score)}`">{{ it.urgency_score }}</span>
            </span>
            <span v-else class="rs-urg-num rs-urg-num--none">—</span>
          </td>
          <td>
            <span class="rs-model">{{ it.name_zh || it.model }}</span>
            <button class="rs-bc-link" @click="emit('open-history', it.barcode)">{{ it.barcode }}</button>
            <span v-if="it.is_truly_discontinued" class="rs-tag rs-tag--disc">停用</span>
            <span v-if="it.is_new_item" class="rs-tag rs-tag--new">新品</span>
            <span v-if="it.stockout_zero_weeks_last8 > 0" class="rs-badge-stockout">⚠ 近 {{ it.stockout_zero_weeks_last8 }} 周零销疑因缺货</span>
          </td>
          <td>
            <span :class="`rs-origin rs-origin--${originBadge(it.origin).cls}`">{{ originBadge(it.origin).char }}</span>
            <button v-if="it.supplier_id" class="rs-supplier" @click="emit('select-supplier', it.supplier_id)">{{ it.supplier_id }}</button>
            <span v-else class="rs-supplier rs-supplier--none">—</span>
          </td>
          <td class="rs-num">{{ fmt(it.qty_total) }}</td>
          <td class="rs-num">
            <span class="rs-cover">
              <span :class="`rs-cover-num ${coverBar(it.weeks_of_cover, props.coverThreshold)?.tone ?? 'ok'}`">
                {{ it.weeks_of_cover != null ? it.weeks_of_cover.toFixed(1) + "w" : "—" }}</span>
              <span v-if="coverBar(it.weeks_of_cover, props.coverThreshold)" class="rs-cover-track">
                <span :class="`rs-cover-fill ${coverBar(it.weeks_of_cover, props.coverThreshold)!.tone}`"
                  :style="{ width: coverBar(it.weeks_of_cover, props.coverThreshold)!.fillPct.toFixed(1) + '%' }"></span>
                <span class="rs-cover-safe" :style="{ left: coverBar(it.weeks_of_cover, props.coverThreshold)!.safePct.toFixed(1) + '%' }"></span>
              </span>
            </span>
          </td>
          <td class="rs-num">{{ fmt(it.weekly_velocity, 1) }}</td>
          <td class="rs-num">€{{ fmt(it.weekly_revenue, 1) }}</td>
          <td class="rs-num">
            <span v-if="it.margin_pct != null" :class="`rs-margin rs-margin--${marginLevel(it.margin_pct)}`">{{ it.margin_pct.toFixed(1) }}%</span>
            <span v-else class="rs-margin rs-margin--none">—</span>
          </td>
          <td>
            <svg v-if="hasSpark(it)" :class="`rs-spark-cell rs-spark-cell--${sparkTrend(it.trend_slope_pct_per_week)}`" viewBox="0 0 60 20">
              <polyline :points="sparkPts(it)" />
            </svg>
            <span v-else class="rs-spark-empty" title="近 12 周无销售">—</span>
          </td>
          <td>
            <span :class="`rs-profit-badge rs-profit-badge--${profitBadge(it.realized_profit_eur, it.inventory_cost_value_eur).cls}`">
              {{ profitBadge(it.realized_profit_eur, it.inventory_cost_value_eur).label }}</span>
          </td>
          <td class="rs-num">{{ fmtDays(it.last_purchase_days_ago) }}</td>
          <td class="rs-num rs-rec-g rs-rec-sep"><span class="rs-rec-v rs-rec-v--hi">{{ it.restock_qty_p50 ?? "—" }}</span></td>
          <td class="rs-num rs-rec-g"><span class="rs-rec-v">{{ it.restock_qty_p98 ?? "—" }}</span></td>
          <td class="rs-num rs-rec-g"><span class="rs-rec-v rs-rec-v--mut">{{ it.last_purchase_qty ?? "—" }}</span></td>
        </tr>
        <tr v-if="visible.length === 0"><td colspan="14" class="empty">无匹配项</td></tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.rs-tbl-wrap { flex: 1; overflow-y: auto; overflow-x: auto; }
.rs-table { width: 100%; border-collapse: collapse; font-size: var(--fs-md); }
.rs-table thead { position: sticky; top: 0; z-index: 2; background: var(--bg-1); }
.rs-table th { padding: 8px 16px; text-align: left; font-size: var(--fs-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-2); border-bottom: 1px solid var(--line-soft); white-space: nowrap; cursor: default; }
.rs-table th.rs-num { text-align: right; }
.rs-table td { padding: 7px 16px; border-bottom: 1px solid var(--line-soft); color: var(--ink-1); vertical-align: middle; }
.rs-table td.rs-num { text-align: right; }
.rs-num { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.rs-row { transition: background var(--t-fast); }
.rs-row:hover { background: var(--bg-2); }

/* Urgency cell */
.rs-urg { display: inline-flex; align-items: center; gap: 6px; }
.rs-urg-bar { width: 48px; height: 5px; background: var(--bg-3); border-radius: 2px; overflow: hidden; flex-shrink: 0; }
.rs-urg-fill { height: 100%; border-radius: 2px; transition: width .3s var(--ease-standard); display: block; }
.rs-urg-fill--high { background: var(--error); }
.rs-urg-fill--mid  { background: var(--warn); }
.rs-urg-fill--low  { background: var(--success); }
.rs-urg-num { font-family: var(--mono); font-size: var(--fs-sm); font-weight: 600; min-width: 20px; text-align: right; }
.rs-urg-num--high { color: var(--error); }
.rs-urg-num--mid  { color: var(--warn); }
.rs-urg-num--low  { color: var(--success); }
.rs-urg-num--none { color: var(--ink-3); }

/* SKU name + code */
.rs-model { font-size: var(--fs-md); color: var(--ink-0); font-weight: 500; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: middle; }
.rs-bc-link { background: none; border: none; padding: 0; margin: 0 0 0 8px; font: inherit; color: var(--ink-2); cursor: pointer; font-family: var(--mono); font-size: var(--fs-xs); }
.rs-bc-link:hover { color: var(--accent); text-decoration: underline; }

/* Tags */
.rs-tag { display: inline-block; margin-left: 6px; padding: 1px 5px; font-family: var(--mono); font-size: 9px; font-weight: 700; border-radius: 2px; vertical-align: middle; letter-spacing: 0.04em; text-transform: uppercase; }
.rs-tag--disc { background: var(--bg-3); color: var(--ink-3); border: 1px solid var(--line-soft); }
.rs-tag--new  { background: var(--success-subtle); color: var(--success); border: 1px solid var(--success-subtle-border); }
.rs-badge-stockout { color: var(--warn); font-size: 12px; white-space: nowrap; margin-left: 6px; }

/* Supplier cell + origin prefix */
.rs-origin { font-size: 13px; line-height: 1; margin-right: 4px; }
.rs-origin--unk { color: var(--ink-3); font-family: var(--mono); font-size: 11px; }
.rs-supplier { font-family: var(--sans); font-size: var(--fs-md); color: var(--ink-2); background: transparent; border: none; padding: 0; cursor: pointer; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; transition: color var(--t-fast); }
.rs-supplier:hover { color: var(--accent); text-decoration: underline; }
.rs-supplier--none { color: var(--ink-3); cursor: default; }
.rs-supplier--none:hover { color: var(--ink-3); text-decoration: none; }

/* Weeks of cover micro-bar (静态，省 knob) */
.rs-cover { display: inline-flex; align-items: center; gap: 7px; justify-content: flex-end; }
.rs-cover-num { font-family: var(--mono); font-size: var(--fs-sm); font-weight: 600; min-width: 34px; text-align: right; }
.rs-cover-num.crit { color: var(--error); }
.rs-cover-num.low { color: var(--warn); }
.rs-cover-num.ok { color: var(--ink-1); }
.rs-cover-num.high { color: var(--success); }
.rs-cover-track { position: relative; width: 44px; height: 5px; background: var(--bg-3); border-radius: 2px; overflow: visible; flex-shrink: 0; }
.rs-cover-fill { position: absolute; left: 0; top: 0; height: 100%; border-radius: 2px; }
.rs-cover-fill.crit { background: var(--error); }
.rs-cover-fill.low { background: var(--warn); }
.rs-cover-fill.ok { background: var(--ink-3); }
.rs-cover-fill.high { background: var(--success); }
.rs-cover-safe { position: absolute; top: -2px; width: 1px; height: 9px; background: var(--ink-1); opacity: .55; }

/* Margin */
.rs-margin { font-family: var(--mono); font-size: var(--fs-sm); }
.rs-margin--great, .rs-margin--good { color: var(--success); }
.rs-margin--meh  { color: var(--warn); }
.rs-margin--bad  { color: var(--error); }
.rs-margin--none { color: var(--ink-3); }

/* Sparkline */
.rs-spark-cell { width: 60px; height: 20px; }
.rs-spark-cell polyline { fill: none; stroke-width: 1.2; stroke-linecap: round; stroke-linejoin: round; }
.rs-spark-cell--up polyline { stroke: var(--success); }
.rs-spark-cell--down polyline { stroke: var(--error); }
.rs-spark-cell--flat polyline { stroke: var(--ink-3); }
.rs-spark-empty { display: inline-block; width: 60px; text-align: center; color: var(--ink-3); font-family: var(--mono); cursor: help; }

/* Profit badge */
.rs-profit-badge { display: inline-flex; align-items: center; padding: 1px 5px; border-radius: 2px; font-size: 9px; font-weight: 700; text-transform: uppercase; }
.rs-profit-badge--good { color: var(--success); background: var(--success-subtle); border: 1px solid var(--success-subtle-border); }
.rs-profit-badge--mid  { color: var(--warn); background: var(--warn-subtle); border: 1px solid var(--warn-subtle-border); }
.rs-profit-badge--bad  { color: var(--error); background: var(--error-subtle); border: 1px solid var(--error-subtle-border); }
.rs-profit-badge--unknown { color: var(--ink-3); background: var(--bg-3); border: 1px solid var(--line-soft); }

/* Recommend group (p50/p98/上次量 高亮组) */
.rs-table th.rs-rec-g { background: var(--bg-2); color: var(--ink-1); }
.rs-table td.rs-rec-g { background: var(--accent-subtle); }
.rs-rec-sep { border-left: 2px solid var(--accent-subtle-border) !important; }
.rs-rec-v { font-family: var(--mono); font-size: var(--fs-sm); font-weight: 600; color: var(--ink-0); }
.rs-rec-v--hi { color: var(--accent); }
.rs-rec-v--mut { color: var(--ink-2); }

/* Empty state */
.rs-table .empty { text-align: center; color: var(--ink-2); padding: 40px; }
</style>
