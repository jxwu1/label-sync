"""ERP 抓取 parquet 的清洗层。

输入：原始 parquet（ERP 抓取脚本输出）
输出：
- cleaned parquet（进 DB 的干净数据）
- archive parquet（内部账户 999*，存档但不进 DB）
- CleaningReport（每条规则剔了多少行）

规则（按执行顺序）：
1. 硬剔：product_barcode == '90000000001'（税行，发票上的税额行不是商品）
2. 硬剔：len(product_barcode) >= 15（POS 双扫拼接错误，前面发现 1 行 26 位 + 1 行 15 位）
3. 完全重复行去重（同 inventory_events UNIQUE 约束的 7 列子集）
4. 拆分：customer_id 以 '999' 开头 → archive，不进 cleaned

保留不动（不是错误）：
- erp_category_code == '0'（停用条码，仍可能卖/进，用户明确要求保留）
- qty < 0（退货，用户明确不用管）
- qty == 0（扫描错，用户明确不用管）
- product_barcode 长度 1（购物袋无条码，"0"/"1"，用户明确保留）
- product_barcode 长度 14（EAN-14 国际标准）

设计取舍：
- 纯函数 + 显式 IO 分离：`_apply_rules(df)` 是 pure，便于单测；
  `clean_events_parquet(src, dst_cleaned, dst_archive)` 只做读写
- 不依赖 DB schema，独立于 inventory_importer
- 报告用 dataclass 不用 dict，调用方能拿 .rows_out 等属性
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

TAX_BARCODE = "90000000001"
CONCAT_BARCODE_MIN_LEN = 15
INTERNAL_CUSTOMER_PREFIX = "999"

# 重复行去重键（对齐 inventory_events UNIQUE 约束的 7 列）
DEDUP_KEY = [
    "event_type",
    "document_no",
    "shipping_doc",
    "product_barcode",
    "event_at",
    "qty",
    "unit_price",
]


@dataclass
class CleaningReport:
    src_path: str
    rows_in: int = 0
    dropped_tax_rows: int = 0
    dropped_concat_barcode: int = 0
    dropped_duplicates: int = 0
    archived_internal: int = 0
    rows_out: int = 0
    irregular_barcode_count: int = 0
    irregular_barcode_samples: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"=== 清洗报告: {Path(self.src_path).name} ===\n"
            f"原始行数:               {self.rows_in:>10,}\n"
            f"剔除税行(90000000001):  {-self.dropped_tax_rows:>10,}\n"
            f"剔除拼接条码(len>=15):  {-self.dropped_concat_barcode:>10,}\n"
            f"完全重复行去重:         {-self.dropped_duplicates:>10,}\n"
            f"内部账户存档(999*):     {-self.archived_internal:>10,}\n"
            f"{'-' * 40}\n"
            f"最终 cleaned:           {self.rows_out:>10,}\n"
            f"\n"
            f"[仅提示] 条码长度异常但保留: {self.irregular_barcode_count} 笔"
            + (
                f"  样本: {self.irregular_barcode_samples[:3]}"
                if self.irregular_barcode_samples
                else ""
            )
        )


def _drop_tax_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    mask = df["product_barcode"].astype(str) == TAX_BARCODE
    return df[~mask].copy(), int(mask.sum())


def _drop_concat_barcode(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    lens = df["product_barcode"].astype(str).str.len()
    mask = lens >= CONCAT_BARCODE_MIN_LEN
    return df[~mask].copy(), int(mask.sum())


def _drop_exact_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """按 inventory_events UNIQUE 约束的 7 列去重。"""
    keys = [k for k in DEDUP_KEY if k in df.columns]
    if not keys:
        return df, 0
    before = len(df)
    out = df.drop_duplicates(subset=keys, keep="first").copy()
    return out, before - len(out)


def _split_internal_accounts(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """拆出 customer_id 以 '999' 开头的内部账户。

    NaN customer_id 算 cleaned（不是内部账户，是匿名销售）。
    """
    cid = df["customer_id"].astype(str).fillna("")
    mask = cid.str.startswith(INTERNAL_CUSTOMER_PREFIX)
    archive = df[mask].copy()
    cleaned = df[~mask].copy()
    return cleaned, archive, int(mask.sum())


def _count_irregular_barcodes(df: pd.DataFrame) -> tuple[int, list[str]]:
    """仅统计不剔。长度不在 {1, 13, 14} 且不是税号的行。"""
    bc = df["product_barcode"].astype(str)
    lens = bc.str.len()
    irregular = (~lens.isin([1, 13, 14])) & (bc != TAX_BARCODE)
    samples = bc[irregular].drop_duplicates().head(5).tolist()
    return int(irregular.sum()), samples


def _apply_rules(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, CleaningReport]:
    """对 DataFrame 应用所有清洗规则。pure function，便于单测。"""
    report = CleaningReport(src_path="<in-memory>", rows_in=len(df))

    df, report.dropped_tax_rows = _drop_tax_rows(df)
    df, report.dropped_concat_barcode = _drop_concat_barcode(df)
    df, report.dropped_duplicates = _drop_exact_duplicates(df)
    cleaned, archive, report.archived_internal = _split_internal_accounts(df)

    report.rows_out = len(cleaned)
    report.irregular_barcode_count, report.irregular_barcode_samples = _count_irregular_barcodes(
        cleaned
    )

    return cleaned, archive, report


def clean_events_parquet(
    src: Path | str,
    dst_cleaned: Path | str,
    dst_archive: Path | str | None = None,
) -> CleaningReport:
    """清洗单个 parquet。

    Args:
        src: 原始 parquet
        dst_cleaned: 输出干净 parquet
        dst_archive: 输出存档 parquet（内部账户）。None 则丢弃存档

    Returns:
        CleaningReport
    """
    src = Path(src)
    dst_cleaned = Path(dst_cleaned)
    dst_archive = Path(dst_archive) if dst_archive else None

    df = pd.read_parquet(src)
    cleaned, archive, report = _apply_rules(df)
    report.src_path = str(src)

    dst_cleaned.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(dst_cleaned, compression="zstd", index=False)

    if dst_archive and len(archive) > 0:
        dst_archive.parent.mkdir(parents=True, exist_ok=True)
        archive.to_parquet(dst_archive, compression="zstd", index=False)

    return report
