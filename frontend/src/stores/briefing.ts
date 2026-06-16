import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { BriefingData } from "../api/types.gen";
import { normalizeBriefing } from "../pages/briefing/normalize";
import type { BriefingViewModel } from "../pages/briefing/types";

export const useBriefingStore = defineStore("briefing", () => {
  const vm = ref<BriefingViewModel | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      const raw = await apiGet<BriefingData>("/api/briefing/data");
      vm.value = normalizeBriefing(raw);
    } catch (e) {
      // 未登录由 apiGet 的跳转接管 UX，不渲染一闪而过的误导性错误文案
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  return { vm, loading, error, load };
});
