import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useRecentChangesStore } from "./recentChanges";

// ---- payload builders (match types.gen exactly) ----
function batchList(...ids: number[]) {
  return {
    ok: true,
    batches: ids.map((id) => ({
      batch_id: id,
      taken_at: "2026-06-01T00:00:00Z",
      total_local: 100,
      change_count: 3,
      affected_barcodes: 2,
      is_open: false,
    })),
  };
}

function detail(opts: { inserts?: number; total?: number; barcode?: string } = {}) {
  return {
    ok: true,
    summary: {
      location_changes: 1,
      model_changes: 1,
      inserts: opts.inserts ?? 1,
      deactivates: 0,
      reactivates: 0,
      roundtrip_count: 0,
    },
    changes: [
      {
        barcode: opts.barcode ?? "BC1",
        model: "M1",
        field: "location",
        from_value: "A",
        to_value: "B",
        change_type: "location",
        at: "2026-06-01T00:00:00Z",
      },
    ],
    total_count: opts.total ?? 1,
  };
}

const isBatches = (p: string) => p === "/api/history/recent-changes/batches";
const isDetail = (p: string) => /\/api\/history\/recent-changes\/\d+\/changes/.test(p);
const detailBid = (p: string) =>
  Number(/\/api\/history\/recent-changes\/(\d+)\/changes/.exec(p)?.[1]);

// default happy-path router: batches → [1, 2]; any detail → detail()
function installHappyRouter() {
  vi.mocked(apiGet).mockImplementation(async (path: string) => {
    if (isBatches(path)) return batchList(1, 2) as never;
    if (isDetail(path)) return detail({ barcode: `BC${detailBid(path)}` }) as never;
    throw new Error(`unexpected path: ${path}`);
  });
}

const batchCalls = () =>
  vi.mocked(apiGet).mock.calls.filter((c) => isBatches(c[0] as string));
const detailCalls = () =>
  vi.mocked(apiGet).mock.calls.filter((c) => isDetail(c[0] as string));

