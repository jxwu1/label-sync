<script setup lang="ts">
import { computed, onMounted } from "vue";
import PageHeader from "../../components/PageHeader.vue";
import { useForecastEvalStore } from "../../stores/forecastEval";

const store = useForecastEvalStore();
onMounted(() => store.load());
const vm = computed(() => store.vm);

const fmtMase = (v: number | null) => (v == null ? "—" : v.toFixed(2));
const fmtPct = (v: number | null) => (v == null ? "—" : `${Math.round(v)}%`);
const fmtCov = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

const subtitle = computed(() => {
  const v = vm.value;
  if (!v || v.missing) return undefined;
  return `run #${v.runId} · ${v.backtestDate ?? "—"}`;
});

const tierTotal = computed(() => {
  const t = vm.value?.tiers;
  return t ? (t.high + t.medium + t.low) || 1 : 1;
});
const segPct = (n: number) => `${((n / tierTotal.value) * 100).toFixed(1)}%`;
</script>

<template>
  <main class="fe">
    <PageHeader title="预测效果" :subtitle="subtitle" />

    <p v-if="store.loading" class="fe__msg">加载中…</p>
    <p v-else-if="store.error" class="fe__error">{{ store.error }}</p>

    <template v-else-if="vm">
      <div v-if="vm.missing" class="fe__banner">
        尚无回测数据，置信度全部按缺失评为低。先触发一次 backtest 再来看。
      </div>

      <div class="fe__kpis">
        <div class="fe__kpi"><span class="fe__kpi-v">{{ fmtPct(vm.headline.beatsNaivePct) }}</span><span class="fe__kpi-l">MASE&lt;1 占比</span></div>
        <div class="fe__kpi"><span class="fe__kpi-v">{{ fmtMase(vm.headline.medianMase) }}</span><span class="fe__kpi-l">中位 MASE</span></div>
        <div class="fe__kpi"><span class="fe__kpi-v">{{ fmtCov(vm.headline.avgCoverageP98) }}</span><span class="fe__kpi-l">覆盖 @p98</span></div>
        <div class="fe__kpi"><span class="fe__kpi-v">{{ vm.scoredSkus }}/{{ vm.forecastSkus }}</span><span class="fe__kpi-l">评分 / 预测 SKU</span></div>
      </div>

      <div class="fe__tiers">
        <span class="fe__tiers-label">置信度分布</span>
        <div class="fe__bar">
          <div class="fe__seg fe__seg--high" :style="{ width: segPct(vm.tiers.high) }"></div>
          <div class="fe__seg fe__seg--medium" :style="{ width: segPct(vm.tiers.medium) }"></div>
          <div class="fe__seg fe__seg--low" :style="{ width: segPct(vm.tiers.low) }"></div>
        </div>
        <div class="fe__legend">
          <span><i class="fe__dot fe__dot--high"></i>高 {{ vm.tiers.high }}</span>
          <span><i class="fe__dot fe__dot--medium"></i>中 {{ vm.tiers.medium }}</span>
          <span><i class="fe__dot fe__dot--low"></i>低 {{ vm.tiers.low }}</span>
        </div>
      </div>

      <section class="fe__pnl">
        <div class="fe__pnl-hd">按 SKU 类型</div>
        <table class="fe__table">
          <thead><tr><th>SKU 类型</th><th class="fe__num">评分数</th><th class="fe__num">中位MASE</th><th class="fe__num">胜Naive%</th><th class="fe__num">覆盖</th></tr></thead>
          <tbody>
            <tr v-for="r in vm.byType" :key="r.skuType">
              <td>{{ r.skuType }}</td>
              <td class="fe__num">{{ r.n }}</td>
              <td class="fe__num">{{ fmtMase(r.medianMase) }}</td>
              <td class="fe__num">{{ fmtPct(r.beatsNaivePct) }}</td>
              <td class="fe__num">{{ fmtCov(r.avgCoverageP98) }}</td>
            </tr>
            <tr v-if="!vm.byType.length"><td colspan="5" class="fe__empty">—</td></tr>
          </tbody>
        </table>
      </section>

      <section class="fe__pnl">
        <div class="fe__pnl-hd">模型对比</div>
        <table class="fe__table">
          <thead><tr><th>模型</th><th class="fe__num">中位MASE</th><th class="fe__num">胜Naive%</th><th class="fe__num">覆盖</th><th>生产</th></tr></thead>
          <tbody>
            <tr v-for="m in vm.models" :key="m.modelName" :class="{ 'fe__row--prod': m.isProduction }">
              <td>{{ m.modelName }}</td>
              <td class="fe__num">{{ fmtMase(m.medianMase) }}</td>
              <td class="fe__num">{{ fmtPct(m.beatsNaivePct) }}</td>
              <td class="fe__num">{{ fmtCov(m.avgCoverageP98) }}</td>
              <td>{{ m.isProduction ? "★" : "" }}</td>
            </tr>
            <tr v-if="!vm.models.length"><td colspan="5" class="fe__empty">—</td></tr>
          </tbody>
        </table>
      </section>
    </template>
  </main>
</template>

<style scoped>
.fe { padding: var(--sp-6); max-width: 1200px; margin: 0 auto; }
.fe__msg { color: var(--ink-1); }
.fe__error { color: var(--error); }
.fe__banner {
  background: var(--warn-subtle); border: 1px solid var(--line-soft);
  border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); margin-bottom: var(--sp-4);
  color: var(--ink-1);
}
.fe__kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-4); margin-bottom: var(--sp-6); }
.fe__kpi { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-4); border: 1px solid var(--line-soft); border-radius: var(--r-md); }
.fe__kpi-v { font-family: var(--mono); font-size: var(--fs-xl); font-weight: 700; color: var(--accent); }
.fe__kpi-l { font-size: var(--fs-sm); color: var(--ink-2); }
.fe__tiers { margin-bottom: var(--sp-6); }
.fe__tiers-label { font-size: var(--fs-sm); color: var(--ink-2); }
.fe__bar { display: flex; height: 12px; border-radius: var(--r-sm); overflow: hidden; margin: var(--sp-2) 0; background: var(--line-soft); }
.fe__seg--high { background: var(--accent); }
.fe__seg--medium { background: var(--warn); }
.fe__seg--low { background: var(--ink-3); }
.fe__legend { display: flex; gap: var(--sp-4); font-size: var(--fs-sm); color: var(--ink-1); }
.fe__dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.fe__dot--high { background: var(--accent); }
.fe__dot--medium { background: var(--warn); }
.fe__dot--low { background: var(--ink-3); }
.fe__pnl { margin-bottom: var(--sp-6); border: 1px solid var(--line-soft); border-radius: var(--r-md); overflow: hidden; }
.fe__pnl-hd { padding: var(--sp-3) var(--sp-4); font-weight: 600; border-bottom: 1px solid var(--line-soft); }
.fe__table { width: 100%; border-collapse: collapse; }
.fe__table th, .fe__table td { padding: var(--sp-2) var(--sp-4); text-align: left; border-bottom: 1px solid var(--line-soft); font-size: var(--fs-sm); }
.fe__num { text-align: right; font-family: var(--mono); }
.fe__row--prod { background: var(--accent-subtle); }
.fe__empty { color: var(--ink-3); text-align: center; }
</style>
