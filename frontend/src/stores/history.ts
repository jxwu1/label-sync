import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { HistorySearchData } from "../api/types.gen";
import { normalizeHistory } from "../pages/history/normalize";
import type { HistoryResult } from "../pages/history/types";

export const useHistoryStore = defineStore("history", () => {
  const result = ref<HistoryResult | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load(q: string) {
    loading.value = true;
    error.value = null;
    result.value = null;   // 开查询即清旧结果：失败/401 时不残留上次 hit（防 RECENT 误写）
    try {
      const raw = await apiGet<HistorySearchData>(`/api/history?q=${encodeURIComponent(q)}`);
      result.value = normalizeHistory(raw);
    } catch (e) {
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  function reset() {
    result.value = null;
    error.value = null;
    loading.value = false;
  }

  return { result, loading, error, load, reset };
});
