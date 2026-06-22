import { describe, it, expect } from "vitest";
import { normalizeSuppressed } from "./suppressed-normalize";

describe("normalizeSuppressed", () => {
  it("ok=true 取 items", () => {
    expect(normalizeSuppressed({ ok: true, items: { b1: { skipped_at: "x", reason: null, days_left: 3 } } }))
      .toEqual({ b1: { skipped_at: "x", reason: null, days_left: 3 } });
  });
  it("ok=false / null → {}", () => {
    expect(normalizeSuppressed({ ok: false, items: {} })).toEqual({});
    expect(normalizeSuppressed(null)).toEqual({});
  });
});
