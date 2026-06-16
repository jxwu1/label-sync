import { mount, RouterLinkStub } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

// 仓库既有模式：vi.mock 掉 store（不引入 @pinia/testing）。plain 对象即可——
// 每个用例 mount 前设 isAdmin，组件首渲读取（fresh mount，无需响应式）。
const userState = { displayName: "x", isAdmin: false };
vi.mock("../stores/currentUser", () => ({ useCurrentUser: () => userState }));

import SidebarNav from "./SidebarNav.vue";

function mountNav(isAdmin: boolean) {
  userState.isAdmin = isAdmin;
  return mount(SidebarNav, {
    global: { stubs: { RouterLink: RouterLinkStub }, mocks: { $route: { name: "briefing" } } },
  });
}

describe("SidebarNav", () => {
  it("非 admin → 隐藏 requiresAdmin 项（pda_pending/admin）", () => {
    const w = mountNav(false);
    expect(w.text()).not.toContain("PDA 待处理");
    expect(w.text()).not.toContain("系统管理");
    expect(w.text()).toContain("货号历史");
  });

  it("admin → 显示全部项", () => {
    const w = mountNav(true);
    expect(w.text()).toContain("PDA 待处理");
    expect(w.text()).toContain("系统管理");
  });

  it("已迁项(briefing)=RouterLink；未迁项=<a href='/?page=id'>（无空格）", () => {
    const w = mountNav(true);
    const links = w.findAllComponents(RouterLinkStub);
    expect(links.some((l) => (l.props("to") as { name?: string })?.name === "briefing")).toBe(true);
    const hrefs = w.findAll("a.nav-item").map((a) => a.attributes("href"));
    expect(hrefs).toContain("/?page=restock");
    expect(hrefs).toContain("/?page=history");
    hrefs.forEach((h) => h && expect(h).not.toContain(" "));
  });
});
