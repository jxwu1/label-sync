"""
boson ERP 库存快照抓取 (point-in-time 全量, 不按月切片).

跟 sales/purchase 的关键差异:
  - 触发字段: stockpile=库存 (取代 sales 的 range[7]=sale)
  - 不是事件流, 是 per-SKU 当前库存的快照
  - 单日期参数 (begin_date=end_date), 表示"以这一天为准"
  - 输出 schema 由 ERP 返回列决定 (v1 raw, 标准化留给 v2)

用法:
  python scraper/inventory_scraper.py                   # 默认今天
  python scraper/inventory_scraper.py --date 2026-05-20

输出: SCRAPE_OUTPUT_DIR/inventory_snapshot_<date>.parquet (raw)
        + inventory_snapshot_<date>.xlsx (人工核对用)

v1 不做 schema 转换. 跑完后看打印的列名 + 头几行, 跟 sales/purchase 对一下,
再决定标准化映射. 长期落 stockpile_inventory_snapshot 表 (新表).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from io import StringIO
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
URL = f"{BOSON_BASE_URL}/boson/product_search_list.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": BOSON_BASE_URL,
    "Referer": f"{BOSON_BASE_URL}/boson/product_search_reg.php?mode=all&menu_id=340",
    "Content-Type": "application/x-www-form-urlencoded",
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

# form_data 跟 sales/purchase 共用 99%, 只有触发字段 stockpile=库存 不同
form_data_template = {
    "root_kind_length": "", "search_time_type": "", "classify_kind_id": "",
    "sign_type": "", "product_kind_id": "", "product_kind_name": "",
    "stack_kind_id": "", "stack_kind_name": "", "product_model": "",
    "document_valid_grade": ">=1", "audit_status": "", "document_kind_id": "",
    "store_id": "", "begin_product_model": "", "end_product_model": "",
    "valid_grade_range": "", "product_batch": "", "valid_grade_symbol": "=",
    "valid_grade": "", "produce_type": "", "product_barcode": "",
    "sequence_number": "", "begin_product_barcode": "", "end_product_barcode": "",
    "client_model": "", "provider_model": "", "begin_unit_price": "",
    "end_unit_price": "", "begin_stockpile_quantity": "",
    "end_stockpile_quantity": "", "product_description": "",
    "description_length": "15", "stockpile_shelf": "", "stockpile_location": "",
    "product_color": "", "product_size": "", "material_description": "",
    "spec_description": "", "document_id": "", "client_document_id": "",
    "product_brand": "", "produce_area": "", "item_remark": "",
    "document_remark": "", "payment_kind_id": "", "source_kind_id": "",
    "industry_kind_id": "", "handler_id": "", "handler_name": "",
    "creator_id": "", "creator_name": "", "web_status_select": "",
    "recommend_status_select": "", "invoice_limit_select": "",
    "discount_limit_select": "", "client_valid_grade_range": "",
    "group_kind_id": "", "money_rate_id": "103", "client_id": "",
    "client_name": "", "client_title": "", "content_type": ".php",
    "language_id": "101",
    # 库存查询的触发字段 (来自 F12 cURL 抓包, 2026-05-20):
    "stockpile": "库存",
    "interval_days": "1",
    "document_list_report": "", "time_type": "month", "limit_sum": "",
}


# ============ Schema 转换 (v2, 2026-05-20 锁定) ============
# 砍掉 ERP 默认输出的 30 列里 ~28 列无用字段, 只保留补货决策需要的 10 列.
# barcode 不在 ERP 输出里, 服务器侧用 product_model JOIN stockpile 反查
# (规则: A. model==barcode 直接, B. model==barcode[:-1][-5:]).
_KEEP_COLS = {
    "型号": "product_model",
    "品名": "product_name_zh",
    "种类ID号": "erp_category_code",
    "种类名称": "erp_category_raw",
    "最后采购": "last_purchase_at",
    "最后入库": "last_arrival_at",
    "店面库存": "qty_store",
    "库存小计": "qty_total",
    "下限": "reorder_min",
    "上限": "reorder_max",
}


def to_standard_schema(df: pd.DataFrame, snapshot_date: str) -> pd.DataFrame:
    """ERP raw 库存表 → 标准 schema. 砍多余列 + 改名 + 类型规整."""
    missing = [c for c in _KEEP_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"ERP 库存表缺列: {missing}; 拿到的列: {list(df.columns)}"
        )
    std = df[list(_KEEP_COLS)].copy()
    std.columns = list(_KEEP_COLS.values())

    std.insert(0, "snapshot_date", snapshot_date)

    # 字符串列
    for col in ("product_model", "product_name_zh", "erp_category_code",
                "erp_category_raw", "last_purchase_at", "last_arrival_at"):
        std[col] = std[col].astype("string").replace(
            {"": None, "nan": None, "None": None, "<NA>": None}
        )

    # 整数列 (允许 None, 用 Int64)
    for col in ("qty_store", "qty_total", "reorder_min", "reorder_max"):
        std[col] = pd.to_numeric(std[col], errors="coerce").astype("Int64")

    # 必填: product_model + qty_total
    before = len(std)
    std = std.dropna(subset=["product_model", "qty_total"])
    if len(std) < before:
        print(f"    过滤掉 {before - len(std)} 行缺 product_model/qty_total")

    return std


def fetch_snapshot(snapshot_date: str, retry: int = 2) -> pd.DataFrame | None:
    """单次拉库存快照. snapshot_date YYYY-MM-DD 字符串."""
    form_data = dict(form_data_template)
    form_data["begin_date"] = snapshot_date
    form_data["end_date"] = snapshot_date

    for attempt in range(retry + 1):
        try:
            t0 = time.time()
            r = requests.post(URL, data=form_data, headers=HEADERS,
                              cookies=COOKIES, timeout=600)
            r.encoding = "utf-8"
            size_mb = len(r.content) / 1024 / 1024
            elapsed = time.time() - t0

            if len(r.content) < 50000:
                print(f"    ⚠️ 响应仅 {len(r.content)} 字节,可能 cookie 失效")
                if attempt < retry:
                    time.sleep(5)
                    continue
                return None

            tables = pd.read_html(StringIO(r.text))
            if not tables:
                print("    ⚠️ 响应里没找到 table")
                return None

            df = max(tables, key=len)
            df = df.drop(columns=['Unnamed: 0', 'Unnamed: 1'], errors='ignore')
            print(f"    响应 {size_mb:.1f} MB, 用时 {elapsed:.1f}s, {len(df)} 行 × {len(df.columns)} 列")
            return df
        except Exception as e:
            print(f"    ❌ 第 {attempt + 1} 次失败: {e}")
            if attempt < retry:
                time.sleep(5)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="boson ERP 库存快照抓取 (raw v1, 不做 schema 标准化)",
        epilog="cookie 失效时去 scraper/cookie.txt 换 PHPSESSID",
    )
    parser.add_argument(
        "--date", dest="snapshot_date", type=date.fromisoformat,
        default=date.today(),
        help="快照日期 YYYY-MM-DD (默认: 今天)",
    )
    args = parser.parse_args()
    snapshot_date = args.snapshot_date.isoformat()

    output_parquet = OUTPUT_DIR / f"inventory_snapshot_{snapshot_date}.parquet"
    output_xlsx = OUTPUT_DIR / f"inventory_snapshot_{snapshot_date}.xlsx"

    print(f"抓库存快照: {snapshot_date}")
    print(f"输出 parquet: {output_parquet}")
    print(f"输出 xlsx:    {output_xlsx}")
    print()

    df_raw = fetch_snapshot(snapshot_date)
    if df_raw is None or len(df_raw) == 0:
        print("❌ 抓取失败, 无数据")
        return 1

    print(f"\n=== 原始 ERP 表 {len(df_raw)} 行 × {len(df_raw.columns)} 列 ===")
    print(f"\n=== 转换为标准 schema ({len(_KEEP_COLS)} 列) ===")
    try:
        df_std = to_standard_schema(df_raw, snapshot_date)
    except ValueError as e:
        print(f"❌ schema 转换失败: {e}")
        return 1
    print(f"  最终 {len(df_std)} 行 × {len(df_std.columns)} 列")

    print("\n=== 前 5 行 (cleaned) ===")
    print(df_std.head(5).to_string())

    print("\n=== 写 parquet ===")
    df_std.to_parquet(output_parquet, index=False, engine="pyarrow",
                      compression="zstd", compression_level=9)
    print(f"  {output_parquet.stat().st_size / 1024 / 1024:.1f} MB")

    print("\n=== 写 xlsx (人工核对用) ===")
    df_std.to_excel(output_xlsx, index=False, engine="openpyxl")
    print(f"  {output_xlsx.stat().st_size / 1024 / 1024:.1f} MB")

    print("\n✅ 完成. 下一步: 试跑成功后, 服务器侧建表 + 写 import.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
