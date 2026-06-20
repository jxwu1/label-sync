import { describe, it, expect } from "vitest";
import { filterPredicate, type FilterCtx } from "./filter";
import { INITIAL_FILTER, type FilterState } from "./constants";

const EMPTY: FilterCtx = { ordered: {}, suppressed: {}, selected: new Set() };
function item(p: Partial<any> = {}): any {
  return {
    barcode: "b1", model: "M1", name_zh: "名", origin: "FOREIGN", supplier_id: "GR1",
    is_truly_discontinued: false, is_new_item: false, urgency_score: 80,
    weeks_of_cover: 3, ...p,
  };
}
function f(p: Partial<FilterState> = {}): FilterState {
  return { ...INITIAL_FILTER, ...p };
}

describe("filterPredicate", () => {
  it("ordered 隐藏（show_ordered=false）", () => {
    expect(filterPredicate(item(), f(), { ...EMPTY, ordered: { b1: {} } })).toBe(false);
  });
  it("suppressed 默认隐藏；skipped band 只看 suppressed", () => {
    const ctx = { ...EMPTY, suppressed: { b1: {} } };
    expect(filterPredicate(item(), f(), ctx)).toBe(false);
    expect(filterPredicate(item(), f({ band: "skipped" }), ctx)).toBe(true);
    expect(filterPredicate(item({ barcode: "b2" }), f({ band: "skipped" }), ctx)).toBe(false);
  });
  it("origin 不匹配剔除（红队 FOREIGN 排除 CN）", () => {
    expect(filterPredicate(item({ origin: "CN" }), f({ origin: "FOREIGN" }), EMPTY)).toBe(false);
  });
  it("coverMax 仅在 active 视图生效", () => {
    const it = item({ weeks_of_cover: 8 });
    expect(filterPredicate(it, f({ coverMax: 4 }), EMPTY)).toBe(false);
    const disc = item({ weeks_of_cover: 8, is_truly_discontinued: true });
    expect(filterPredicate(disc, f({ coverMax: 4, views: { active: false, new: false, disc: true } }), EMPTY)).toBe(true);
  });
  it("band=ok 保留 urgency_score=null 行", () => {
    expect(filterPredicate(item({ urgency_score: null }), f({ band: "ok", origin: "" }), EMPTY)).toBe(true);
  });
  it("skipSupplier 忽略 supplier 过滤", () => {
    const it = item({ supplier_id: "GR2" });
    expect(filterPredicate(it, f({ supplier: "GR1" }), EMPTY)).toBe(false);
    expect(filterPredicate(it, f({ supplier: "GR1" }), EMPTY, { skipSupplier: true })).toBe(true);
  });
});
