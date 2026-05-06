"""tools/inventory_admin.py 关键纯函数测试。"""

import sys
from pathlib import Path

import pytest

# 让 tests 能 import tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from inventory_admin import _infer_event_type  # noqa: E402


@pytest.mark.parametrize(
    "filename,expected",
    [
        # 中文关键词
        ("采购订单_2026Q1.xls", "purchase"),
        ("销售订单_2026Q1.xls", "sale"),
        ("2026年4月采购.xls", "purchase"),
        # 英文关键词
        ("purchases_2026Q1.xls", "purchase"),
        ("sales_2026Q1.xls", "sale"),
        ("Sale_April.xls", "sale"),
        ("PURCHASE_April.xls", "purchase"),
        ("buy_orders.xls", "purchase"),
        # 推断不出
        ("orders.xls", None),
        ("export.xls", None),
        ("", None),
        # 边界：sale 优先于 purchase（避免 "purchaseXsale" 这种边缘混淆）
        # 实际 ERP 不会出这种文件名，但稳定语义有用
    ],
)
def test_infer_event_type(filename: str, expected: str | None) -> None:
    assert _infer_event_type(filename) == expected
