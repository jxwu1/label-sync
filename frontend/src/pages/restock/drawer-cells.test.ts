import { describe, it, expect } from "vitest";
import { profitStatus, retailPriceLine, cashflowImbalance, scoreSegments } from "./drawer-cells";

describe("drawer-cells", () => {
  it("profitStatus 四档（restock.js:430-446）", () => {
    expect(profitStatus(null, 0)).toEqual({ cls: "unknown", label: "缺成本" });
    expect(profitStatus(5, 0)).toEqual({ cls: "good", label: "已回本" });
    expect(profitStatus(-3, 10)).toEqual({ cls: "mid", label: "压货中" });   // rp+inv>0
    expect(profitStatus(-30, 10)).toEqual({ cls: "bad", label: "账面亏损" }); // rp+inv≤0
  });
  it("retailPriceLine observed/estimate 分支（restock.js:420-429）", () => {
    expect(retailPriceLine(5.5, 6.2, 3).kind).toBe("both");
    expect(retailPriceLine(5.5, null, 3).kind).toBe("observed");
    expect(retailPriceLine(null, 6.2, 0).kind).toBe("estimate");
    expect(retailPriceLine(null, null, 0).kind).toBe("none");
  });
  it("cashflowImbalance >30% 警告（restock.js:451-455）", () => {
    expect(cashflowImbalance(35).warn).toBe(true);
    expect(cashflowImbalance(30).warn).toBe(false);
    expect(cashflowImbalance(null).warn).toBe(false);
  });
  it("scoreSegments 段宽与占比（restock.js:159-168）", () => {
    const segs = scoreSegments({ velocity: 30, cover: 15, recency: 5, margin: 0 } as any);
    expect(segs.map((s) => s.widthPct)).toEqual([30, 30, 10, 30]); // 段宽=总分占比
    expect(segs[0].fillPct).toBe(100); // 30/30
    expect(segs[3].fillPct).toBe(0);   // 0/30
  });
});
