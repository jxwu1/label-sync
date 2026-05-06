"""批量重算所有 active SKU 的 auto_category（PR 5.1）。

用法（项目根目录下）：
    python tools/recompute_categories.py            # 用今天作为 as_of
    python tools/recompute_categories.py --as-of 2026-04-01  # 历史回放

定时跑：在系统层挂 cron / Task Scheduler 调本脚本。
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows PowerShell 默认 GBK，强制 UTF-8 避免遇中文 crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analytics_service import recompute_categories  # noqa: E402


def _parse_as_of(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(description="重算 SKU auto_category")
    parser.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=None,
        help="参考日（YYYY-MM-DD），默认今天",
    )
    args = parser.parse_args()

    result = recompute_categories(as_of=args.as_of)
    print(f"computed: {result['computed']} SKU")
    print(f"duration: {result['duration_s']}s")
    print("by_category:")
    for cat, n in sorted(result["by_category"].items(), key=lambda x: -x[1]):
        print(f"  {cat:14s} {n}")


if __name__ == "__main__":
    main()
