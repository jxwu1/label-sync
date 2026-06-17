import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { ForecastEvalData } from "../api/types.gen";
import { normalizeForecastEval } from "../pages/forecast-eval/normalize";
import type { ForecastEvalViewModel } from "../pages/forecast-eval/types";

export const useForecastEvalStore = defineStore("forecastEval", () => {
  const vm = ref<ForecastEvalViewModel | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      const raw = await apiGet<ForecastEvalData>("/api/forecast-eval/data");
      vm.value = normalizeForecastEval(raw);
    } catch (e) {
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  return { vm, loading, error, load };
});
