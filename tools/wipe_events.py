"""精确清空进销存事件数据（方案 C），保留 stockpile 主档和人工字段。

用法（项目根目录下）：
    python tools/wipe_events.py --dry-run    # 只打印计划不执行
    python tools/wipe_events.py              # 走交互流程：先备份 → 输入 YES 确认 → 执行

设计取舍：
- **必须保留**：stockpile 主档（含 manual_grade / manual_category / 库位 / ERP 分类 /
  stock_price / sale_price），foreign_customer_records，import_profiles，schema_meta
- **清空**：inventory_events、customers、suppliers、stockpile_snapshots、
  inventory_imports、stockpile_changes
- **重置字段**：stockpile.auto_category / auto_category_computed_at = NULL（让
  重导后 categorizer 重跑）
- **自动备份**：执行前一律复制 stockpile.db → stockpile.db.backup_<ts>，不依赖外部
  脚本，单点失败时能直接 mv 回来
- **强确认**：必须输入完整 'YES'（不是 y/yes/Y），防误触

幂等性：清空后再次运行，count=0 行不抛错，备份照旧生成。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.config import CONFIG  # noqa: E402
from app.models import get_engine  # noqa: E402

_TABLES_TO_WIPE = [
    "inventory_events",
    "customers",
    "suppliers",
    "stockpile_snapshots",
    "inventory_imports",
    "stockpile_changes",
]

_FIELDS_TO_RESET = {
    "stockpile": ["auto_category", "auto_category_computed_at"],
}

_TABLES_PRESERVED = [
    "stockpile",
    "stockpile_locations",
    "foreign_customer_records",
    "import_profiles",
    "schema_meta",
    "alembic_version",
]


def _count_table(conn, table: str) -> int:
    return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0


def _backup_db() -> Path:
    src = CONFIG.stockpile_db
    if not src.exists():
        raise FileNotFoundError(f"找不到 DB：{src}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = src.with_name(f"{src.name}.backup_{ts}")
    shutil.copy2(src, dst)
    return dst


def _print_plan(conn) -> dict[str, int]:
    print("=" * 60)
    print("当前 DB 状态 + 清空计划")
    print("=" * 60)

    before: dict[str, int] = {}
    print("\n[将清空] 表名 / 当前行数:")
    for t in _TABLES_TO_WIPE:
        n = _count_table(conn, t)
        before[t] = n
        print(f"  - {t:30s} {n:>10,}")

    print("\n[将重置字段] 表名 / 字段:")
    for t, fields in _FIELDS_TO_RESET.items():
        n = _count_table(conn, t)
        nonnull = []
        for f in fields:
            cnt = conn.execute(text(f"SELECT COUNT(*) FROM {t} WHERE {f} IS NOT NULL")).scalar()
            nonnull.append(f"{f}={cnt}")
        print(f"  - {t:30s} 总 {n:,} / 非空: {', '.join(nonnull)}")

    print("\n[保留不动] 表名 / 当前行数:")
    for t in _TABLES_PRESERVED:
        try:
            n = _count_table(conn, t)
            print(f"  - {t:30s} {n:>10,}")
        except Exception:
            print(f"  - {t:30s} (表不存在或无访问)")

    return before


def _execute_wipe(conn) -> dict[str, int]:
    after: dict[str, int] = {}
    for t in _TABLES_TO_WIPE:
        conn.execute(text(f"DELETE FROM {t}"))
        after[t] = _count_table(conn, t)

    for t, fields in _FIELDS_TO_RESET.items():
        for f in fields:
            conn.execute(text(f"UPDATE {t} SET {f} = NULL"))

    seq_names = ",".join(f"'{t}'" for t in _TABLES_TO_WIPE)
    conn.execute(text(f"DELETE FROM sqlite_sequence WHERE name IN ({seq_names})"))

    return after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不备份不执行")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认（CI 用，谨慎）")
    args = parser.parse_args()

    engine = get_engine()

    with engine.connect() as conn:
        before = _print_plan(conn)

    if args.dry_run:
        print("\n[dry-run] 未执行任何修改。")
        return 0

    if not args.yes:
        print("\n" + "!" * 60)
        print("此操作不可逆。备份会自动生成，但仍请确认。")
        print("!" * 60)
        resp = input("\n输入 YES（全大写）继续，其它任何输入取消: ").strip()
        if resp != "YES":
            print("已取消。")
            return 1

    print("\n[1/3] 备份 DB ...")
    backup_path = _backup_db()
    print(f"      ✓ 备份完成: {backup_path}")
    print(f"        大小: {backup_path.stat().st_size / 1e6:.1f} MB")

    print("\n[2/3] 执行清空 ...")
    with engine.begin() as conn:
        after = _execute_wipe(conn)

    print("\n[3/3] VACUUM 回收空间 ...")
    with engine.connect() as conn:
        conn.execute(text("VACUUM"))

    print("\n" + "=" * 60)
    print("完成。前后行数对比:")
    print("=" * 60)
    print(f"{'表':30s} {'before':>10s} {'after':>10s} {'削减':>10s}")
    for t in _TABLES_TO_WIPE:
        b, a = before[t], after[t]
        print(f"{t:30s} {b:>10,} {a:>10,} {b - a:>10,}")

    print(f"\n备份路径: {backup_path}")
    print("如需回滚: 关闭所有连接后，手动 copy 备份覆盖 stockpile.db")
    return 0


if __name__ == "__main__":
    sys.exit(main())
