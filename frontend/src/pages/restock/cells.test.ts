import { describe, it, expect } from "vitest";
import {
  fmt, fmtDays, coverTone, urgencyLevel, wocLevel, marginLevel,
  originBadge, profitBadge, coverBar, sparklinePoints, sparkTrend, realBars,
} from "./cells";

describe("cells", () => {
  it("fmt null → 破折号；千分位", () => {
    expect(fmt(null)).toBe("—");
    expect(fmt(1234)).toBe("1,234");
  });
  it("fmtDays 分档", () => {
    expect(fmtDays(null)).toBe("—");
    expect(fmtDays(0)).toBe("今天");
    expect(fmtDays(5)).toBe("5 天前");
    expect(fmtDays(40)).toBe("1 月前");
    expect(fmtDays(400)).toBe("1.1 年前");
  });
  it("coverTone 阈值（T=4）", () => {
    expect(coverTone(null, 4)).toBe("ok");
    expect(coverTone(1, 4)).toBe("crit");
    expect(coverTone(3, 4)).toBe("low");
    expect(coverTone(6, 4)).toBe("ok");
    expect(coverTone(9, 4)).toBe("high");
  });
  it("urgencyLevel", () => {
    expect(urgencyLevel(70)).toBe("high");
    expect(urgencyLevel(40)).toBe("mid");
    expect(urgencyLevel(39)).toBe("low");
  });
  it("wocLevel", () => {
    expect(wocLevel(2)).toBe("crit");
    expect(wocLevel(4)).toBe("warn");
    expect(wocLevel(20)).toBe("cold");
    expect(wocLevel(10)).toBe("");
  });
  it("marginLevel", () => {
    expect(marginLevel(50)).toBe("great");
    expect(marginLevel(30)).toBe("good");
    expect(marginLevel(10)).toBe("meh");
    expect(marginLevel(9)).toBe("bad");
  });
  it("originBadge 三态（restock.js:109）", () => {
    expect(originBadge("FOREIGN")).toEqual({ char: "🇬🇷", cls: "fo" });
    expect(originBadge("CN")).toEqual({ char: "🇨🇳", cls: "cn" });
    expect(originBadge("unknown")).toEqual({ char: "?", cls: "unk" });
  });
  it("profitBadge 分档（restock.js:274）", () => {
    expect(profitBadge(null, 0)).toEqual({ label: "缺成本", cls: "unknown" });
    expect(profitBadge(5, 0)).toEqual({ label: "已回本", cls: "good" });
    expect(profitBadge(-3, 10)).toEqual({ label: "压货中", cls: "mid" }); // rp+inv=7>0
    expect(profitBadge(-30, 10)).toEqual({ label: "未回本", cls: "bad" }); // rp+inv=-20≤0
    expect(profitBadge(0, 0)).toEqual({ label: "未回本", cls: "bad" });   // rp=0 不>0；rp+inv=0 不>0
  });
  it("coverBar 几何（T=4, CAP=13）", () => {
    expect(coverBar(null, 4)).toBe(null);
    const b = coverBar(6.5, 4);
    expect(b!.tone).toBe("ok");
    expect(b!.fillPct).toBeCloseTo(50, 1);   // 6.5/13*100
    expect(b!.safePct).toBeCloseTo(30.77, 1); // 4/13*100
    expect(coverBar(20, 4)!.fillPct).toBe(100); // 封顶
  });
  it("sparkTrend 颜色档", () => {
    expect(sparkTrend(1.2)).toBe("up");
    expect(sparkTrend(-0.5)).toBe("down");
    expect(sparkTrend(0)).toBe("flat");
    expect(sparkTrend(null)).toBe("flat");
  });
  it("realBars 非 12 长度兜底全 0", () => {
    expect(realBars(null)).toEqual(new Array(12).fill(0));
    expect(realBars([1, 2, 3])).toEqual(new Array(12).fill(0));
    const ok = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
    expect(realBars(ok)).toBe(ok);
  });
  it("sparklinePoints 12 周 viewBox 60×20", () => {
    const pts = sparklinePoints([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 10]);
    const arr = pts.split(" ");
    expect(arr.length).toBe(12);
    expect(arr[0]).toBe("2.0,18.0");    // i=0 → x=2, v=0 → y=18(底)
    expect(arr[11]).toBe("58.0,2.0");   // i=11 → x=58, v=max → y=2(顶)
  });
});
