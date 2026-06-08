"""scraper 文件名 → 抓取窗口判断 (单一真源).

两层护栏复用:
  - sanitize.py 第一层: weekly_violation 命中且无 --allow-backfill → 拒绝产出
  - run_weekly.ps1 第二层: scrape_window.py --check <dir> manifest 闸

纯函数 weekly_violation 接 today 参数 (测试传固定日期, 不依赖系统时钟).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_DATE = r"\d{4}-\d{2}-\d{2}"
_EVENTS_RE = re.compile(rf"^events_[a-z]+_({_DATE})_({_DATE})\.")
_SNAPSHOT_RE = re.compile(rf"^inventory_snapshot_({_DATE})\.")
_MASTER_RE = re.compile(rf"^product_master_({_DATE})\.")


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_window(filename: str) -> tuple[str, date | None, date | None]:
    """(kind, start, end). kind 由前缀决定, 不是解析成功与否.

    匹配目标前缀但日期坏 → kind 保持前缀、日期 None (区分坏命名目标 vs 无关文件).
    """
    name = Path(filename).name
    if name.startswith("events_"):
        m = _EVENTS_RE.match(name)
        if m:
            s, e = _parse_date(m.group(1)), _parse_date(m.group(2))
            if s is None or e is None:
                return ("events", None, None)
            return ("events", s, e)
        return ("events", None, None)
    if name.startswith("inventory_snapshot_"):
        m = _SNAPSHOT_RE.match(name)
        if m:
            d = _parse_date(m.group(1))
            return ("snapshot", d, d)
        return ("snapshot", None, None)
    if name.startswith("product_master_"):
        m = _MASTER_RE.match(name)
        if m:
            d = _parse_date(m.group(1))
            return ("master", d, d)
        return ("master", None, None)
    return ("unknown", None, None)


def weekly_violation(
    filename: str,
    today: date,
    max_span_days: int = 14,
    max_age_days: int = 14,
) -> str | None:
    """周任务护栏: 返回违规原因字符串, 合规返回 None.

    span > max_span_days 才拒 (== 放行); start < today-max_age_days 才拒 (== 放行).
    """
    name = Path(filename).name
    kind, start, end = parse_window(name)
    if kind == "unknown":
        return None
    if kind == "master":
        if start is None:
            return f"日期解析失败: {name}"
        return None
    if kind == "snapshot":
        if start is None:
            return f"日期解析失败: {name}"
        if start < today - timedelta(days=max_age_days):
            return f"陈旧快照 {start} (早于 {today - timedelta(days=max_age_days)})"
        return None
    # events
    if start is None or end is None:
        return f"日期解析失败: {name}"
    span = (end - start).days
    if span > max_span_days:
        return f"日期跨度 {span} 天 > {max_span_days} ({start}→{end})"
    if start < today - timedelta(days=max_age_days):
        return f"起始日 {start} 太旧 (早于 {today - timedelta(days=max_age_days)})"
    return None


_GLOBS = (
    "events_*.parquet",
    "inventory_snapshot_*.parquet",
    "product_master_*.parquet",
)


def _iter_target_files(directory: str) -> list[Path]:
    p = Path(directory)
    found: list[Path] = []
    for pattern in _GLOBS:
        found.extend(p.glob(pattern))
    return sorted(set(found))


def run_check(
    directory: str,
    today: date,
    max_total_mb: float = 50.0,
    allow_backfill: bool = False,
) -> int:
    """扫描 directory 下目标文件, 打印 manifest (按 kind), 违规/超量返回 1."""
    files = _iter_target_files(directory)
    print(f"manifest: {directory} ({len(files)} 个目标文件)")
    total = 0
    for f in files:
        kind, _, _ = parse_window(f.name)
        size = f.stat().st_size
        total += size
        print(f"  [{kind}] {f.name}  ({size / 1024 / 1024:.2f} MB)")
    total_mb = total / 1024 / 1024
    print(f"  总大小: {total_mb:.2f} MB")

    if allow_backfill:
        print("✅ --allow-backfill: 跳过历史/大小闸")
        return 0

    failed: list[str] = []
    for f in files:
        reason = weekly_violation(f.name, today)
        if reason:
            failed.append(f"{f.name}: {reason}")
    if total_mb > max_total_mb:
        failed.append(f"<total>: 总大小 {total_mb:.1f}MB > {max_total_mb}MB")

    if failed:
        print("❌ manifest 闸拦截:")
        for line in failed:
            print(f"  - {line}")
        return 1
    print("✅ manifest 闸通过")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="scrape_window manifest 闸: 扫描目录, 历史/超量文件 → 退出码 1",
    )
    parser.add_argument("--check", metavar="DIR", required=True, help="待检查目录")
    parser.add_argument("--max-total-mb", type=float, default=50.0)
    parser.add_argument("--allow-backfill", action="store_true")
    args = parser.parse_args(argv)
    return run_check(args.check, date.today(), args.max_total_mb, args.allow_backfill)


if __name__ == "__main__":
    sys.exit(main())
