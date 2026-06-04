"""清理重复的 purchase inventory_events.

背景 (2026-05-23):
  历史回填 scrape (2020-2025) 与既有 events 部分重叠. ERP 同一笔进货可能
  有两条记录: 一条带 unit_price, 一条 unit_price 缺失 (不同 document_no
  导致 dedup key 不匹配, 都进 DB). 5828079293643 命中 8640 / 20640 = 42%
  双计, lifetime_invested 虚高.

清理规则:
  对每个 (product_barcode, event_at, qty, event_type='purchase') 组合,
  如果同时存在 unit_price IS NULL 行 + unit_price > 0 行, 删 NULL 行.
  (用户确认: "一次进货有价格一个没价格, 基本可以确定就是重复导入")

用法:
  python tools/dedup_purchase_events.py --dry-run    # 仅报告, 不删
  python tools/dedup_purchase_events.py --execute    # 实际删除
  python tools/dedup_purchase_events.py --barcode B  # 仅处理某个 SKU

幂等: 跑完不会再有 NULL 价格的 purchase 行 (有匹配的带价行时).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.repositories import stockpile_db  # noqa: E402


# 找出待删的 NULL-price 行 (有匹配带价行的)
_FIND_DUPS_SQL = """
SELECT e_null.id, e_null.product_barcode, e_null.event_at, e_null.qty,
       e_priced.id AS keep_id, e_priced.unit_price
FROM inventory_events e_null
JOIN inventory_events e_priced
  ON e_priced.event_type = 'purchase'
 AND e_priced.product_barcode = e_null.product_barcode
 AND e_priced.event_at = e_null.event_at
 AND e_priced.qty = e_null.qty
 AND e_priced.unit_price IS NOT NULL
 AND e_priced.id != e_null.id
WHERE e_null.event_type = 'purchase'
  AND e_null.unit_price IS NULL
"""

_FIND_DUPS_FILTERED_SQL = _FIND_DUPS_SQL + " AND e_null.product_barcode = :barcode"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="只报告, 不删")
    g.add_argument("--execute", action="store_true", help="实际执行删除")
    ap.add_argument("--barcode", help="仅处理某个条码")
    args = ap.parse_args()

    sql = _FIND_DUPS_FILTERED_SQL if args.barcode else _FIND_DUPS_SQL
    params = {"barcode": args.barcode} if args.barcode else {}

    with stockpile_db._session() as s:
        rows = s.execute(text(sql), params).all()
        if not rows:
            print("没找到任何重复 (NULL-price + 带价配对). 无事可做.")
            return 0
        print(f"找到 {len(rows)} 行待删 NULL-price purchase events:")
        from collections import defaultdict

        by_bc: dict[str, list] = defaultdict(list)
        for r in rows:
            by_bc[r.product_barcode].append(r)
        for bc, items in sorted(by_bc.items()):
            total_qty = sum(it.qty for it in items)
            print(f"  {bc}: {len(items)} 行 / {total_qty} 件双计")
            for it in items[:5]:
                print(
                    f"    - {it.event_at} qty={it.qty} (delete id={it.id}, "
                    f"keep id={it.keep_id} unit_price={it.unit_price})"
                )
            if len(items) > 5:
                print(f"    ... 还有 {len(items) - 5} 行")
        if args.dry_run:
            print(f"\n[DRY-RUN] 总计可删 {len(rows)} 行. 加 --execute 实际删除.")
            return 0
        ids = [r.id for r in rows]
        BATCH = 500
        deleted = 0
        for i in range(0, len(ids), BATCH):
            chunk = ids[i : i + BATCH]
            s.execute(
                text("DELETE FROM inventory_events WHERE id = ANY(:ids)"),
                {"ids": chunk},
            )
            deleted += len(chunk)
            print(f"  删除 {deleted} / {len(ids)} ...")
        s.commit()
        print(f"\n[OK] 删除 {deleted} 行重复 purchase events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
