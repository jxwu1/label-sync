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
  let seq = 0; // HC-B7 单调 request-id（闭包级，测试隔离）

  async function load(q: string): Promise<boolean> {
    const my = ++seq;
    loading.value = true;
    error.value = null;
    result.value = null;   // 开查询即清旧结果：失败/401 时不残留上次 hit（防 RECENT 误写）
    try {
      const raw = await apiGet<HistorySearchData>(`/api/history?q=${encodeURIComponent(q)}`);
      if (my !== seq) return false;
      result.value = normalizeHistory(raw);
    } catch (e) {
      if (my !== seq) return false;
      if (e instanceof UnauthenticatedError) return false;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === seq) loading.value = false;
    }
    return my === seq;
  }

  function reset() {
    seq++; // HC-B7: 作废 pending
    result.value = null;
    error.value = null;
    loading.value = false;
  }

  return { result, loading, error, load, reset };
});
