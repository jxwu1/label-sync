import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// nav-resolve.js 是 classic 脚本（无 export，禁 ESM），不能 import；
// 读文件 + new Function eval 取出全局函数（spec §8）。
const here = dirname(fileURLToPath(import.meta.url)); // .../frontend/src/legacy
const file = resolve(here, "../../../static/js/nav-resolve.js"); // → 仓库根 static/js
const code = readFileSync(file, "utf8");
const resolveInitialPage = new Function(
  code + "; return resolveInitialPage;",
)() as (p: string, s: string, ids: string[]) => string | null;

const IDS = ["dashboard", "restock", "purchase", "data_quality"];

describe("resolveInitialPage", () => {
  it("?page= 命中 → 返回该 id", () => {
    expect(resolveInitialPage("/", "?page=restock", IDS)).toBe("restock");
    expect(resolveInitialPage("/", "?page=purchase", IDS)).toBe("purchase");
    expect(resolveInitialPage("/", "?page=data_quality", IDS)).toBe("data_quality");
  });
  it("query 命中优先于 pathname", () => {
    expect(resolveInitialPage("/data_quality", "?page=restock", IDS)).toBe("restock");
  });
  it("query 未命中 → 回退 pathname 首段", () => {
    expect(resolveInitialPage("/data_quality", "", IDS)).toBe("data_quality");
    expect(resolveInitialPage("/data_quality", "?page=nope", IDS)).toBe("data_quality");
  });
  it("都不命中 → null", () => {
    expect(resolveInitialPage("/", "", IDS)).toBeNull();
    expect(resolveInitialPage("/unknown", "?page=bad", IDS)).toBeNull();
  });
  it("非法 page 值 → null（不回退到它）", () => {
    expect(resolveInitialPage("/", "?page=<script>", IDS)).toBeNull();
  });
});
