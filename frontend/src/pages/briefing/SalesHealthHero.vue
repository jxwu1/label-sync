<script setup lang="ts">
import { computed } from "vue";
import type { SalesHealthVM, Unavailable } from "./types";

const props = defineProps<{ vm: SalesHealthVM | Unavailable }>();

const DEGRADED: Record<string, string> = {
  week_incomplete: "数据周未完整，本批次暂不给环比结论。",
  coverage_insufficient: "销售口径覆盖不足，本批次暂不给环比结论。",
  no_previous_week: "上一完整周无数据，仅显示本批次销量。",
};

const isOk = computed(() => props.vm.available && props.vm.status === "ok");
const degradedMsg = computed(() =>
  props.vm.available && props.vm.status !== "ok" ? DEGRADED[props.vm.status] : "",
);
const deltaText = computed(() => {
  if (!props.vm.available || props.vm.deltaPct === null) return "";
  const v = props.vm.deltaPct;
  return `${v > 0 ? "+" : ""}${v}%`;
});
const tone = computed(() => {
  if (!props.vm.available || props.vm.deltaPct === null) return "neutral";
  return props.vm.deltaPct >= 0 ? "up" : "down";
});
</script>

<template>
  <section class="hero" :class="`hero--${tone}`">
    <div class="hero__label">本批次销售健康</div>

    <template v-if="!vm.available">
      <div class="hero__na">暂不可用</div>
    </template>

    <template v-else-if="isOk">
      <div class="hero__delta">{{ deltaText }}</div>
      <div class="hero__sub">
        本批次清洗后销量较上批 {{ deltaText }}（{{ vm.previousQty }} → {{ vm.currentQty }} 件）<br />
        <template v-if="vm.forecastNextTotal !== null">下期系统预期约 {{ vm.forecastNextTotal }} 件</template>
        <template v-if="vm.modelBiasUnits !== null"> · 模型近期校准：回测整体偏移 {{ vm.modelBiasUnits }} 件/周</template>
      </div>
    </template>

    <template v-else>
      <div class="hero__degraded">{{ degradedMsg }}</div>
      <div v-if="vm.currentQty !== null" class="hero__sub">本批次销量 {{ vm.currentQty }} 件</div>
    </template>
  </section>
</template>

<style scoped>
.hero {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-left: 3px solid var(--ink-2);
  border-radius: var(--r-md);
  padding: var(--sp-5) var(--sp-6);
}
.hero--up { border-left-color: var(--success); }
.hero--down { border-left-color: var(--error); }
.hero__label {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-2);
}
.hero__delta {
  font-family: var(--mono);
  font-size: var(--fs-4xl);
  color: var(--ink-0);
  line-height: 1.1;
  margin: var(--sp-2) 0;
}
.hero--up .hero__delta { color: var(--success); }
.hero--down .hero__delta { color: var(--error); }
.hero__sub { font-size: var(--fs-base); color: var(--ink-1); }
.hero__degraded { font-size: var(--fs-lg); color: var(--ink-1); margin-top: var(--sp-2); }
.hero__na { font-size: var(--fs-base); color: var(--ink-2); margin-top: var(--sp-2); }
</style>
