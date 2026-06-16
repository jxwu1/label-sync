import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import StatCard from "./StatCard.vue";

describe("StatCard", () => {
  it("available → 渲染 label/value/hint", () => {
    const w = mount(StatCard, { props: { label: "补货风险", value: "38 项", hint: "其中 12 个紧急", available: true } });
    expect(w.text()).toContain("补货风险");
    expect(w.text()).toContain("38 项");
    expect(w.text()).toContain("其中 12 个紧急");
  });
  it("unavailable → 显「暂不可用」，不渲染 value", () => {
    const w = mount(StatCard, { props: { label: "压货风险", value: "€83k", available: false } });
    expect(w.text()).toContain("暂不可用");
    expect(w.text()).not.toContain("€83k");
  });
});
