"""进销存批量导入与验证 CLI。

用法（项目根目录下）：
    python tools/inventory_admin.py import-batch <folder>     # 批量导入
    python tools/inventory_admin.py stats                      # 当前聚合统计
    python tools/inventory_admin.py verify                     # 数据异常检查

文件类型按文件名推断：
- 含 'purchase' / '采购' / 'buy' → purchase
- 含 'sale' / 'sales' / '销售'   → sale
- 推断不出 → 跳过该文件并打印警告

幂等：UNIQUE 约束保证重复 import 同一份文件不会重复落库。
"""

import argparse
import sys
from pathlib import Path

# 让脚本能 import 项目根模块（不依赖 PYTHONPATH 设置）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows PowerShell 默认 GBK，遇中文 / 货币符号会崩。强制 UTF-8 输出，
# 终端显示可能有乱码但不再 crash。Windows Terminal / PowerShell 7 / VSCode
# 终端能正常显示。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import func, select  # noqa: E402

import stockpile_db  # noqa: E402
from inventory_importer import DEFAULT_MAPPING, import_events  # noqa: E402
from models import Customer, InventoryEvent, Stockpile, Supplier  # noqa: E402
from xls_html_parser import XlsHtmlParseError, parse_xls_html  # noqa: E402

_PURCHASE_KEYWORDS = ("purchase", "采购", "buy", "进货")
_SALE_KEYWORDS = ("sales", "sale", "销售", "售单")


def _infer_event_type(filename: str) -> str | None:
    name = filename.lower()
    # 先 sale 再 purchase（"采购" 不会撞 "sale"，但 "buy" 不能在 "buyer" 前匹配）
    for kw in _SALE_KEYWORDS:
        if kw in name:
            return "sale"
    for kw in _PURCHASE_KEYWORDS:
        if kw in name:
            return "purchase"
    return None


def cmd_import_batch(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"目录不存在: {folder}")
        return 1

    xls_files = sorted(folder.glob("*.xls"))
    if not xls_files:
        print(f"目录里没有 .xls 文件: {folder}")
        return 1

    total_imported = 0
    total_skipped_duplicate = 0
    total_skipped_missing = 0
    total_new_customers = 0
    total_new_suppliers = 0
    total_new_skus = 0
    files_processed = 0
    files_skipped = []

    for xls in xls_files:
        event_type = _infer_event_type(xls.name)
        if event_type is None:
            files_skipped.append(xls.name)
            print(f"⚠ 跳过（无法推断类型，文件名缺少 purchase/sale 关键词）：{xls.name}")
            continue
        if args.type and event_type != args.type:
            # --type 强制类型时跳过不匹配的
            continue

        print(f"\n→ [{event_type}] {xls.name}")
        try:
            df = parse_xls_html(xls)
        except XlsHtmlParseError as exc:
            print(f"  ✗ 解析失败：{exc}")
            files_skipped.append(xls.name)
            continue

        try:
            with stockpile_db._session() as session:
                result = import_events(df, DEFAULT_MAPPING, event_type, session)
                session.commit()
        except Exception as exc:
            print(f"  ✗ 导入失败：{exc}")
            files_skipped.append(xls.name)
            continue

        dup = result.rows_skipped_duplicate
        miss = result.rows_skipped_missing_key
        print(f"  导入 {result.rows_imported} / 跳过 重复{dup} 缺字段{miss}")
        print(
            f"  新建 客户{result.new_customers} 供应商{result.new_suppliers} SKU{result.new_skus}"
        )
        total_imported += result.rows_imported
        total_skipped_duplicate += result.rows_skipped_duplicate
        total_skipped_missing += result.rows_skipped_missing_key
        total_new_customers += result.new_customers
        total_new_suppliers += result.new_suppliers
        total_new_skus += result.new_skus
        files_processed += 1

    print("\n=== 汇总 ===")
    print(f"成功处理 {files_processed} 个文件")
    print(f"事件导入 {total_imported}")
    print(f"事件跳过 重复{total_skipped_duplicate} / 缺字段{total_skipped_missing}")
    print(f"新建 客户{total_new_customers} / 供应商{total_new_suppliers} / SKU{total_new_skus}")
    if files_skipped:
        print(f"\n跳过文件 ({len(files_skipped)} 个)：")
        for f in files_skipped:
            print(f"  {f}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with stockpile_db._session() as session:
        events_total = session.scalar(select(func.count()).select_from(InventoryEvent)) or 0
        events_purchase = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(InventoryEvent.event_type == "purchase")
            )
            or 0
        )
        events_sale = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(InventoryEvent.event_type == "sale")
            )
            or 0
        )
        customers_total = session.scalar(select(func.count()).select_from(Customer)) or 0
        suppliers_total = session.scalar(select(func.count()).select_from(Supplier)) or 0
        skus_total = session.scalar(select(func.count()).select_from(Stockpile)) or 0

        min_date, max_date = session.execute(
            select(func.min(InventoryEvent.event_at), func.max(InventoryEvent.event_at))
        ).first()

        type_distribution = session.execute(
            select(Customer.customer_type, func.count()).group_by(Customer.customer_type)
        ).all()

    print("=== 当前数据库状态 ===")
    print(f"事件总数: {events_total}  (采购 {events_purchase} / 销售 {events_sale})")
    print(f"客户: {customers_total}")
    print(f"供应商: {suppliers_total}")
    print(f"SKU: {skus_total}")
    if min_date:
        print(f"事件日期范围: {min_date} ~ {max_date}")
    print("客户类型分布:")
    for t, c in sorted(type_distribution):
        print(f"  {t or 'unknown'}: {c}")
    return 0


