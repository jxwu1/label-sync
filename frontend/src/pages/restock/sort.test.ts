import { describe, it, expect } from "vitest";
import { applySort } from "./sort";

describe("applySort", () => {
  it("desc 数值；null 沉底", () => {
    const r = applySort([{ s: 1 }, { s: null }, { s: 3 }], { key: "s", dir: "desc" });
    expect(r.map((x) => x.s)).toEqual([3, 1, null]);
  });
  it("asc 数值", () => {
    const r = applySort([{ s: 3 }, { s: 1 }], { key: "s", dir: "asc" });
    expect(r.map((x) => x.s)).toEqual([1, 3]);
  });
  it("审计偏离：两边 null 返回 0（保持输入顺序）", () => {
    const a = { s: null, id: 1 }, b = { s: null, id: 2 };
    const r = applySort([a, b], { key: "s", dir: "desc" });
    expect(r.map((x) => x.id)).toEqual([1, 2]);
  });
});
