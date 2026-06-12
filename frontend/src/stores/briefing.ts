import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet } from "../api/client";
import type { BriefingData } from "../api/types.gen";

export const useBriefingStore = defineStore("briefing", () => {
  const data = ref<BriefingData | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      data.value = await apiGet<BriefingData>("/api/briefing/data");
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  return { data, loading, error, load };
});
