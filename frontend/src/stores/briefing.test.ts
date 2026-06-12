import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(async () => ({
    ok: true,
    generated_at: "2026-06-12T09:00:00",
    data_week: "2026-06-08",
    data_week_complete: true,
    cards: {
      sales_health: { ok: true, status: "ok" },
      restock_risk: { ok: true },
      stockout_impact: { ok: true },
      overstock_risk: { ok: true },
      data_health: { ok: true },
    },
    actions: { restock: { items: [] }, follow_up: { items: [] }, review_anomalies: { items: [] } },
  })),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useBriefingStore } from "./briefing";

describe("briefing store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 填充数据并清 loading", async () => {
    const s = useBriefingStore();
    expect(s.loading).toBe(false);
    const p = s.load();
    expect(s.loading).toBe(true);
    await p;
    expect(s.loading).toBe(false);
    expect(s.data?.data_week).toBe("2026-06-08");
    expect(s.error).toBeNull();
  });

  it("load 失败 → error 填充, data 保持 null, loading 清掉", async () => {
    const s = useBriefingStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load();
    expect(s.loading).toBe(false);
    expect(s.error).toBe("boom");
    expect(s.data).toBeNull();
  });

  it("未登录错误被吞掉（跳转接管 UX），不污染 error", async () => {
    const s = useBriefingStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    await s.load();
    expect(s.error).toBeNull();
    expect(s.loading).toBe(false);
  });
});
