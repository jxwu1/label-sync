import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import FilterBar from "./FilterBar.vue";
import { INITIAL_FILTER, type FilterState } from "./constants";

const emittedFilter = (w: ReturnType<typeof mount>): FilterState =>
  w.emitted("update")?.[0]?.[0] as FilterState;

describe("FilterBar", () => {
  it("点『已跳过』emit band=skipped", () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER } } });
    w.find('[data-band="skipped"]').trigger("click");
    expect(emittedFilter(w).band).toBe("skipped");
  });
  it("再点同一 band 回到 all", () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER, band: "urgent" } } });
    w.find('[data-band="urgent"]').trigger("click");
    expect(emittedFilter(w).band).toBe("all");
  });
  it("重置 emit origin='' 且 coverMax=null", () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER, origin: "FOREIGN", coverMax: 4 } } });
    w.find(".rs-reset").trigger("click");
    const f = emittedFilter(w);
    expect(f.origin).toBe(""); expect(f.coverMax).toBe(null);
  });
  it("可撑滑块范围 0.5–20 / step 0.5（对齐旧 rsCfRange）", () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER } } });
    const range = w.find(".rs-cf-range");
    expect(range.attributes("min")).toBe("0.5");
    expect(range.attributes("max")).toBe("20");
    expect(range.attributes("step")).toBe("0.5");
  });
  it("可撑滑块改值 emit 该值（支持 0.5 粒度）", () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER } } });
    const input = w.find(".rs-cf-range");
    (input.element as HTMLInputElement).value = "6.5";
    input.trigger("input");
    expect(emittedFilter(w).coverMax).toBe(6.5);
  });
  it("『不限』× 单独清 coverMax→null，不动其他筛选", () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER, origin: "FOREIGN", coverMax: 4 } } });
    w.find(".rs-cf-clear").trigger("click");
    const f = emittedFilter(w);
    expect(f.coverMax).toBe(null);
    expect(f.origin).toBe("FOREIGN"); // 其他筛选保留
  });
  it("coverMax=null 时不渲染清除 ×", () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER, coverMax: null } } });
    expect(w.find(".rs-cf-clear").exists()).toBe(false);
  });
  it("清 coverMax 后滑块保留清除前位置（不复位到 4）", async () => {
    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER, coverMax: 12 } } });
    // 父把 coverMax 置 null（模拟点 × 后的回流）
    await w.setProps({ filter: { ...INITIAL_FILTER, coverMax: null } });
    expect((w.find(".rs-cf-range").element as HTMLInputElement).value).toBe("12"); // 保留 12，非 4
  });
  it("供应商 tag 仅在 supplier 非空时渲染，× 清 supplier 保留其他筛选", () => {
    const none = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER, supplier: null } } });
    expect(none.find(".rs-supplier-tag").exists()).toBe(false);

    const w = mount(FilterBar, { props: { filter: { ...INITIAL_FILTER, supplier: "GR001", coverMax: null, search: "abc" } } });
    expect(w.find(".rs-supplier-tag-val").text()).toBe("GR001");
    w.find(".rs-supplier-tag-x").trigger("click");
    const f = emittedFilter(w);
    expect(f.supplier).toBe(null);
    expect(f.coverMax).toBe(null); // 凑单态保留
    expect(f.search).toBe("abc");  // 其他筛选保留
  });
});
