import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import KpiCards from "./KpiCards.vue";

describe("KpiCards", () => {
  it("渲染 4 个数字，无『已标记』", () => {
    const w = mount(KpiCards, { props: { kpi: { hot: 1, watch: 2, ok: 3, spend: 100 } } });
    expect(w.findAll(".rs-kpi").length).toBe(4);
    expect(w.text()).not.toContain("已标记");
    expect(w.text()).toContain("€100");
  });
});
