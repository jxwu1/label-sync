import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const storeFile = join(here, "..", "..", "stores", "history.ts");

// HC-2：Phase 1 不得引用 analytics/timeline 接口
const FORBIDDEN = ["/analytics/sku", "/timeline"];

function sources(): string[] {
  const files = readdirSync(here).filter(
    (f) => (f.endsWith(".ts") || f.endsWith(".vue")) && !f.includes("no-analytics"),
  );
  const texts = files.map((f) => readFileSync(join(here, f), "utf-8"));
  texts.push(readFileSync(storeFile, "utf-8"));
  return texts;
}

describe("HC-2 Phase 1 不接分析/SVG 接口", () => {
  for (const needle of FORBIDDEN) {
    it(`pages/history 与 stores/history.ts 不含 "${needle}"`, () => {
      for (const src of sources()) expect(src.includes(needle)).toBe(false);
    });
  }
});
