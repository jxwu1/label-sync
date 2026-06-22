import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, ApiError, UnauthenticatedError } from "../api/client";
import type { RestockDetail, RestockDetailResponse } from "../api/types.gen";

type Entry = "loading" | "ready" | "missing" | "error";

// 闭包级【非响应式】合并表——Promise 不进 reactive state
const inflight = new Map<string, Promise<void>>();

export const useRestockDetailStore = defineStore("restockDetail", () => {
  const entries = ref<Record<string, Entry>>({});
  const cache = ref<Record<string, RestockDetail>>({});
  const errorMsg = ref<Record<string, string>>({});

  function load(bc: string): Promise<void> {
    if (cache.value[bc]) { entries.value[bc] = "ready"; return Promise.resolve(); }
    if (inflight.has(bc)) return inflight.get(bc)!;
    entries.value[bc] = "loading";
    const p = (async () => {
      try {
        const data = await apiGet<RestockDetailResponse>(`/api/restock/${encodeURIComponent(bc)}/detail`);
        cache.value[bc] = data.detail;
        entries.value[bc] = "ready";
      } catch (e) {
        if (e instanceof UnauthenticatedError) return; // 401 中性，apiGet 已跳登录
        if (e instanceof ApiError && e.status === 404) { entries.value[bc] = "missing"; return; }
        entries.value[bc] = "error";
        errorMsg.value[bc] = (e as Error).message; // 500/网络：不写 cache，重开可重试
      } finally {
        inflight.delete(bc);
      }
    })();
    inflight.set(bc, p);
    return p;
  }

  return { entries, cache, errorMsg, load };
});
