export interface SortState { key: string; dir: "asc" | "desc"; }

export function applySort<T extends Record<string, any>>(items: T[], sort: SortState): T[] {
  const { key, dir } = sort;
  const mul = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = a[key], bv = b[key];
    const an = av === null || av === undefined;
    const bn = bv === null || bv === undefined;
    if (an && bn) return 0;        // 审计偏离：旧实现返回 1（违反反对称性），spec §6
    if (an) return 1;              // null 沉底
    if (bn) return -1;
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
}
