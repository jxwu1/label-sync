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
});
