import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useScanBatchesStore } from "./scanBatches";

function batchList() {
  return {
    ok: true,
    batches: [
      { batch_id: "ALI价格标20260420100000", employee: "ALI", scanned_at: "2026-04-20 10:00:00",
        csv_filename: "x.csv", csv_rows: 3, csv_size_bytes: 120, xlsx_files: [] },
      { batch_id: "ABDUL价格标20260421100000", employee: "ABDUL", scanned_at: "2026-04-21 10:00:00",
        csv_filename: null, csv_rows: null, csv_size_bytes: null, xlsx_files: [] },
      { batch_id: "ALI价格标20260422100000", employee: "ALI", scanned_at: "2026-04-22 10:00:00",
        csv_filename: "y.csv", csv_rows: 1, csv_size_bytes: 50, xlsx_files: [] },
    ],
  };
}

const SCAN = "/api/history/scan-batches";
const scanCalls = () => vi.mocked(apiGet).mock.calls.filter((c) => c[0] === SCAN);

describe("scanBatches store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(apiGet).mockReset();
  });

  it("loadBatches 填 batches + loaded=true", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.batches.length).toBe(3);
    expect(s.loaded).toBe(true);
    expect(s.error).toBeNull();
  });

  it("employees 从批次派生（去重+排序）", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.employees).toEqual(["ABDUL", "ALI"]);
  });

  it("filteredBatches 按 employeeFilter；null=全部", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.filteredBatches.length).toBe(3);
    s.setEmployeeFilter("ALI");
    expect(s.filteredBatches.map((b) => b.employee)).toEqual(["ALI", "ALI"]);
    s.setEmployeeFilter(null);
    expect(s.filteredBatches.length).toBe(3);
  });

  it("toggleExpand 支持多行同时展开", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.loadBatches();
    s.toggleExpand("ALI价格标20260420100000");
    s.toggleExpand("ALI价格标20260422100000");
    expect(s.expanded.has("ALI价格标20260420100000")).toBe(true);
    expect(s.expanded.has("ALI价格标20260422100000")).toBe(true);
    s.toggleExpand("ALI价格标20260420100000");
    expect(s.expanded.has("ALI价格标20260420100000")).toBe(false);
  });

  it("401 → 不落 error", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    const s = useScanBatchesStore();
    await s.loadBatches();
    expect(s.error).toBeNull();
    expect(s.loaded).toBe(false);
  });

  it("ensureLoaded 幂等：首调 1 次，二调 0 新请求", async () => {
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    const s = useScanBatchesStore();
    await s.ensureLoaded();
    expect(scanCalls().length).toBe(1);
    await s.ensureLoaded();
    expect(scanCalls().length).toBe(1);
  });

  it("首次失败 loaded=false → 二次 ensureLoaded 重试发请求", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    const s = useScanBatchesStore();
    await s.ensureLoaded();
    expect(s.loaded).toBe(false);
    expect(s.error).toBe("boom");
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    await s.ensureLoaded();
    expect(scanCalls().length).toBe(2);
    expect(s.loaded).toBe(true);
  });

  it("reset 作废 pending：resolve 后不回填，loaded=false，清 filter+expanded", async () => {
    let resolve: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementation(() => new Promise((r) => { resolve = r; }) as never);
    const s = useScanBatchesStore();
    const p = s.loadBatches();
    s.setEmployeeFilter("ALI");
    s.reset();
    resolve(batchList());
    await p;
    expect(s.batches).toEqual([]);
    expect(s.loaded).toBe(false);
    expect(s.employeeFilter).toBeNull();
    expect(s.expanded.size).toBe(0);
  });

  it("inflight 代际竞态：A pending→reset→ensureLoaded(B)→A 迟到不清 B 的 inflight→不起 C", async () => {
    let resolveA: (v: unknown) => void = () => {};
    let resolveB: (v: unknown) => void = () => {};
    let nth = 0;
    vi.mocked(apiGet).mockImplementation(async () => {
      nth += 1;
      if (nth === 1) return new Promise((r) => { resolveA = r; }) as never;
      if (nth === 2) return new Promise((r) => { resolveB = r; }) as never;
      throw new Error("spurious C");
    });
    const s = useScanBatchesStore();
    const pA = s.ensureLoaded();
    expect(scanCalls().length).toBe(1);
    s.reset();
    const pB = s.ensureLoaded();
    expect(scanCalls().length).toBe(2);
    resolveA(batchList());
    await pA;
    const pExtra = s.ensureLoaded();
    expect(scanCalls().length).toBe(2); // 无 C
    resolveB(batchList());
    await pB;
    await pExtra;
    expect(scanCalls().length).toBe(2);
  });
});
