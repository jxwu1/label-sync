<script setup lang="ts">
import type { Kpi } from "./kpi";
defineProps<{ kpi: Kpi }>();
</script>

<template>
  <div class="rs-kpis">
    <div class="rs-kpi"><span class="rs-kpi-num">{{ kpi.hot.toLocaleString() }}</span><span class="rs-kpi-label">紧急</span></div>
    <div class="rs-kpi"><span class="rs-kpi-num">{{ kpi.watch.toLocaleString() }}</span><span class="rs-kpi-label">关注</span></div>
    <div class="rs-kpi"><span class="rs-kpi-num">{{ kpi.ok.toLocaleString() }}</span><span class="rs-kpi-label">充足</span></div>
    <div class="rs-kpi"><span class="rs-kpi-num">{{ kpi.spend > 0 ? "€" + Math.round(kpi.spend).toLocaleString() : "—" }}</span><span class="rs-kpi-label">本周补货额</span></div>
  </div>
</template>
