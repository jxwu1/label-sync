<script setup lang="ts">
import { computed, onMounted } from "vue";
import PageHeader from "../../components/PageHeader.vue";
import { useBriefingStore } from "../../stores/briefing";
import ActionList from "./ActionList.vue";
import SalesHealthHero from "./SalesHealthHero.vue";
import StatCard from "./StatCard.vue";

const store = useBriefingStore();
onMounted(() => store.load());

const vm = computed(() => store.vm);

const subtitle = computed(() => {
  if (!vm.value) return undefined;
  const dh = vm.value.dataHealth;
  const imp = dh.available && dh.lastImportDate ? ` · 数据刷新于 ${dh.lastImportDate}` : "";
  return `数据周 ${vm.value.dataWeek ?? "—"}${imp}`;
});

const staleBanner = computed(() => {
  const v = vm.value;
  if (!v || !v.dataHealth.available) return null;
  const dh = v.dataHealth;
  if (!dh.stale && !dh.scrapeStale) return null;
  return dh.daysSince === null ? "数据刷新时间未知，请检查抓取任务" : `数据已超过 ${dh.daysSince} 天未刷新`;
});

const isEmpty = computed(() => !!vm.value && vm.value.dataWeek === null);

// 行动清单列定义
const restockCols = [
  { key: "model", label: "型号" },
  { key: "p50", label: "建议量" },
  { key: "cover", label: "可售周" },
];
const followCols = [
  { key: "supplier", label: "供应商" },
  { key: "qty", label: "数量" },
  { key: "overdue", label: "逾期" },
];
const reviewCols = [
  { key: "kind", label: "类型" },
  { key: "count", label: "数量" },
];

const restockRows = computed(() =>
  vm.value && vm.value.restockAction.available
    ? vm.value.restockAction.items.map((i) => ({ model: i.model, p50: i.restockQtyP50, cover: i.weeksOfCover }))
    : [],
);
const followRows = computed(() =>
  vm.value && vm.value.followUpAction.available
    ? vm.value.followUpAction.items.map((i) => ({
        supplier: i.supplierName,
        qty: i.totalQty,
        overdue: i.overdueState === "overdue" ? `逾期 ${i.overdueDays} 天` : i.overdueState === "not_due" ? "未到期" : "—",
      }))
    : [],
);
const reviewRows = computed(() =>
  vm.value && vm.value.reviewAction.available
    ? vm.value.reviewAction.items.map((i) => ({ kind: i.kind, count: i.count }))
    : [],
);

// 状态卡文案
function eur(n: number | null): string {
  return n === null ? "—" : `€${Math.round(n).toLocaleString()}`;
}
const restockStat = computed(() => {
  const c = vm.value?.restockRisk;
  return c?.available ? { value: `${c.total} 项`, hint: `其中 ${c.urgent} 个紧急（可售 ≤ 2 周）` } : null;
});
const stockoutStat = computed(() => {
  const c = vm.value?.stockoutImpact;
  return c?.available ? { value: `${c.total} 项`, hint: "近期零销疑因缺货" } : null;
});
const overstockStat = computed(() => {
  const c = vm.value?.overstockRisk;
  if (!c?.available) return null;
  return c.costAvailable
    ? { value: eur(c.overstockValueEur), hint: `${c.total} 个滞销 SKU · ${c.stockQty.toLocaleString()} 件` }
    : { value: `${c.stockQty.toLocaleString()} 件`, hint: `${c.total} 个滞销 SKU · 无成本数据` };
});
const dataStat = computed(() => {
  const c = vm.value?.dataHealth;
  if (!c?.available) return null;
  const since = c.daysSince === null ? "刷新时间未知" : `距今 ${c.daysSince} 天`;
  const cov = c.costCoveragePct === null ? "" : ` · 成本覆盖 ${c.costCoveragePct}%`;
  return { value: c.stale || c.scrapeStale ? "注意" : "正常", hint: `${since}${cov}` };
});
</script>

<template>
  <main class="briefing">
    <PageHeader title="晨间简报" :subtitle="subtitle" />

    <p v-if="store.loading" class="briefing__msg">加载中…</p>
    <p v-else-if="store.error" class="briefing__error">{{ store.error }}</p>
    <p v-else-if="isEmpty" class="briefing__msg">本批次暂无完整数据周</p>

    <template v-else-if="vm">
      <div v-if="staleBanner" class="briefing__stale">{{ staleBanner }}</div>

      <SalesHealthHero :vm="vm.salesHealth" />

      <div class="briefing__grouplabel">今天要动手的</div>
      <div class="briefing__actions">
        <ActionList title="建议补货" :total="vm.restockAction.available ? vm.restockAction.total : 0" href="/?page=restock"
          :columns="restockCols" :rows="restockRows" :available="vm.restockAction.available" empty-text="暂无补货建议" />
        <ActionList title="建议催 / 确认" :total="vm.followUpAction.available ? vm.followUpAction.total : 0" href="/?page=purchase"
          :columns="followCols" :rows="followRows" :available="vm.followUpAction.available" empty-text="暂无采购订单" />
        <ActionList title="建议复查异常" :total="vm.reviewAction.available ? vm.reviewAction.total : 0" href="/?page=data_quality"
          :columns="reviewCols" :rows="reviewRows" :available="vm.reviewAction.available" empty-text="暂无异常" />
      </div>

      <div class="briefing__grouplabel">状态</div>
      <div class="briefing__stats">
        <StatCard label="补货风险" :available="!!restockStat" :value="restockStat?.value" :hint="restockStat?.hint" />
        <StatCard label="缺货影响" :available="!!stockoutStat" :value="stockoutStat?.value" :hint="stockoutStat?.hint" />
        <StatCard label="压货风险" :available="!!overstockStat" :value="overstockStat?.value" :hint="overstockStat?.hint" />
        <StatCard label="数据健康" :available="!!dataStat" :value="dataStat?.value" :hint="dataStat?.hint" />
      </div>
    </template>
  </main>
</template>

<style scoped>
.briefing { padding: var(--sp-6); max-width: 1200px; margin: 0 auto; }
.briefing__msg { color: var(--ink-1); }
.briefing__error { color: var(--error); }
.briefing__stale {
  background: var(--error-subtle);
  border: 1px solid var(--error-subtle-border);
  color: var(--error);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-4);
  font-size: var(--fs-base);
}
.briefing__grouplabel {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  letter-spacing: 0.05em;
  margin: var(--sp-6) 0 var(--sp-3);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--line-soft);
}
.briefing__actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-4); }
.briefing__stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-4); }
</style>
