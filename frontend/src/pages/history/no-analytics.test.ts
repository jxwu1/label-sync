import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const storesDir = join(here, "..", "..", "stores");

// HC-P3-5：货号历史新栈不得调用 legacy analytics 端点。
// /analytics/sku 覆盖旧胖端点（含旧 timeline /analytics/sku/<bc>/timeline）。
// 新瘦端点 /api/history/<bc>/{analytics,analytics/extras,timeline} 均不含该子串。
// 裸 /timeline 已移除（会误伤新 timeline 瘦端点 + ./timeline-types import）。
const FORBIDDEN = ["/analytics/sku"];

const HISTORY_STORES = ["history.ts", "skuAnalytics.ts", "skuExtras.ts", "skuTimeline.ts", "recentChanges.ts", "scanBatches.ts"];

function sources(): { name: string; text: string }[] {
  const pageFiles = readdirSync(here)
    .filter((f) => (f.endsWith(".ts") || f.endsWith(".vue")) && !f.includes("no-analytics"))
    .map((f) => ({ name: `pages/history/${f}`, text: readFileSync(join(here, f), "utf-8") }));
  const storeFiles = HISTORY_STORES.map((f) => ({
    name: `stores/${f}`,
    text: readFileSync(join(storesDir, f), "utf-8"),
  }));
  return [...pageFiles, ...storeFiles];
}

describe("货号历史新栈不调用 legacy analytics 端点", () => {
  it("扫描集确实包含全部 sku* store（防漏扫假保护）", () => {
    const names = sources().map((s) => s.name);
    for (const f of HISTORY_STORES) expect(names).toContain(`stores/${f}`);
  });
  for (const needle of FORBIDDEN) {
    it(`无文件含 "${needle}"`, () => {
      for (const { text } of sources()) expect(text.includes(needle)).toBe(false);
    });
  }
});
