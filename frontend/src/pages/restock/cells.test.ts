import { describe, it, expect } from "vitest";
import { fmt, fmtDays, coverTone, urgencyLevel, wocLevel, marginLevel } from "./cells";

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
});
