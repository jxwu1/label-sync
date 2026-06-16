import { mount, RouterLinkStub } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

// vi.mock store（仓库模式）；load 返回 resolved promise 以配合 onMounted 的 .catch()。
const loadSpy = vi.fn().mockResolvedValue(undefined);
const userState = { displayName: "老板", isAdmin: true, load: loadSpy };
vi.mock("../stores/currentUser", () => ({ useCurrentUser: () => userState }));

import AppShell from "./AppShell.vue";

describe("AppShell", () => {
  it("渲染侧栏品牌 + RouterView 占位，挂载触发 currentUser.load()", () => {
    const w = mount(AppShell, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          RouterView: { template: "<div class='rv' />" },
          SidebarNav: true,
          AppHeader: true,
          ThemeToggle: true,
          IconSprite: true,
        },
        mocks: { $route: { name: "briefing" } },
      },
    });
    expect(w.find("aside.sidebar").exists()).toBe(true);
    expect(w.find(".rv").exists()).toBe(true);
    expect(w.text()).toContain("DataOps");
    expect(loadSpy).toHaveBeenCalled();
  });
});
