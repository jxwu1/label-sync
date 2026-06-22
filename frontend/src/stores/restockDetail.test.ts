import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
vi.mock("../api/client", () => ({
  apiGet: vi.fn(),
  ApiError: class extends Error { constructor(public status: number, m: string){ super(m); } },
  UnauthenticatedError: class extends Error {},
}));
import { apiGet, ApiError, UnauthenticatedError } from "../api/client";
import { useRestockDetailStore } from "./restockDetail";

const detail = (bc: string) => ({ barcode: bc, urgency_breakdown: null });

beforeEach(() => { setActivePinia(createPinia()); vi.mocked(apiGet).mockReset(); });

describe("restockDetail store", () => {
  it("缓存命中不重拉", async () => {
    vi.mocked(apiGet).mockResolvedValue({ ok: true, detail: detail("b1") } as any);
    const s = useRestockDetailStore();
    await s.load("b1");
    await s.load("b1");
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(s.entries["b1"]).toBe("ready");
    expect(s.cache["b1"].barcode).toBe("b1");
  });
  it("inflight 合并同 SKU 并发（只发一次）", async () => {
    let resolve: (v: any) => void;
    vi.mocked(apiGet).mockReturnValue(new Promise((r) => { resolve = r; }) as any);
    const s = useRestockDetailStore();
    const p1 = s.load("b1"); const p2 = s.load("b1");
    resolve!({ ok: true, detail: detail("b1") });
    await Promise.all([p1, p2]);
    expect(apiGet).toHaveBeenCalledTimes(1);
  });
  it("A/B 隔离：A 迟到只填 cache[A]，不动当前 B", async () => {
    let resolveA: (v: any) => void;
    vi.mocked(apiGet).mockImplementation((path: string) => {
      if (path.includes("A")) return new Promise((r) => { resolveA = r; }) as any;
      return Promise.resolve({ ok: true, detail: detail("B") }) as any;
    });
    const s = useRestockDetailStore();
    s.load("A");                 // A 挂起
    await s.load("B");           // B 完成
    expect(s.entries["B"]).toBe("ready");
    resolveA!({ ok: true, detail: detail("A") }); // A 迟到
    await Promise.resolve();
    expect(s.cache["A"].barcode).toBe("A"); // 只填自己 key
    expect(s.cache["B"].barcode).toBe("B"); // B 不被污染
  });
  it("404 → missing；500 → error 不缓存可重试；401 → 中性不写错", async () => {
    const s = useRestockDetailStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new ApiError(404, "x"));
    await s.load("m1"); expect(s.entries["m1"]).toBe("missing");
    vi.mocked(apiGet).mockRejectedValueOnce(new ApiError(500, "boom"));
    await s.load("e1"); expect(s.entries["e1"]).toBe("error"); expect(s.cache["e1"]).toBeUndefined();
    vi.mocked(apiGet).mockResolvedValueOnce({ ok: true, detail: detail("e1") } as any);
    await s.load("e1"); expect(s.entries["e1"]).toBe("ready"); // 重开可重试
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("401"));
    await s.load("u1"); expect(s.errorMsg["u1"]).toBeUndefined(); // 401 不写业务错
  });
});
