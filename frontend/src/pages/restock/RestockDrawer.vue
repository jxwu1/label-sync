<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRestockDetailStore } from "../../stores/restockDetail";
import { fmt, fmtEurOrDash } from "./cells";
import { profitStatus, retailPriceLine, cashflowImbalance, scoreSegments } from "./drawer-cells";

const props = defineProps<{ barcode: string }>();

const store = useRestockDetailStore();
const state = computed(() => store.entries[props.barcode]);
const d = computed(() => store.cache[props.barcode]);

const ps   = computed(() => (d.value ? profitStatus(d.value.realized_profit_eur, d.value.inventory_cost_value_eur) : null));
const rpl  = computed(() => (d.value ? retailPriceLine(d.value.retail_price_observed, d.value.retail_price_estimate, d.value.retail_qty_26w) : null));
const segs = computed(() => (d.value?.urgency_breakdown ? scoreSegments(d.value.urgency_breakdown) : []));

onMounted(() => store.load(props.barcode));
</script>

<template>
  <div class="rs-drawer">
    <p v-if="state === 'loading'" class="rs-drawer-muted">加载中…</p>
    <p v-else-if="state === 'missing'" class="rs-drawer-muted">无补货明细（该 SKU 不在汇总）</p>
    <p v-else-if="state === 'error'" class="rs-drawer-muted">明细加载失败：{{ store.errorMsg[barcode] }}（点行重开重试）</p>
    <div v-else-if="state === 'ready' && d" class="rs-drawer-grid">

      <!-- § 1 财务快照 -->
      <section class="rs-drawer-sec">
        <h4>💰 财务快照</h4>
        <div>批发价 <b>{{ fmtEurOrDash(d.master_sale_price_eur ?? d.sale_net_avg) }}</b> <span class="rs-drawer-muted">(主档)</span></div>
        <!-- 零售价行: observed/estimate/both/none -->
        <template v-if="rpl!.kind === 'both'">
          <div>零售价 <b>{{ fmtEurOrDash(rpl!.observed) }}</b>
            <span class="rs-drawer-muted">(实际 {{ rpl!.qty }} 笔均价)</span>
            · 估算 {{ fmtEurOrDash(rpl!.estimate) }} (×2)
          </div>
        </template>
        <template v-else-if="rpl!.kind === 'observed'">
          <div>零售价 <b>{{ fmtEurOrDash(rpl!.observed) }}</b>
            <span class="rs-drawer-muted">(实际)</span>
          </div>
        </template>
        <template v-else-if="rpl!.kind === 'estimate'">
          <div>零售价 <b>{{ fmtEurOrDash(rpl!.estimate) }}</b>
            <span class="rs-drawer-muted">(批发×2 估算)</span>
          </div>
        </template>
        <template v-else>
          <div>零售价 —</div>
        </template>
        <div>单件进价 <b>{{ fmtEurOrDash(d.last_purchase_unit_price ?? d.master_stock_price_eur) }}</b>
          <span class="rs-drawer-muted">({{ d.margin_source === 'master' ? '主档参考' : d.margin_source === 'purchase' ? '上次成交' : '—' }})</span>
        </div>
        <div>单件毛利率 <b>{{ d.margin_pct != null ? d.margin_pct + '%' : '—' }}</b></div>
      </section>

      <!-- § 2 库存 -->
      <section class="rs-drawer-sec">
        <h4>📦 库存</h4>
        <div>当前库存 <b>{{ fmt(d.qty_total) }} 件</b></div>
        <div>库存可销售金额 <b>{{ fmtEurOrDash(d.inventory_sale_value_eur) }}</b></div>
        <div>库存成本 <b>{{ fmtEurOrDash(d.inventory_cost_value_eur) }}</b></div>
        <div>可撑 <b>{{ d.weeks_of_cover != null ? d.weeks_of_cover.toFixed(1) + ' 周可撑' : '—' }}</b></div>
      </section>

      <!-- § 3 累计盈亏 -->
      <section class="rs-drawer-sec">
        <h4>💵 累计盈亏
          <span :class="`rs-profit-badge rs-profit-badge--${ps!.cls}`">
            {{ ps!.label }}
          </span>
        </h4>
        <div>累计投入 <b>{{ fmtEurOrDash(d.lifetime_invested_eur) }}</b>
          <span class="rs-drawer-muted">({{ fmt(d.lifetime_purchase_qty) }} 件)</span>
        </div>
        <div>累计销售 <b>€{{ fmt(d.lifetime_sale_revenue_eur, 0) }}</b>
          <span class="rs-drawer-muted">({{ fmt(d.lifetime_sale_qty) }} 件)</span>
        </div>
        <!-- profitLine by tier -->
        <template v-if="ps!.cls === 'unknown'">
          <div><span class="rs-drawer-muted">无 cost 数据</span></div>
        </template>
        <template v-else-if="ps!.cls === 'good'">
          <div>实现利润 <b>+€{{ fmt(d.realized_profit_eur!, 0) }}</b></div>
        </template>
        <template v-else-if="ps!.cls === 'mid'">
          <div>实现利润 <b>€{{ fmt(d.realized_profit_eur!, 0) }}</b> · 库存能补 <b>€{{ fmt(d.inventory_cost_value_eur ?? 0, 0) }}</b> 回本</div>
        </template>
        <template v-else>
          <div>实现利润 <b>€{{ fmt(d.realized_profit_eur!, 0) }}</b> + 库存 <b>€{{ fmt(d.inventory_cost_value_eur ?? 0, 0) }}</b> 仍亏 <b>€{{ fmt(-(d.realized_profit_eur! + (d.inventory_cost_value_eur ?? 0)), 0) }}</b></div>
        </template>
        <!-- 净现金流 -->
        <div v-if="d.net_cashflow_eur != null">
          净现金流 <b>{{ d.net_cashflow_eur >= 0 ? '+' : '' }}€{{ fmt(d.net_cashflow_eur, 0) }}</b>
          <span v-if="cashflowImbalance(d.inventory_imbalance_pct).warn" class="rs-trunc-warn"
            :title="`进销库存差额 ${d.inventory_imbalance_pct}% > 30%, FIFO 实现利润可能高估, 实际请看净现金流`">
            ⚠️ 不平 {{ d.inventory_imbalance_pct }}%
          </span>
        </div>
        <!-- 首笔事件 -->
        <div v-if="d.first_event_at" class="rs-drawer-muted">
          首笔事件 {{ d.first_event_at }}
          <span v-if="d.is_history_truncated" class="rs-trunc-warn"
            title="该 SKU 第一笔事件早于 ETL 窗口起点 (2021-06-01), 更早期的进/销记录未纳入, 实际累计利润可能与此估算有出入">
            ⚠️ 历史可能不全
          </span>
        </div>
      </section>

      <!-- § 4 销售概况 (CALIBER FIX: 累计批发，per-week，无 ×26 外推) -->
      <section class="rs-drawer-sec">
        <h4>📊 销售概况</h4>
        <div>累计批发 <b>{{ fmt(d.total_qty) }} 件</b></div>
        <div>近 26 周活跃 <b>{{ fmt(d.n_active_weeks_26w) }} 周</b></div>
        <div>周销速 <b>{{ fmt(d.weekly_velocity, 2) }} 件/周</b> · 周销额 <b>€{{ fmt(d.weekly_revenue, 2) }}/周</b></div>
        <div>真实零售 26 周 <b>{{ fmt(d.retail_qty_26w) }} 件</b> / €{{ fmt(d.retail_revenue_26w, 0) }} <span class="rs-drawer-muted">(不进算法)</span></div>
        <div>零售占比 <b>{{ (d.retail_share_26w * 100).toFixed(0) }}%</b></div>
      </section>

      <!-- § 5 紧迫分 -->
      <section class="rs-drawer-sec">
        <h4>🎯 紧迫分 <b>{{ d.urgency_score ?? '—' }}</b></h4>
        <template v-if="d.urgency_breakdown">
          <div class="rs-score-bar">
            <div
              v-for="seg in segs"
              :key="seg.cls"
              :class="`rs-score-seg rs-score-seg--${seg.cls}`"
              :style="{ width: seg.widthPct + '%', opacity: seg.fillPct / 100 + 0.15 }"
            ></div>
          </div>
          <div class="rs-score-legend">
            <span v-for="seg in segs" :key="seg.cls" class="rs-score-legend-item">
              <span :class="`rs-score-legend-dot rs-score-seg--${seg.cls}`"></span>
              {{ seg.label }}
            </span>
          </div>
          <div>销额(30): <b>{{ d.urgency_breakdown.velocity }}</b>
            <span v-if="d.urgency_breakdown.velocity_pctile != null" class="rs-drawer-muted"> (p{{ (d.urgency_breakdown.velocity_pctile * 100).toFixed(0) }})</span>
          </div>
          <div>库存(30): <b>{{ d.urgency_breakdown.cover }}</b>
            <span v-if="d.urgency_breakdown.demand_validity != null && d.urgency_breakdown.demand_validity < 1.0" class="rs-dv-tag"
              :title="`长尾活跃度折扣 (n_active_weeks=${d.n_active_weeks_26w}/4)`">×{{ d.urgency_breakdown.demand_validity }}</span>
          </div>
          <div>距进货(10): <b>{{ d.urgency_breakdown.recency }}</b>
            <span v-if="d.urgency_breakdown.demand_validity != null && d.urgency_breakdown.demand_validity < 1.0" class="rs-dv-tag"
              :title="`长尾活跃度折扣 (n_active_weeks=${d.n_active_weeks_26w}/4)`">×{{ d.urgency_breakdown.demand_validity }}</span>
          </div>
          <div>毛利(30): <b>{{ d.urgency_breakdown.margin }}</b>
            <span v-if="d.urgency_breakdown.margin_pctile != null" class="rs-drawer-muted"> (p{{ (d.urgency_breakdown.margin_pctile * 100).toFixed(0) }})</span>
          </div>
        </template>
        <template v-else>
          <div>—</div>
        </template>
      </section>

    </div>
  </div>
