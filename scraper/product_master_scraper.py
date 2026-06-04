"""
boson ERP 产品总档抓取 (替代月度手动 import).

跟 sales / purchase / inventory 三个 scraper 的关键差异:
  - 用 product_data_export.php?action=export 直接下载 CSV/xlsx (不是 HTML 表)
  - 不切片月份, 一次性全量
  - 不带 PII (公司名 supplier_name, 不哈希)
  - 跑频率: 月度 (run_weekly.ps1 里 IsoWeek==1 才触发)

用法:
  python scraper/product_master_scraper.py            # 默认今天的快照
  python scraper/product_master_scraper.py --date 2026-05-21

输出: SCRAPE_OUTPUT_DIR/product_master_<date>.parquet (原始列名透传, 给
      server 端 product_master.py importer 用 DEFAULT_PRODUCT_MAPPING).
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

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

BOSON_BASE_URL = os.environ.get("BOSON_BASE_URL", "http://bosonapp.local:8137")
URL = f"{BOSON_BASE_URL}/boson/product_data_export.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": BOSON_BASE_URL,
    "Referer": f"{BOSON_BASE_URL}/boson/product_search_reg.php?mode=all&menu_id=340",
}

_COOKIE_FILE = _resolve(os.environ.get("SCRAPE_COOKIE_FILE", "scraper/cookie.txt"))
if not _COOKIE_FILE.exists():
    sys.exit(
        f"cookie file missing: {_COOKIE_FILE}\n"
        f"create from scraper/cookie.txt.example, 粘贴 PHPSESSID 进去"
    )
_PHPSESSID = _COOKIE_FILE.read_text(encoding="utf-8").strip()
if not _PHPSESSID or _PHPSESSID.startswith("#"):
    sys.exit(f"cookie file is empty or only comments: {_COOKIE_FILE}")

COOKIES = {
    "discount_base_kind": "discount_percent",
    "commission_tax_include_status": "N",
    "PHPSESSID": _PHPSESSID,
}

OUTPUT_DIR = _resolve(os.environ.get("SCRAPE_OUTPUT_DIR", "scraper/staging"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# action=export + valid_grade>=0 → 全部 SKU (含 ERP 等级 0/停用)
# current_menu_name=销售列表 是 ERP 想要的页面上下文标识, 必传
PARAMS = {
    "action": "export",
    "product_kind_id": "",
    "stack_kind_id": "",
    "product_brand": "",
    "produce_type": "",
    "product_model": "",
    "begin_product_model": "",
    "end_product_model": "",
    "product_description": "",
    "valid_grade_symbol": ">=",
    "valid_grade": "0",
    "client_id": "",
    "store_id": "",
    "stockpile_shelf": "",
    "begin_stockpile_quantity": "",
    "end_stockpile_quantity": "",
    "current_menu_name": "销售列表",
}


def _parse_response_to_df(content: bytes, content_type: str) -> pd.DataFrame | None:
    """ERP 产品导出可能是 xlsx 或 CSV. 试 Excel → 失败 → 试 CSV (UTF-8 / GBK)."""
    ct = (content_type or "").lower()

    if "spreadsheet" in ct or "excel" in ct or "openxmlformats" in ct:
        try:
            return pd.read_excel(io.BytesIO(content), engine="openpyxl")
        except Exception as e:
            print(f"    Excel parse 失败: {e}, 退到 CSV")

    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            df = pd.read_csv(io.BytesIO(content), encoding=enc, dtype=str)
            print(f"    解码成功: {enc}")
            return df
        except Exception:
            continue

    # 兜底再试一次 Excel (有时 content-type 不准)
    try:
        return pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except Exception:
        pass
    return None


def fetch_product_master(retry: int = 2) -> pd.DataFrame | None:
    for attempt in range(retry + 1):
        try:
            t0 = time.time()
            r = requests.get(URL, params=PARAMS, headers=HEADERS, cookies=COOKIES, timeout=600)
            elapsed = time.time() - t0
            size_mb = len(r.content) / 1024 / 1024
            ct = r.headers.get("content-type", "")
            print(f"    HTTP {r.status_code}, {size_mb:.2f} MB, {elapsed:.1f}s, content-type={ct}")

            if r.status_code != 200 or len(r.content) < 1000:
                print(f"    ⚠️ 响应太短 ({len(r.content)} 字节), 可能 cookie 失效或参数错")
                if attempt < retry:
                    time.sleep(5)
                    continue
                return None

            df = _parse_response_to_df(r.content, ct)
            if df is None or len(df) == 0:
                print("    ⚠️ 无法解析响应为 DataFrame")
                debug_path = OUTPUT_DIR / "product_master_raw_debug.bin"
                debug_path.write_bytes(r.content[:200_000])
                print(f"    前 200KB 已存到 {debug_path}, 检查格式后调整 _parse_response_to_df")
                return None

            print(f"    {len(df)} 行 × {len(df.columns)} 列")
            return df
        except Exception as e:
            print(f"    ❌ 第 {attempt + 1} 次失败: {e}")
            if attempt < retry:
                time.sleep(5)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="boson ERP 产品总档抓取 (月度全量, 不哈希 supplier_name)",
        epilog="cookie 失效时去 scraper/cookie.txt 换 PHPSESSID",
    )
    parser.add_argument(
        "--date",
        dest="snapshot_date",
        type=date.fromisoformat,
        default=date.today(),
        help="文件名日期标签 YYYY-MM-DD (默认: 今天)",
    )
    args = parser.parse_args()
    snapshot_date = args.snapshot_date.isoformat()

    output_parquet = OUTPUT_DIR / f"product_master_{snapshot_date}.parquet"
    print(f"抓产品总档: {snapshot_date}")
    print(f"输出 parquet: {output_parquet}")
    print()

    df = fetch_product_master()
    if df is None:
        print("❌ 抓取失败")
        return 1

    if "product_barcode" not in df.columns:
        print(f"⚠️ 响应缺 product_barcode 列. 拿到的列: {list(df.columns)[:30]}")
        print("   importer 那侧会全跳过, 检查 ERP 导出列名是否变了.")

    # 列名透传, server 端 product_master.py 用 DEFAULT_PRODUCT_MAPPING (英文列名) 解析,
    # 跟现有月度手动 import 路径一致.
    df.to_parquet(
        output_parquet, index=False, engine="pyarrow", compression="zstd", compression_level=9
    )
    print(f"  parquet: {output_parquet.stat().st_size / 1024 / 1024:.2f} MB")

    print("\n=== 前 3 行 (列名透传) ===")
    print(df.head(3).to_string(max_cols=10))
    print(f"\n=== 全部列 ({len(df.columns)}) ===")
    print(", ".join(str(c) for c in df.columns))

    print("\n✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
