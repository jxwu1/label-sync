import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppHeader from "./AppHeader.vue";

describe("AppHeader", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("渲染时钟（HH:MM:SS）", () => {
    const w = mount(AppHeader);
    expect(w.text()).toMatch(/\d{2}:\d{2}:\d{2}/);
  });

  it("unmount 清掉 interval（不再 tick）", () => {
    const spy = vi.spyOn(globalThis, "clearInterval");
    const w = mount(AppHeader);
    w.unmount();
    expect(spy).toHaveBeenCalled();
  });
});
