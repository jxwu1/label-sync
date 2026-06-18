import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { SkuExtrasResponse } from "../api/types.gen";
import { normalizeExtras } from "../pages/history/extras-normalize";
import type { ExtrasPageVM } from "../pages/history/extras-types";

export const useSkuExtrasStore = defineStore("skuExtras", () => {
  const vm = ref<ExtrasPageVM | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  let seq = 0; // HC-B7 单调 request-id（闭包级，测试隔离）

  async function load(barcode: string) {
    const my = ++seq;
    loading.value = true;
    error.value = null;
    vm.value = null;
    try {
      const raw = await apiGet<SkuExtrasResponse>(
        `/api/history/${encodeURIComponent(barcode)}/analytics/extras`,
      );
      if (my !== seq) return;
      vm.value = normalizeExtras(raw);
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
