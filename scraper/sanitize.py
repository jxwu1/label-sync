"""
脱敏层: 把 staging/ 抓取原始 parquet 转成 sanitized/ 安全上云副本.

规则 (跟 2026-05-20 确认的字段表):
  - customer_name → SHA-256[:16]  (确定性, 同名得同 hash, 不可逆)
  - supplier_name → SHA-256[:16]
  - event_type='purchase' 行: unit_price → None  (进价不上云)
  - event_type='sale' 行的 unit_price 保留 (售价分析需要)
  - 其他字段全部保留

用法:
  python scraper/sanitize.py                          # 批量处理 staging/*.parquet
  python scraper/sanitize.py --input <file>           # 单文件
  python scraper/sanitize.py --input <f> --output <f>

输入: SCRAPE_STAGING_DIR (默认 scraper/staging)
输出: SCRAPE_SANITIZED_DIR (默认 scraper/sanitized)

脱敏后的文件可以安全上服务器, 原始 staging/ 留本地.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else _REPO_ROOT / p


_load_env_file(_HERE / ".env")

STAGING_DIR = _resolve(os.environ.get("SCRAPE_OUTPUT_DIR", "scraper/staging"))
SANITIZED_DIR = _resolve(os.environ.get("SCRAPE_SANITIZED_DIR", "scraper/sanitized"))

_HASH_LEN = 16  # SHA-256 hex 前 16 字符 = 64 bit, 碰撞概率忽略


def _hash_name(value) -> str | None:
    """SHA-256[:16]. 空值返回 None, 同名得同 hash (确定性).

    pd.isna 同时接 None / float NaN / pd.NA (pandas string dtype 用这个),
    比 isinstance(value, float) 检查更全.
    """
    if value is None or pd.isna(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:_HASH_LEN]


def sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """对 events parquet DataFrame 执行脱敏.

    输入: 原始 events_sale_*.parquet 或 events_purchase_*.parquet 的 DataFrame
    输出: 同结构, 但敏感字段已处理. 不修改输入.
    """
    out = df.copy()

    if "customer_name" in out.columns:
        out["customer_name"] = out["customer_name"].apply(_hash_name).astype("string")

    if "supplier_name" in out.columns:
        out["supplier_name"] = out["supplier_name"].apply(_hash_name).astype("string")

    # purchase 行的 unit_price 设 None (进价不上云). sale 行保留.
    if "event_type" in out.columns and "unit_price" in out.columns:
        purchase_mask = out["event_type"] == "purchase"
        if purchase_mask.any():
            out.loc[purchase_mask, "unit_price"] = None

    return out


def sanitize_file(input_path: Path, output_path: Path) -> tuple[int, int]:
    """读取一个 parquet, 脱敏, 写出. 返回 (rows_in, rows_out)."""
    df = pd.read_parquet(input_path)
    n_in = len(df)
    df_clean = sanitize_dataframe(df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_clean.to_parquet(output_path, index=False, engine="pyarrow",
                        compression="zstd", compression_level=9)
    n_out = len(df_clean)
    return n_in, n_out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="脱敏: staging/*.parquet → sanitized/*.parquet (上云用)",
    )
    parser.add_argument(
        "--input",
        help="单文件路径; 不指定则批量处理 staging/events_*.parquet",
    )
    parser.add_argument(
        "--output",
        help="单文件输出路径 (仅 --input 时使用); 默认 sanitized/<同名>",
    )
    args = parser.parse_args()

    if args.input:
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"❌ 输入文件不存在: {in_path}", file=sys.stderr)
            return 1
        out_path = Path(args.output) if args.output else SANITIZED_DIR / in_path.name
        print(f"[1/1] {in_path.name} → {out_path}")
        n_in, n_out = sanitize_file(in_path, out_path)
        print(f"    ✓ {n_in} → {n_out} 行")
        return 0

    if not STAGING_DIR.exists():
        print(f"❌ staging 目录不存在: {STAGING_DIR}", file=sys.stderr)
        return 1
    files = sorted(STAGING_DIR.glob("events_*.parquet"))
    if not files:
        print(f"⚠️  staging 目录里没有 events_*.parquet: {STAGING_DIR}")
        return 0

    print(f"批量脱敏 {len(files)} 个文件")
    print(f"  输入: {STAGING_DIR}")
    print(f"  输出: {SANITIZED_DIR}")
    print()
    for i, f in enumerate(files, 1):
        out = SANITIZED_DIR / f.name
        print(f"[{i}/{len(files)}] {f.name}")
        n_in, n_out = sanitize_file(f, out)
        print(f"    ✓ {n_in} → {n_out} 行")
    print(f"\n✅ 完成, 安全副本在 {SANITIZED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