</template>

<style scoped>
.rs-drawer { padding: 12px 16px; }
.rs-drawer-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
}
@media (max-width: 1400px) { .rs-drawer-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px)  { .rs-drawer-grid { grid-template-columns: repeat(2, 1fr); } }

.rs-drawer-sec {
  background: var(--bg-1);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-sm);
  padding: 10px 12px;
}
.rs-drawer-sec h4 {
  margin: 0 0 6px 0;
  font-size: var(--fs-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-2);
  display: flex;
  align-items: center;
  gap: 6px;
}
.rs-drawer-sec > div {
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-1);
  font-family: var(--mono);
  padding: 1px 0;
}
.rs-drawer-sec b { font-family: var(--mono); color: var(--ink-0); font-weight: 600; }

.rs-drawer-muted { color: var(--ink-2); font-size: var(--fs-sm); font-weight: 400; }

.rs-dv-tag {
  display: inline-block;
  padding: 0 4px;
  background: var(--warn-subtle);
  color: var(--warn);
  border: 1px solid var(--warn-subtle-border);
  border-radius: 2px;
  font-size: var(--fs-xs);
  margin-left: 3px;
  cursor: help;
}
.rs-trunc-warn { font-size: var(--fs-xs); color: var(--warn); cursor: help; }

/* Profit badge */
.rs-profit-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 5px;
  border-radius: 2px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
}
.rs-profit-badge--good    { color: var(--success); background: var(--success-subtle); border: 1px solid var(--success-subtle-border); }
.rs-profit-badge--mid     { color: var(--warn); background: var(--warn-subtle); border: 1px solid var(--warn-subtle-border); }
.rs-profit-badge--bad     { color: var(--error); background: var(--error-subtle); border: 1px solid var(--error-subtle-border); }
.rs-profit-badge--unknown { color: var(--ink-3); background: var(--bg-3); border: 1px solid var(--line-soft); }

/* Score bar */
.rs-score-bar { display: flex; align-items: center; gap: 4px; margin-top: 3px; }
.rs-score-seg { height: 6px; border-radius: 2px; transition: width 0.15s; }
.rs-score-seg--v { background: var(--accent); }
.rs-score-seg--c { background: var(--info); }
.rs-score-seg--r { background: var(--warn); }
.rs-score-seg--m { background: var(--success); }

.rs-score-legend { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.rs-score-legend-item { display: flex; align-items: center; gap: 3px; font-size: 9px; color: var(--ink-2); }
.rs-score-legend-dot { width: 6px; height: 6px; border-radius: 1px; }
</style>
