import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

// 守护：restock 页只走 strict /api/restock/*，禁止直连旧胖端点
// /analytics/* 或 /restock/decisions（前端独立化 §11 契约，逐页 guard 先例 = history/no-analytics.test.ts）
const DIR = join(__dirname);
const FORBIDDEN = ["/analytics/", "/restock/decisions"];

describe("restock 页只走 /api/restock/*", () => {
  it("源码不含旧胖端点", () => {
    const files = readdirSync(DIR).filter(
      (f) => (f.endsWith(".ts") || f.endsWith(".vue")) && !f.endsWith(".test.ts"),
    );
    for (const f of files) {
      const src = readFileSync(join(DIR, f), "utf8");
      for (const bad of FORBIDDEN) {
        expect(src.includes(bad), `${f} 含 ${bad}`).toBe(false);
      }
    }
  });
});
