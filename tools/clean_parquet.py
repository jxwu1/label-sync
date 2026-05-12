"""清洗 ERP 抓取 parquet（在导入 DB 之前）。

用法（项目根目录）:
    单文件:
        python tools/clean_parquet.py raw/events_sale_2025.parquet
            → 默认输出: cleaned/events_sale_2025.cleaned.parquet
                       archive/events_sale_2025.archive.parquet

    指定输出:
        python tools/clean_parquet.py raw/foo.parquet \\
            --out cleaned/bar.parquet --archive archive/bar.parquet

    批量 (glob):
        python tools/clean_parquet.py "raw/*.parquet" \\
            --out-dir cleaned/ --archive-dir archive/

    丢弃内部账户（不存档）:
        python tools/clean_parquet.py raw/foo.parquet --no-archive

Pipeline 位置:
    [ERP 抓取] → raw parquet → [本脚本] → cleaned parquet
        → tools/inventory_admin.py import-batch → DB
"""

from __future__ import annotations

import argparse
import sys
from glob import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from etl.parquet_cleaner import clean_events_parquet  # noqa: E402


def _derive_paths(
    src: Path,
    out_dir: Path | None,
    archive_dir: Path | None,
    explicit_out: Path | None,
    explicit_archive: Path | None,
    no_archive: bool,
) -> tuple[Path, Path | None]:
    if explicit_out:
        out = explicit_out
    elif out_dir:
        out = out_dir / f"{src.stem}.cleaned.parquet"
    else:
        out = src.parent.parent / "cleaned" / f"{src.stem}.cleaned.parquet"

    if no_archive:
        return out, None

    if explicit_archive:
        arc = explicit_archive
    elif archive_dir:
        arc = archive_dir / f"{src.stem}.archive.parquet"
    else:
        arc = src.parent.parent / "archive" / f"{src.stem}.archive.parquet"

    return out, arc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", help="源 parquet 路径或 glob 模式")
    parser.add_argument("--out", type=Path, help="单文件指定输出路径")
    parser.add_argument("--archive", type=Path, help="单文件指定 archive 路径")
    parser.add_argument("--out-dir", type=Path, help="批量输出目录")
    parser.add_argument("--archive-dir", type=Path, help="批量 archive 目录")
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="丢弃内部账户，不输出 archive 文件",
    )
    args = parser.parse_args()

    files = [Path(p) for p in glob(args.src)]
    if not files:
        print(f"未找到匹配的文件: {args.src}")
        return 1

    if len(files) > 1 and (args.out or args.archive):
        print("批量模式（多文件）不能用 --out / --archive；请用 --out-dir / --archive-dir")
        return 1

    print(f"将处理 {len(files)} 个文件\n")

    totals = {
        "rows_in": 0,
        "dropped_tax": 0,
        "dropped_concat": 0,
        "dropped_dup": 0,
        "archived": 0,
        "rows_out": 0,
        "irregular": 0,
    }

    for src in files:
        out, arc = _derive_paths(
            src,
            args.out_dir,
            args.archive_dir,
            args.out,
            args.archive,
            args.no_archive,
        )
        report = clean_events_parquet(src, out, arc)
        print(report.summary())
        print(f"  → cleaned: {out}")
        if arc and report.archived_internal > 0:
            print(f"  → archive: {arc}")
        print()

        totals["rows_in"] += report.rows_in
        totals["dropped_tax"] += report.dropped_tax_rows
        totals["dropped_concat"] += report.dropped_concat_barcode
        totals["dropped_dup"] += report.dropped_duplicates
        totals["archived"] += report.archived_internal
        totals["rows_out"] += report.rows_out
        totals["irregular"] += report.irregular_barcode_count

    if len(files) > 1:
        print("=" * 60)
        print(f"汇总（{len(files)} 文件）")
        print("=" * 60)
        print(f"原始总行数:           {totals['rows_in']:>12,}")
        print(f"剔除税行:             {-totals['dropped_tax']:>12,}")
        print(f"剔除拼接条码:         {-totals['dropped_concat']:>12,}")
        print(f"完全重复行去重:       {-totals['dropped_dup']:>12,}")
        print(f"内部账户存档:         {-totals['archived']:>12,}")
        print(f"{'-' * 40}")
        print(f"最终 cleaned 总数:    {totals['rows_out']:>12,}")
        print(f"[提示] 条码异常保留:  {totals['irregular']:>12,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
