"""导入清洗后的 parquet 到 DB。**一次性历史回填工具**。

用法（项目根目录）:
    单文件:
        python tools/import_parquet.py cleaned/events_2024.cleaned.parquet

    批量 (glob):
        python tools/import_parquet.py "cleaned/*.parquet"

Pipeline 位置:
    wipe_events.py → ERP 抓取 → raw parquet → clean_parquet.py
        → cleaned parquet → [本脚本] → DB

日常增量请用 tools/inventory_admin.py import-batch（走 HTML 路径）。
"""

from __future__ import annotations

import argparse
import sys
from glob import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockpile_db  # noqa: E402
from etl.parquet_importer import import_cleaned_parquet  # noqa: E402


def _import_one(path: Path) -> dict[str, int]:
    print(f"\n→ {path.name}")

    with stockpile_db._session() as session:
        sale_r, purchase_r = import_cleaned_parquet(path, session)
        session.commit()

    print(
        f"  sale     : 导入 {sale_r.rows_imported:>7,}  "
        f"重复跳 {sale_r.rows_skipped_duplicate:>5,}  "
        f"缺字段跳 {sale_r.rows_skipped_missing_key:>4,}  "
        f"新客户 {sale_r.new_customers:>4,}"
    )
    print(
        f"  purchase : 导入 {purchase_r.rows_imported:>7,}  "
        f"重复跳 {purchase_r.rows_skipped_duplicate:>5,}  "
        f"缺字段跳 {purchase_r.rows_skipped_missing_key:>4,}  "
        f"新供应商 {purchase_r.new_suppliers:>4,}"
    )
    print(f"  新建 SKU : {sale_r.new_skus + purchase_r.new_skus:>4,}")

    return {
        "sale_imported": sale_r.rows_imported,
        "sale_dup": sale_r.rows_skipped_duplicate,
        "sale_miss": sale_r.rows_skipped_missing_key,
        "purchase_imported": purchase_r.rows_imported,
        "purchase_dup": purchase_r.rows_skipped_duplicate,
        "purchase_miss": purchase_r.rows_skipped_missing_key,
        "new_customers": sale_r.new_customers,
        "new_suppliers": purchase_r.new_suppliers,
        "new_skus": sale_r.new_skus + purchase_r.new_skus,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", help="cleaned parquet 路径或 glob")
    args = parser.parse_args()

    files = sorted(Path(p) for p in glob(args.src))
    if not files:
        print(f"未找到匹配的文件: {args.src}")
        return 1

    print(f"将处理 {len(files)} 个文件")

    totals: dict[str, int] = {}
    for f in files:
        t = _import_one(f)
        for k, v in t.items():
            totals[k] = totals.get(k, 0) + v

    if len(files) > 1:
        print("\n" + "=" * 60)
        print(f"汇总（{len(files)} 文件）")
        print("=" * 60)
        print(f"sale 导入:        {totals.get('sale_imported', 0):>10,}")
        print(f"sale 重复跳:      {totals.get('sale_dup', 0):>10,}")
        print(f"sale 缺字段跳:    {totals.get('sale_miss', 0):>10,}")
        print(f"purchase 导入:    {totals.get('purchase_imported', 0):>10,}")
        print(f"purchase 重复跳:  {totals.get('purchase_dup', 0):>10,}")
        print(f"purchase 缺字段跳:{totals.get('purchase_miss', 0):>10,}")
        print(f"新客户:           {totals.get('new_customers', 0):>10,}")
        print(f"新供应商:         {totals.get('new_suppliers', 0):>10,}")
        print(f"新建 SKU:         {totals.get('new_skus', 0):>10,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
