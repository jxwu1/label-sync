import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SalesHealthHero from "./SalesHealthHero.vue";
import type { SalesHealthVM } from "./types";

const ok: SalesHealthVM = {
  available: true, status: "ok", deltaPct: 12, currentQty: 4715, previousQty: 4210,
  forecastNextP50: 380, modelBiasUnits: 6, coveredSkus: 42,
};

describe("SalesHealthHero", () => {
  it("status ok → 显 delta% + 副信息", () => {
    const w = mount(SalesHealthHero, { props: { vm: ok } });
    expect(w.text()).toContain("+12%");
    expect(w.text()).toContain("380");
  });
  it("status coverage_insufficient → 不显 delta%，显覆盖不足文案", () => {
    const w = mount(SalesHealthHero, { props: { vm: { ...ok, status: "coverage_insufficient", deltaPct: null } } });
    expect(w.text()).not.toContain("%");
    expect(w.text()).toContain("覆盖不足");
  });
  it("unavailable → 暂不可用", () => {
    const w = mount(SalesHealthHero, { props: { vm: { available: false } } });
    expect(w.text()).toContain("暂不可用");
  });
});
