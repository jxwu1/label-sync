import { describe, it, expect, beforeEach } from "vitest";
import { loadOrdered, autoClearOrderedByPurchase, LS_KEY_ORDERED } from "./ordered-store";

beforeEach(() => localStorage.clear());

describe("ordered-store", () => {
  it("损坏 JSON → {}", () => {
    localStorage.setItem(LS_KEY_ORDERED, "{not json");
    expect(loadOrdered()).toEqual({});
  });
  it("过期项剔除（>30 天）", () => {
    const old = new Date(Date.now() - 31 * 86400000).toISOString();
    const fresh = new Date().toISOString();
    localStorage.setItem(LS_KEY_ORDERED, JSON.stringify({ a: { marked_at: old }, b: { marked_at: fresh } }));
    const r = loadOrdered();
    expect("a" in r).toBe(false); expect("b" in r).toBe(true);
  });
  it("货到自动清：last_purchase_at > marked_at", () => {
    const marked = "2026-06-01T00:00:00.000Z";
    const ordered: Record<string, any> = { b1: { marked_at: marked } };
    const items = [{ barcode: "b1", last_purchase_at: "2026-06-10" }];
    const changed = autoClearOrderedByPurchase(ordered, items);
    expect(changed).toBe(true); expect("b1" in ordered).toBe(false);
  });
});
