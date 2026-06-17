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
});
