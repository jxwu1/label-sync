import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(async () => ({
    ok: true, found: false,
    fuzzy_matches: [{ barcode: "B1", model: "M1", location: "A22", is_active: true }],
  })),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useHistoryStore } from "./history";

// Helper: build a minimal "hit" HistorySearchData with a distinguishable barcode
function hitPayload(barcode: string) {
  return {
    ok: true,
    found: true,
    current: {
      barcode,
      model: `M-${barcode}`,
      location: "A01",
      is_active: true,
      source: null,
      created_at: null,
      updated_at: null,
      product_name_zh: null,
      product_name_local: null,
      erp_category_raw: null,
      erp_category_code: null,
      manual_grade: null,
      stock_price: null,
      sale_price: null,
      is_truly_discontinued: false,
      store_locations: [],
      warehouse_locations: [],
      unknown_locations: [],
    },
    events: [],
    fuzzy_matches: [],
  };
}

describe("history store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 命中填 result（fuzzy）并清 loading + 调对端点", async () => {
    const s = useHistoryStore();
    const p = s.load("ABC");
    expect(s.loading).toBe(true);
    await p;
    expect(s.loading).toBe(false);
    expect(s.result?.kind).toBe("fuzzy");
    expect(s.error).toBeNull();
    expect(vi.mocked(apiGet)).toHaveBeenCalledWith("/api/history?q=ABC");
  });

  it("load 失败 → error 填充，result 保持 null", async () => {
    const s = useHistoryStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load("x");
    expect(s.error).toBe("boom");
    expect(s.result).toBeNull();
  });

  it("未登录错误被吞掉，不污染 error", async () => {
    const s = useHistoryStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    await s.load("x");
    expect(s.error).toBeNull();
  });

  it("load 失败后清空上次 result（不残留旧 hit）", async () => {
    const s = useHistoryStore();
    // 先成功命中（默认 mock 返回 fuzzy；关键是 result 非 null）
    await s.load("A");
    expect(s.result).not.toBeNull();
    // 再失败查询
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load("B");
    expect(s.result).toBeNull();   // 旧结果必须被清，不能残留
    expect(s.error).toBe("boom");
  });

  it("reset() 清空 result/error", async () => {
    const s = useHistoryStore();
    await s.load("A");
    s.reset();
    expect(s.result).toBeNull();
    expect(s.error).toBeNull();
  });

  // HC-B7 concurrency guard tests
  it("HC-B7: A resolves after B, result stays B", async () => {
    let resolveA: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementationOnce(
      () => new Promise((r) => { resolveA = r; }),
    );
    vi.mocked(apiGet).mockResolvedValueOnce(hitPayload("B-barcode"));

    const s = useHistoryStore();
    const pA = s.load("A");
    const pB = s.load("B");
    await pB;
    resolveA(hitPayload("A-barcode"));
    await pA;

    expect(s.result?.kind).toBe("hit");
    expect((s.result as { kind: "hit"; current: { barcode: string } } | null)?.current?.barcode).toBe("B-barcode");
  });

  it("load returns true for latest, false for superseded", async () => {
    let resolveA: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementationOnce(
      () => new Promise((r) => { resolveA = r; }),
    );
    vi.mocked(apiGet).mockResolvedValueOnce(hitPayload("B-barcode"));

    const s = useHistoryStore();
    const pA = s.load("A");
    const freshB = await s.load("B");
    resolveA(hitPayload("A-barcode"));
    const freshA = await pA;

    expect(freshB).toBe(true);
    expect(freshA).toBe(false);
  });

  it("HC-B7 reset cancels pending (resolve after reset does not write result)", async () => {
    let resolveA: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementationOnce(
      () => new Promise((r) => { resolveA = r; }),
    );

    const s = useHistoryStore();
    const pA = s.load("A");
    s.reset();
    resolveA(hitPayload("A-barcode"));
    await pA;

    expect(s.result).toBeNull();
  });
});
