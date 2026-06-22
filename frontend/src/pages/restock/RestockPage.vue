<script setup lang="ts">
import { ref, shallowRef, computed, markRaw, onMounted } from "vue";
import { apiGet, UnauthenticatedError } from "../../api/client";
import type { RestockItemList, RestockSuppressedList } from "../../api/types.gen";
import { INITIAL_FILTER, INITIAL_SORT, THRESH, VISIBLE_CAP, type FilterState } from "./constants";
import { filterPredicate, type FilterCtx } from "./filter";
import { applySort, type SortState } from "./sort";
import { computeKpi } from "./kpi";
import { supplierSummary, allSuppliersSummary } from "./supplier-summary";
import { loadOrdered, saveOrdered, autoClearOrderedByPurchase } from "./ordered-store";
import { normalizeSuppressed } from "./suppressed-normalize";
import RestockTable from "./RestockTable.vue";
import FilterBar from "./FilterBar.vue";
import KpiCards from "./KpiCards.vue";
import SupplierOverview from "./SupplierOverview.vue";

const items = shallowRef<any[]>([]);
const suppressed = ref<Record<string, any>>({});
const ordered = ref<Record<string, { marked_at: string }>>({});
const filter = ref<FilterState>({ ...INITIAL_FILTER });
const sort = ref<SortState>({ ...INITIAL_SORT });
const supExpanded = ref(false);
const loadError = ref<string | null>(null);
const loaded = ref(false);

const ctx = computed<FilterCtx>(() => ({ ordered: ordered.value, suppressed: suppressed.value, selected: new Set<string>() }));
const filteredSorted = computed(() => applySort(items.value.filter((it) => filterPredicate(it, filter.value, ctx.value)), sort.value));
const kpi = computed(() => computeKpi(items.value, filter.value, ctx.value, filterPredicate));
const supRows = computed(() => supExpanded.value
  ? allSuppliersSummary(items.value, filter.value, ctx.value, filterPredicate)
  : supplierSummary(items.value, filter.value, ctx.value, filterPredicate).slice(0, THRESH.SUPPLIER_OVERVIEW_TOP));
const shownCount = computed(() => Math.min(filteredSorted.value.length, VISIBLE_CAP));

async function load() {
  loadError.value = null;
  try {
    ordered.value = loadOrdered();
    const data = await apiGet<RestockItemList>("/api/restock/items");
    items.value = markRaw(data.items as any[]);
    if (autoClearOrderedByPurchase(ordered.value, items.value)) saveOrdered(ordered.value);
    try {
      const s = await apiGet<RestockSuppressedList>("/api/restock/suppressed");
      suppressed.value = normalizeSuppressed(s);
    } catch { suppressed.value = {}; }
    loaded.value = true;
  } catch (e) {
    if (e instanceof UnauthenticatedError) return;
    loadError.value = (e as Error).message;
  }
}

function onSelectSupplier(bc: string) {
  filter.value = { ...filter.value, supplier: bc, coverMax: null };
}
function onSortChange(key: string) {
  // 同列切方向；异列换 key 默认 desc（restock.js:1298）
  sort.value = sort.value.key === key
    ? { key, dir: sort.value.dir === "asc" ? "desc" : "asc" }
    : { key, dir: "desc" };
}
function onUpdateFilter(f: FilterState) { filter.value = f; }
function onOpenHistory(bc: string) { location.href = "/ui/history?q=" + encodeURIComponent(bc); }

onMounted(load);
</script>

<template>
  <section id="pageRestock">
    <div class="rs-top"><KpiCards :kpi="kpi" /></div>
    <SupplierOverview :rows="supRows" :expanded="supExpanded" :active-supplier="filter.supplier"
      @select-supplier="onSelectSupplier" @toggle-expand="supExpanded = !supExpanded" />
    <FilterBar :filter="filter" @update="onUpdateFilter" />
    <p v-if="loadError" class="empty">加载失败：{{ loadError }}</p>
    <p v-else-if="!loaded" class="empty">加载中…</p>
    <RestockTable v-else :rows="filteredSorted" :cover-threshold="filter.coverThreshold" :sort="sort"
      @open-history="onOpenHistory" @select-supplier="onSelectSupplier" @sort-change="onSortChange" />
    <div v-if="loaded" class="rs-foot">
      <span class="rs-foot-stat">显示前 <b>{{ shownCount }}</b> / {{ filteredSorted.length }} 项</span>
    </div>
  </section>
</template>

<style scoped>
#pageRestock { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }
.rs-top { background: var(--bg-1); border-bottom: 1px solid var(--line-soft); flex-shrink: 0; padding: 12px 20px; }
.empty { text-align: center; color: var(--ink-2); padding: 40px; }
.rs-foot { display: flex; align-items: center; gap: 12px; padding: 8px 20px; background: var(--bg-1); border-top: 1px solid var(--line-soft); flex-shrink: 0; }
.rs-foot-stat { font-size: var(--fs-sm); font-family: var(--mono); color: var(--ink-2); }
.rs-foot-stat b { font-weight: 600; color: var(--ink-1); }
</style>
