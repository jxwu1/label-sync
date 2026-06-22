<script setup lang="ts">
import type { Kpi } from "./kpi";
defineProps<{ kpi: Kpi }>();
</script>

<template>
  <div class="rs-kpis">
    <div class="rs-kpi" data-tone="error"><span class="rs-kpi-num">{{ kpi.hot.toLocaleString() }}</span><span class="rs-kpi-label">紧急</span></div>
    <div class="rs-kpi" data-tone="warn"><span class="rs-kpi-num">{{ kpi.watch.toLocaleString() }}</span><span class="rs-kpi-label">关注</span></div>
    <div class="rs-kpi" data-tone="success"><span class="rs-kpi-num">{{ kpi.ok.toLocaleString() }}</span><span class="rs-kpi-label">充足</span></div>
    <div class="rs-kpi"><span class="rs-kpi-num">{{ kpi.spend > 0 ? "€" + Math.round(kpi.spend).toLocaleString() : "—" }}</span><span class="rs-kpi-label">本周补货额</span></div>
  </div>
</template>

<style scoped>
.rs-kpis { display: flex; gap: 6px; flex-wrap: wrap; }
.rs-kpi { display: inline-flex; align-items: baseline; gap: 6px; padding: 5px 12px; background: var(--bg-0); border: 1px solid var(--line-soft); border-radius: var(--r-sm); }
.rs-kpi-num { font-family: var(--display); font-size: var(--fs-lg); font-weight: 700; letter-spacing: -0.02em; line-height: 1; color: var(--ink-0); }
.rs-kpi-label { font-size: var(--fs-xs); font-weight: 600; color: var(--ink-2); text-transform: uppercase; letter-spacing: 0.03em; white-space: nowrap; }
.rs-kpi[data-tone="error"] .rs-kpi-num { color: var(--error); }
.rs-kpi[data-tone="warn"] .rs-kpi-num { color: var(--warn); }
.rs-kpi[data-tone="success"] .rs-kpi-num { color: var(--success); }
</style>
