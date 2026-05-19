"""SKU 来源分群 (FOREIGN / CN / unknown).

业务背景: 用户 (jxwu) 只关心国外供应商的货 (FOREIGN), 国内供应商
(CN) 的数据由同事负责. 分析侧需要按来源筛选回测/dashboard 指标.

规则 (用户 2026-05-19 确认):

1. **supplier_id 前缀优先**:
   - CN... → CN
   - GR/ES/TR/BG/NE/IT... → FOREIGN
2. **无采购记录回退 model 长度** (启发式, ~83% FOREIGN 准确率):
   - len(product_model) == 5  → CN
   - len(product_model) == 13 → FOREIGN
   - 其他 → unknown

DB 数据 (2026-05-19): supplier_id 前缀分布 CN 534 / GR 44 / ES 5 /
TR 1 / BG 1 / NE 1 / IT 1.
"""

from __future__ import annotations

# 国外供应商国家代码 (希腊为主)
_FOREIGN_PREFIXES: frozenset[str] = frozenset({"GR", "ES", "TR", "BG", "NE", "IT"})
_CN_PREFIX = "CN"


def classify_origin(supplier_id: str | None, product_model: str | None) -> str:
    """单 SKU 来源分类. 返回 'FOREIGN' / 'CN' / 'unknown'."""
    if supplier_id:
        prefix = supplier_id[:2].upper()
        if prefix == _CN_PREFIX:
            return "CN"
        if prefix in _FOREIGN_PREFIXES:
            return "FOREIGN"
    if product_model:
        n = len(product_model)
        if n == 5:
            return "CN"
        if n == 13:
            return "FOREIGN"
    return "unknown"


# ----- SQL CTE -------------------------------------------------------------

# 给 SKU 来源打标的 CTE 片段, JOIN 到 backtest_results / stockpile 用.
#
# 输出列:
#   product_barcode, origin (FOREIGN/CN/unknown)
#
# 优先级 (跟 classify_origin Python 实现保持一致):
#   1. 若 inventory_events 里该 barcode 有 purchase 事件且 supplier_id 非空,
#      取**最近一次** purchase 的 supplier_id 前缀分类.
#   2. 否则按 stockpile.product_model 长度回退.
ORIGIN_CTE_SQL = """\
WITH latest_purchase AS (
    SELECT DISTINCT ON (product_barcode)
        product_barcode,
        supplier_id
    FROM inventory_events
    WHERE event_type = 'purchase' AND supplier_id IS NOT NULL
    ORDER BY product_barcode, event_at DESC
),
sku_origin AS (
    SELECT
        s.product_barcode,
        CASE
            WHEN UPPER(LEFT(lp.supplier_id, 2)) = 'CN' THEN 'CN'
            WHEN UPPER(LEFT(lp.supplier_id, 2)) IN ('GR','ES','TR','BG','NE','IT') THEN 'FOREIGN'
            WHEN LENGTH(s.product_model) = 5  THEN 'CN'
            WHEN LENGTH(s.product_model) = 13 THEN 'FOREIGN'
            ELSE 'unknown'
        END AS origin
    FROM stockpile s
    LEFT JOIN latest_purchase lp ON lp.product_barcode = s.product_barcode
)
"""
