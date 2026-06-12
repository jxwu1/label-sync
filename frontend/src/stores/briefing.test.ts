import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
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
});
