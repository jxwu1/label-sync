import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import Badge from "./Badge.vue";
import Card from "./Card.vue";
import PageHeader from "./PageHeader.vue";

describe("基础组件", () => {
  it("Card 渲染标题与默认插槽", () => {
    const w = mount(Card, { props: { title: "销售健康" }, slots: { default: "<p>body</p>" } });
    expect(w.text()).toContain("销售健康");
    expect(w.html()).toContain("<p>body</p>");
  });

  it("Badge 按 tone 切换样式类", () => {
    const ok = mount(Badge, { props: { tone: "ok" }, slots: { default: "正常" } });
    const warn = mount(Badge, { props: { tone: "warn" }, slots: { default: "注意" } });
    expect(ok.classes()).not.toEqual(warn.classes());
    expect(ok.text()).toBe("正常");
  });

  it("PageHeader 渲染标题与副标题", () => {
    const w = mount(PageHeader, { props: { title: "晨间简报", subtitle: "2026-06-08 周" } });
    expect(w.text()).toContain("晨间简报");
    expect(w.text()).toContain("2026-06-08");
  });
});
