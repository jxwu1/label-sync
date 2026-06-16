import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useCurrentUser } from "./currentUser";

describe("useCurrentUser", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 成功 → 填充 displayName + isAdmin", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({ display_name: "老板", is_admin: true });
    const s = useCurrentUser();
    expect(s.isAdmin).toBe(false); // 初始安全默认
    await s.load();
    expect(s.displayName).toBe("老板");
    expect(s.isAdmin).toBe(true);
  });

  it("401 透传（不吞，登录跳转由 apiGet 接管）", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    const s = useCurrentUser();
    await expect(s.load()).rejects.toBeInstanceOf(UnauthenticatedError);
  });

  it("500/网络失败 → 降级 isAdmin=false，不抛", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    const s = useCurrentUser();
    await s.load();
    expect(s.isAdmin).toBe(false);
  });
});
