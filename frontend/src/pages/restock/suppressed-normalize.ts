import type { RestockSuppressedList, RestockSuppressedEntry } from "../../api/types.gen";

export function normalizeSuppressed(
  data: RestockSuppressedList | null | undefined,
): Record<string, RestockSuppressedEntry> {
  if (!data || !data.ok || !data.items) return {};
  return data.items as Record<string, RestockSuppressedEntry>;
}
