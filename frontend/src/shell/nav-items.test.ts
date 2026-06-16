import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import IconSprite from "./IconSprite.vue";
import { NAV_ITEMS, SPRITE_ICONS } from "./nav-items";

describe("nav-items", () => {
  it("每个 NavItem 二选一必有 routeName 或 legacyPageId", () => {
    for (const it of NAV_ITEMS) {
      expect(Boolean(it.routeName) !== Boolean(it.legacyPageId)).toBe(true);
    }
  });

  it("每个 icon 都能在 sprite 里找到对应 symbol（防空图标）", () => {
    const w = mount(IconSprite);
    const ids = w.findAll("symbol").map((s) => s.attributes("id"));
    for (const item of NAV_ITEMS) {
      expect(ids).toContain(`icon-${item.icon}`);
    }
    // SPRITE_ICONS 与实际 sprite 一致
    for (const name of SPRITE_ICONS) {
      expect(ids).toContain(`icon-${name}`);
    }
  });
});
