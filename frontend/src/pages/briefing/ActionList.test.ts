import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ActionList from "./ActionList.vue";

const columns = [
  { key: "model", label: "型号" },
  { key: "qty", label: "建议量" },
];
const rows = [
  { model: "34249", qty: 120 },
  { model: "25778", qty: 80 },
];

describe("ActionList", () => {
  it("渲染标题、行、查看全部链接（href）", () => {
    const w = mount(ActionList, { props: { title: "建议补货", total: 38, href: "/?page=restock", columns, rows } });
    expect(w.text()).toContain("建议补货");
    expect(w.text()).toContain("34249");
    const a = w.get("a.action__more");
    expect(a.attributes("href")).toBe("/?page=restock");
    expect(a.attributes("href")).not.toContain(" ");
  });
  it("空 rows → 显空态文案", () => {
    const w = mount(ActionList, { props: { title: "建议催单", total: 0, href: "/?page=purchase", columns, rows: [], emptyText: "暂无采购订单" } });
    expect(w.text()).toContain("暂无采购订单");
  });
  it("unavailable → 暂不可用", () => {
    const w = mount(ActionList, { props: { title: "复查异常", total: 0, href: "/?page=data_quality", columns, rows: [], available: false } });
    expect(w.text()).toContain("暂不可用");
  });
});
