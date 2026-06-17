import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { SkuAnalyticsData } from "../api/types.gen";
import { normalizeAnalytics } from "../pages/history/analytics-normalize";
import type { AnalyticsVM } from "../pages/history/analytics-types";

export const useSkuAnalyticsStore = defineStore("skuAnalytics", () => {
  const vm = ref<AnalyticsVM | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load(barcode: string) {
    loading.value = true;
    error.value = null;
    vm.value = null; // 开查询即清旧 VM：失败/401 后不残留上次分析（HC-A4 状态卫生）
    try {
      const raw = await apiGet<SkuAnalyticsData>(`/api/history/${encodeURIComponent(barcode)}/analytics`);
      vm.value = normalizeAnalytics(raw);
    } catch (e) {
      if (e instanceof UnauthenticatedError) return; // 401 走全局跳转，不写块内 error
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  function reset() {
    vm.value = null;
    error.value = null;
    loading.value = false;
  }

  return { vm, loading, error, load, reset };
});
