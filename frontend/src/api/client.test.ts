import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, UnauthenticatedError } from "./client";

function mockResponse(init: Partial<Response> & { payload?: unknown }) {
  const { payload, ...rest } = init;
  return {
    ok: true,
    status: 200,
    redirected: false,
    headers: new Headers({ "content-type": "application/json" }),
    ...rest,
    json: async () => payload ?? {},
  } as unknown as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe("apiGet", () => {
  it("返回 JSON 数据", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({ payload: { ok: true } })));
    expect(await apiGet("/api/briefing/data")).toEqual({ ok: true });
  });

  it("401 → 跳登录并抛 UnauthenticatedError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({ ok: false, status: 401 })));
    const assign = vi.fn();
    vi.stubGlobal("location", { assign, pathname: "/ui/briefing" });
    await expect(apiGet("/x")).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fui%2Fbriefing");
  });

  it("text/html 响应按未登录处理（防 302 喂登录页）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      mockResponse({ redirected: true, headers: new Headers({ "content-type": "text/html" }) }),
    ));
    const assign = vi.fn();
    vi.stubGlobal("location", { assign, pathname: "/ui/briefing" });
    await expect(apiGet("/x")).rejects.toBeInstanceOf(UnauthenticatedError);
  });
});