def _trunc(text: str, width: int) -> str:
    """按显示宽度截断字符串（中文 / 希腊字符算 2 列）。"""
    out = []
    used = 0
    for c in text or "":
        w = 2 if ord(c) > 0x7F else 1
        if used + w > width:
            out.append("…")
            break
        out.append(c)
        used += w
    return "".join(out).ljust(width - max(0, used - width))


def _pct(num: int | float, total: int | float) -> str:
    if not total:
        return "—"
    return f"{100 * num / total:.1f}%"


def cmd_verify(args: argparse.Namespace) -> int:
    sale_amt = func.coalesce(InventoryEvent.qty, 0) * func.coalesce(InventoryEvent.unit_price, 0)
    with stockpile_db._session() as session:
        # === 1. 异常计数 ===
        neg_qty = (
            session.scalar(
                select(func.count()).select_from(InventoryEvent).where(InventoryEvent.qty < 0)
            )
            or 0
        )
        sales_total = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(InventoryEvent.event_type == "sale")
            )
            or 0
        )
        purchase_total = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(InventoryEvent.event_type == "purchase")
            )
            or 0
        )
        sales_zero_price = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where((InventoryEvent.event_type == "sale") & (InventoryEvent.unit_price == 0))
            )
            or 0
        )
        purchase_zero_price = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where((InventoryEvent.event_type == "purchase") & (InventoryEvent.unit_price == 0))
            )
            or 0
        )
        sales_no_customer = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(
                    (InventoryEvent.event_type == "sale") & (InventoryEvent.customer_id.is_(None))
                )
            )
            or 0
        )
        purchase_no_supplier = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(
                    (InventoryEvent.event_type == "purchase")
                    & (InventoryEvent.supplier_id.is_(None))
                )
            )
            or 0
        )

        # === 2. 客户类型分布 ===
        type_dist_rows = session.execute(
            select(Customer.customer_type, func.count())
            .group_by(Customer.customer_type)
            .order_by(func.count().desc())
        ).all()
        type_dist = {t or "unknown": c for t, c in type_dist_rows}
        customers_total = sum(type_dist.values())

        # === 3. Top 10 客户（事件数 + 销售额） ===
        top_by_count = session.execute(
            select(
                InventoryEvent.customer_id,
                Customer.customer_name,
                Customer.customer_type,
                func.count().label("cnt"),
            )
            .join(Customer, Customer.customer_id == InventoryEvent.customer_id)
            .where(InventoryEvent.event_type == "sale")
            .group_by(InventoryEvent.customer_id, Customer.customer_name, Customer.customer_type)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        top_by_amt = session.execute(
            select(
                InventoryEvent.customer_id,
                Customer.customer_name,
                Customer.customer_type,
                func.sum(sale_amt).label("amt"),
            )
            .join(Customer, Customer.customer_id == InventoryEvent.customer_id)
            .where(InventoryEvent.event_type == "sale")
            .group_by(InventoryEvent.customer_id, Customer.customer_name, Customer.customer_type)
            .order_by(func.sum(sale_amt).desc())
            .limit(10)
        ).all()

        # === 4. 销售额 by 客户类型 ===
        sales_by_type_rows = session.execute(
            select(
                Customer.customer_type,
                func.sum(sale_amt).label("amt"),
                func.count().label("cnt"),
            )
            .join(Customer, Customer.customer_id == InventoryEvent.customer_id)
            .where(InventoryEvent.event_type == "sale")
            .group_by(Customer.customer_type)
            .order_by(func.sum(sale_amt).desc())
        ).all()
        total_sales_amt = sum(float(r.amt or 0) for r in sales_by_type_rows)

    # === 输出 ===
    sales_zp_pct = _pct(sales_zero_price, sales_total)
    purchase_zp_pct = _pct(purchase_zero_price, purchase_total)
    sales_nc_pct = _pct(sales_no_customer, sales_total)
    print("=== 数据验证 ===")
    print(f"负 qty 事件:           {neg_qty}  (期望 0)")
    sales_zp_line = f"{sales_zero_price} / {sales_total} ({sales_zp_pct})"
    purchase_zp_line = f"{purchase_zero_price} / {purchase_total} ({purchase_zp_pct})"
    print(f"销售单价 0:            {sales_zp_line}  (赠品 / 免单)")
    print(f"采购单价 0:            {purchase_zp_line}")
    print(f"无客户的销售事件:      {sales_no_customer} / {sales_total} ({sales_nc_pct})")
    print(f"无供应商的采购事件:    {purchase_no_supplier}  (>0 异常)")

    print("\n=== 客户类型分布 ===")
    for t in ("foreign", "chinese", "mixed", "unknown"):
        c = type_dist.get(t, 0)
        print(f"  {t:10s} {c:>5d}  ({_pct(c, customers_total)})")

    print("\n=== Top 10 客户（按销售事件数） ===")
    print(f"  {'#':>3}  {'类型':6}  {'客户名':30}  {'事件数':>8}")
    for i, r in enumerate(top_by_count, 1):
        print(f"  {i:>3}  {r.customer_type:6}  {_trunc(r.customer_name, 30)}  {r.cnt:>8d}")

    print("\n=== Top 10 客户（按销售额） ===")
    print(f"  {'#':>3}  {'类型':6}  {'客户名':30}  {'销售额':>12}")
    for i, r in enumerate(top_by_amt, 1):
        amt = float(r.amt or 0)
        print(f"  {i:>3}  {r.customer_type:6}  {_trunc(r.customer_name, 30)}  €{amt:>11,.2f}")

    print("\n=== 销售额 by 客户类型 ===")
    print(f"  {'类型':10}  {'销售额':>14}  {'占比':>8}  {'事件数':>8}")
    for r in sales_by_type_rows:
        amt = float(r.amt or 0)
        print(
            f"  {(r.customer_type or 'unknown'):10}  "
            f"€{amt:>13,.2f}  {_pct(amt, total_sales_amt):>8}  {r.cnt:>8d}"
        )

    # === 备注 ===
    print(
        "\n备注：barcode 反查救回数仅在每次 import 时显示（ImportResult），"
        "不入库；要看历史救回率需对照 import 时的输出。"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="进销存批量导入与验证工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import-batch", help="批量导入一个目录里的所有 .xls")
    p_import.add_argument("folder", help="含 .xls 文件的目录路径")
    p_import.add_argument(
        "--type",
        choices=("purchase", "sale"),
        default=None,
        help="只导入指定类型的文件（默认：按文件名推断）",
    )
    p_import.set_defaults(func=cmd_import_batch)

    p_stats = sub.add_parser("stats", help="打印当前数据库聚合统计")
    p_stats.set_defaults(func=cmd_stats)

    p_verify = sub.add_parser("verify", help="验证查询：找数据异常")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
