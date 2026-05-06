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


def cmd_verify(args: argparse.Namespace) -> int:
    with stockpile_db._session() as session:
        neg_qty = (
            session.scalar(
                select(func.count()).select_from(InventoryEvent).where(InventoryEvent.qty < 0)
            )
            or 0
        )
        zero_price = (
            session.scalar(
                select(func.count())
                .select_from(InventoryEvent)
                .where(InventoryEvent.unit_price == 0)
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
        unknown_customers = (
            session.scalar(
                select(func.count())
                .select_from(Customer)
                .where(Customer.customer_type == "unknown")
            )
            or 0
        )
        mixed_customers = (
            session.scalar(
                select(func.count()).select_from(Customer).where(Customer.customer_type == "mixed")
            )
            or 0
        )

    print("=== 数据验证 ===")
    print(f"负 qty 事件:           {neg_qty}  (期望 0；采购销售都是正数 + event_type 区分方向)")
    print(f"单价 0 事件:           {zero_price}  (赠品 / 免单可能正常，看比例)")
    print(f"无客户的销售事件:      {sales_no_customer}  (散客没记可能正常)")
    print(f"无供应商的采购事件:    {purchase_no_supplier}  (采购都该有供应商，>0 异常)")
    print("待人工归类客户:")
    print(f"  unknown (纯数字/纯符号): {unknown_customers}")
    print(f"  mixed (中希混合):        {mixed_customers}")
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
