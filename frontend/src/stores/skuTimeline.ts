import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { SkuTimelineResponse } from "../api/types.gen";
import { normalizeTimeline } from "../pages/history/timeline-normalize";
import type { TimelineVM } from "../pages/history/timeline-types";

export const useSkuTimelineStore = defineStore("skuTimeline", () => {
  const vm = ref<TimelineVM | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  let seq = 0; // HC-B7 单调 request-id（闭包级）

  async function load(barcode: string) {
    const my = ++seq;
    loading.value = true;
    error.value = null;
    vm.value = null;
    try {
      const raw = await apiGet<SkuTimelineResponse>(
        `/api/history/${encodeURIComponent(barcode)}/timeline`,
      );
      if (my !== seq) return;
      vm.value = normalizeTimeline(raw);
    } catch (e) {
      if (my !== seq) return;
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === seq) loading.value = false;
    }
  }

  function reset() {
    seq++; // HC-B7: 作废 pending
    vm.value = null;
    error.value = null;
    loading.value = false;
  }

  return { vm, loading, error, load, reset };
});
