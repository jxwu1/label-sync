import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { RecentChangesBatchList, RecentChangesDetail } from "../api/types.gen";
import { normalizeBatches, normalizeDetail } from "../pages/history/recent-changes-normalize";
import type { RecentBatchVM, RecentSummaryVM, ChangeRowVM } from "../pages/history/recent-changes-types";

export const useRecentChangesStore = defineStore("recentChanges", () => {
  const batches = ref<RecentBatchVM[]>([]);
  const selectedBatchId = ref<number | null>(null);
  const summary = ref<RecentSummaryVM | null>(null);
  const changes = ref<ChangeRowVM[]>([]);
  const totalCount = ref(0);
  const mode = ref<"collapsed" | "raw">("collapsed");
  const filter = ref<{ field: string | null; changeType: string | null }>({ field: null, changeType: null });
  const loading = ref(false);       // batches 级
  const error = ref<string | null>(null);
  const detailLoading = ref(false); // per-batch 级
  const detailError = ref<string | null>(null);
  const loaded = ref(false);
  let inflight = false;
  let batchesGen = 0, detailSeq = 0, initGen = 0;

  async function ensureLoaded() {
    if (loaded.value || inflight) return;
    const my = ++initGen;
    inflight = true;
    try { await loadBatches(); }
    finally { if (my === initGen) inflight = false; }
  }

  async function loadBatches() {
    const my = ++batchesGen;
    loading.value = true; error.value = null;
    try {
      const raw = await apiGet<RecentChangesBatchList>("/api/history/recent-changes/batches");
      if (my !== batchesGen) return;
      batches.value = normalizeBatches(raw);
      loaded.value = true;
      if (batches.value.length) await selectBatch(batches.value[0].batchId);
      else { summary.value = null; changes.value = []; totalCount.value = 0; }
    } catch (e) {
      if (my !== batchesGen) return;
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === batchesGen) loading.value = false;
    }
  }

  async function loadDetail() {
    if (selectedBatchId.value === null) return;
    const my = ++detailSeq;
    const bid = selectedBatchId.value;
    detailLoading.value = true; detailError.value = null;
    const params = new URLSearchParams({ mode: mode.value });
    if (filter.value.field) params.set("field", filter.value.field);
    if (filter.value.changeType) params.set("change_type", filter.value.changeType);
    try {
      const raw = await apiGet<RecentChangesDetail>(
        `/api/history/recent-changes/${bid}/changes?${params.toString()}`);
      if (my !== detailSeq) return;
      const vm = normalizeDetail(raw);
      summary.value = vm.summary; changes.value = vm.changes; totalCount.value = vm.totalCount;
    } catch (e) {
      if (my !== detailSeq) return;
      if (e instanceof UnauthenticatedError) return;
      detailError.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === detailSeq) detailLoading.value = false;
    }
  }

  async function selectBatch(id: number) {
    selectedBatchId.value = id;
    filter.value = { field: null, changeType: null };
    await loadDetail();
  }
  async function setMode(m: "collapsed" | "raw") { mode.value = m; await loadDetail(); }
  async function setFilter(f: { field: string | null; changeType: string | null }) { filter.value = f; await loadDetail(); }
  function reset() {
    batchesGen++; detailSeq++; initGen++; loaded.value = false; inflight = false;
    batches.value = []; selectedBatchId.value = null; summary.value = null;
    changes.value = []; totalCount.value = 0; mode.value = "collapsed";
    filter.value = { field: null, changeType: null };
    loading.value = false; error.value = null; detailLoading.value = false; detailError.value = null;
  }

  return { batches, selectedBatchId, summary, changes, totalCount, mode, filter,
           loading, error, detailLoading, detailError, loaded,
           ensureLoaded, loadBatches, loadDetail, selectBatch, setMode, setFilter, reset };
});
