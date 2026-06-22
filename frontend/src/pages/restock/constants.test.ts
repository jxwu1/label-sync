import { describe, it, expect } from "vitest";
import { INITIAL_FILTER, RESET_FILTER, THRESH, VISIBLE_CAP } from "./constants";

describe("constants", () => {
  it("初始默认 ≠ 重置目标", () => {
    expect(INITIAL_FILTER.origin).toBe("FOREIGN");
    expect(INITIAL_FILTER.coverMax).toBe(4);
    expect(RESET_FILTER.origin).toBe("");
    expect(RESET_FILTER.coverMax).toBe(null);
  });
  it("阈值锁定", () => {
    expect(THRESH.HOT_URGENCY).toBe(70);
    expect(THRESH.COVER_CAP).toBe(13.0);
    expect(THRESH.SUPPLIER_OVERVIEW_TOP).toBe(5);
    expect(THRESH.ORDERED_EXPIRY_DAYS).toBe(30);
    expect(VISIBLE_CAP).toBe(500);
  });
});