describe("recentChanges store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(apiGet).mockReset();
  });

  // 1
  it("loadBatches 填 batches 并自动选首项 → 触发 loadDetail", async () => {
    installHappyRouter();
    const s = useRecentChangesStore();
    await s.loadBatches();
    expect(s.batches.map((b) => b.batchId)).toEqual([1, 2]);
    expect(s.selectedBatchId).toBe(1);
    expect(s.loaded).toBe(true);
    // detail endpoint called for batches[0].batchId === 1
    expect(detailCalls().some((c) => detailBid(c[0] as string) === 1)).toBe(true);
  });

  // 2
  it("loadDetail 填 summary + changes + totalCount", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (isBatches(path)) return batchList(1) as never;
      return detail({ inserts: 7, total: 9, barcode: "BCX" }) as never;
    });
    const s = useRecentChangesStore();
    await s.loadBatches();
    expect(s.summary?.inserts).toBe(7);
    expect(s.changes[0].barcode).toBe("BCX");
    expect(s.totalCount).toBe(9);
    expect(s.detailError).toBeNull();
  });

  // 3
  it("detail 失败 → detailError 填充且不抛", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (isBatches(path)) return batchList(1) as never;
      throw new Error("detail boom");
    });
    const s = useRecentChangesStore();
    await expect(s.loadBatches()).resolves.toBeUndefined();
    expect(s.detailError).toBe("detail boom");
    expect(s.summary).toBeNull();
  });

  // 4
  it("401 吞掉：error 与 detailError 均保持 null", async () => {
    // batches 401
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    const s = useRecentChangesStore();
    await s.loadBatches();
    expect(s.error).toBeNull();
    expect(s.detailError).toBeNull();

    // detail 401
    vi.mocked(apiGet).mockReset();
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (isBatches(path)) return batchList(1) as never;
      throw new UnauthenticatedError("y");
    });
    const s2 = useRecentChangesStore();
    await s2.loadBatches();
    expect(s2.error).toBeNull();
    expect(s2.detailError).toBeNull();
  });

  // 5
  it("setMode 与 setFilter 各自重新拉 detail", async () => {
    installHappyRouter();
    const s = useRecentChangesStore();
    await s.loadBatches();
    const before = detailCalls().length;
    await s.setMode("raw");
    expect(detailCalls().length).toBe(before + 1);
    expect(detailCalls().at(-1)?.[0]).toContain("mode=raw");
    await s.setFilter({ field: "location", changeType: null });
    expect(detailCalls().length).toBe(before + 2);
    expect(detailCalls().at(-1)?.[0]).toContain("field=location");
  });

  // 6 HC-B7
  it("HC-B7: A→B 快切，A 迟到响应不得覆盖 B", async () => {
    let resolveA: (v: unknown) => void = () => {};
    const s = useRecentChangesStore();
    // seed batches + selectedBatchId without going through auto-select
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (isBatches(path)) return batchList(1, 2) as never;
      const bid = detailBid(path);
      if (bid === 1) return new Promise((r) => { resolveA = r; }) as never; // A hangs
      return detail({ barcode: "BC2", inserts: 22 }) as never; // B resolves now
    });
    // loadBatches auto-selects batch 1 (A, hangs). Don't await it.
    const pBatches = s.loadBatches();
    // flush microtasks so batches resolves and auto-select(1) issues A's
    // (hanging) detail request before we switch.
    while (!detailCalls().some((c) => detailBid(c[0] as string) === 1)) {
      await Promise.resolve();
    }
    // switch to B while A pending
    await s.selectBatch(2);
    expect(s.changes[0].barcode).toBe("BC2");
    expect(s.summary?.inserts).toBe(22);
    // now A arrives late
    resolveA(detail({ barcode: "BC1", inserts: 99 }));
    await pBatches;
    // B still wins, A's late data discarded
    expect(s.changes[0].barcode).toBe("BC2");
    expect(s.summary?.inserts).toBe(22);
  });

  // 7
  it("reset 作废 pending（含 batches 级）：resolve 后不回填，loaded === false", async () => {
    let resolveBatches: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementation(
      () => new Promise((r) => { resolveBatches = r; }) as never,
    );
    const s = useRecentChangesStore();
    const p = s.loadBatches();
    s.reset();
    resolveBatches(batchList(1, 2));
    await p;
    expect(s.batches).toEqual([]);
    expect(s.loaded).toBe(false);
    expect(s.selectedBatchId).toBeNull();
  });

  // 8
  it("ensureLoaded 幂等：首调 1 batches + 1 changes 且 resolve 在两者完成后；二调 0 新请求", async () => {
    installHappyRouter();
    const s = useRecentChangesStore();
    await s.ensureLoaded();
    expect(batchCalls().length).toBe(1);
    expect(detailCalls().length).toBe(1);
    // ensureLoaded resolved only after both completed → state fully populated
    expect(s.loaded).toBe(true);
    expect(s.summary).not.toBeNull();
    expect(s.changes.length).toBeGreaterThan(0);

    await s.ensureLoaded();
    expect(batchCalls().length).toBe(1); // no new requests
    expect(detailCalls().length).toBe(1);
  });

  // 9
  it("首次 batches 失败 → loaded false；二次 ensureLoaded 重试发请求", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("batches boom"));
    const s = useRecentChangesStore();
    await s.ensureLoaded();
    expect(s.loaded).toBe(false);
    expect(s.error).toBe("batches boom");
    expect(batchCalls().length).toBe(1);

    // retry: now happy
    installHappyRouter();
    await s.ensureLoaded();
    expect(batchCalls().length).toBe(2); // retried
    expect(s.loaded).toBe(true);
  });

  // 10
  it("inflight 代际竞态：A pending→reset→ensureLoaded(B) 起→A 迟到 finally 不清 B 的 inflight→再调不起 C", async () => {
    let resolveA: (v: unknown) => void = () => {};
    let resolveB: (v: unknown) => void = () => {};
    let nthBatches = 0;
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (isBatches(path)) {
        nthBatches += 1;
        if (nthBatches === 1) return new Promise((r) => { resolveA = r; }) as never;
        if (nthBatches === 2) return new Promise((r) => { resolveB = r; }) as never;
        throw new Error("spurious C batches call");
      }
      return detail() as never;
    });
    const s = useRecentChangesStore();

    // A: ensureLoaded starts, batches pending (initGen = 1, inflight = true)
    const pA = s.ensureLoaded();
    expect(batchCalls().length).toBe(1);

    // reset bumps initGen → 2, inflight = false
    s.reset();

    // B: ensureLoaded starts a NEW batches request (initGen = 3, inflight = true)
    const pB = s.ensureLoaded();
    expect(batchCalls().length).toBe(2);

    // A resolves LATE. loadBatches A's gen mismatches → returns early.
    // ensureLoaded A's finally: my(=1) !== initGen(=3) → must NOT clear inflight.
    resolveA(batchList(1));
    await pA;

    // another ensureLoaded while B inflight → must NOT start C
    const pExtra = s.ensureLoaded();
    expect(batchCalls().length).toBe(2); // still 2, no spurious C

    // let B finish cleanly
    resolveB(batchList(1, 2));
    await pB;
    await pExtra;
    expect(batchCalls().length).toBe(2);
  });
});
