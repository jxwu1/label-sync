import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import SupplierOverview from "./SupplierOverview.vue";

describe("SupplierOverview", () => {
  it("点 chip emit select-supplier", () => {
    const w = mount(SupplierOverview, { props: {
      rows: [{ supplier_id: "GR1", count: 3, hot_count: 2, max: 90 }],
      expanded: false, activeSupplier: null,
    }});
    w.find(".sup-chip").trigger("click");
    expect(w.emitted("select-supplier")?.[0]).toEqual(["GR1"]);
  });
  it("toggle-expand", () => {
    const w = mount(SupplierOverview, { props: { rows: [], expanded: false, activeSupplier: null } });
    w.find(".sup-strip-more").trigger("click");
    expect(w.emitted("toggle-expand")).toBeTruthy();
  });
});
