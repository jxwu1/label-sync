export class UnauthenticatedError extends Error {}

/** 统一 API GET：same-origin cookie；401/redirect/HTML 一律按未登录跳转（spec §6）。 */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  const isHtml = (res.headers.get("content-type") ?? "").includes("text/html");
  if (res.status === 401 || res.redirected || isHtml) {
    location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
    throw new UnauthenticatedError(`unauthenticated: ${path}`);
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return (await res.json()) as T;
}
