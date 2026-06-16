import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import ThemeToggle from "./ThemeToggle.vue";

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.dataset.theme = "dark";
  });

  it("点 LIGHT → localStorage.theme=light + data-theme=light", async () => {
    const w = mount(ThemeToggle);
    await w.get('[data-theme-btn="light"]').trigger("click");
    expect(localStorage.getItem("theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("点 DARK → localStorage.theme=dark + data-theme=dark", async () => {
    const w = mount(ThemeToggle);
    await w.get('[data-theme-btn="dark"]').trigger("click");
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("active 反映当前 data-theme", () => {
    document.documentElement.dataset.theme = "light";
    const w = mount(ThemeToggle);
    expect(w.get('[data-theme-btn="light"]').classes()).toContain("active");
  });
});
