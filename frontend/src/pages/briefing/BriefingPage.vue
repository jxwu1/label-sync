<script setup lang="ts">
import { onMounted } from "vue";
import Badge from "../../components/Badge.vue";
import Card from "../../components/Card.vue";
import PageHeader from "../../components/PageHeader.vue";
import { useBriefingStore } from "../../stores/briefing";

const store = useBriefingStore();
onMounted(() => store.load());

const cardTitles: Record<string, string> = {
  sales_health: "销售健康",
  restock_risk: "补货风险",
  stockout_impact: "缺货影响",
  overstock_risk: "压货风险",
  data_health: "数据健康",
};

function isOk(card: Record<string, unknown>): boolean {
  return card.ok === true;
}
</script>

<template>
  <main class="briefing">
    <PageHeader
      title="晨间简报"
      :subtitle="store.data ? `数据周 ${store.data.data_week ?? '—'}` : undefined"
    />
    <p v-if="store.loading">加载中…</p>
    <p v-else-if="store.error" class="error">{{ store.error }}</p>
    <div v-else-if="store.data" class="cards">
      <Card
        v-for="(card, key) in store.data.cards"
        :key="key"
        :title="cardTitles[key] ?? key"
      >
        <Badge :tone="isOk(card) ? 'ok' : 'danger'">{{ isOk(card) ? "正常" : "异常" }}</Badge>
        <pre class="card-raw">{{ card }}</pre>
      </Card>
    </div>
  </main>
</template>

<style scoped>
.briefing { padding: var(--sp-6); max-width: 1100px; margin: 0 auto; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: var(--sp-4); }
.error { color: var(--error); }
.card-raw { font-size: var(--fs-sm); overflow: auto; }
</style>
