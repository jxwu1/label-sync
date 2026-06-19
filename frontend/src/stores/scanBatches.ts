import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { ScanBatchList } from "../api/types.gen";
import { normalizeBatches } from "../pages/history/scan-batch-normalize";
import type { ScanBatchVM } from "../pages/history/scan-batch-types";

export const useScanBatchesStore = defineStore("scanBatches", () => {
  const batches = ref<ScanBatchVM[]>([]);
  const employeeFilter = ref<string | null>(null); // null = 全部员工
  const expanded = ref<Set<string>>(new Set());     // 展开的 batchId，多行并存
  const loading = ref(false);
  const error = ref<string | null>(null);
  const loaded = ref(false);
  let inflight = false;
  let batchesGen = 0, initGen = 0;

  async function ensureLoaded() {
    if (loaded.value || inflight) return;
    const my = ++initGen;
    inflight = true;
    try { await loadBatches(); }
    finally { if (my === initGen) inflight = false; }
  }

  // 不变量：loadBatches 吞掉所有非 401 错误（不 rethrow）→ ensureLoaded 的 await 永不 reject，
  // finally 必清 inflight，故 inflight 不会死锁。若日后给本函数加 throw，必须同步审查 ensureLoaded。
  async function loadBatches() {
    const my = ++batchesGen;
    loading.value = true; error.value = null;
    try {
      const raw = await apiGet<ScanBatchList>("/api/history/scan-batches");
      if (my !== batchesGen) return;
      batches.value = normalizeBatches(raw);
      loaded.value = true;
    } catch (e) {
      if (my !== batchesGen) return;
      if (e instanceof UnauthenticatedError) return; // 401 不落 error
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === batchesGen) loading.value = false;
    }
  }

  const employees = computed(() =>
    [...new Set(batches.value.map((b) => b.employee))].sort());
  const filteredBatches = computed(() =>
    employeeFilter.value ? batches.value.filter((b) => b.employee === employeeFilter.value) : batches.value);

  function setEmployeeFilter(name: string | null) { employeeFilter.value = name; }
  function toggleExpand(batchId: string) {
    const next = new Set(expanded.value);
    next.has(batchId) ? next.delete(batchId) : next.add(batchId);
    expanded.value = next;
  }
  function reset() {
    batchesGen++; initGen++; loaded.value = false; inflight = false;
    batches.value = []; employeeFilter.value = null; expanded.value = new Set();
    loading.value = false; error.value = null;
  }

  return { batches, employeeFilter, expanded, loading, error, loaded,
           employees, filteredBatches,
           ensureLoaded, loadBatches, setEmployeeFilter, toggleExpand, reset };
});
