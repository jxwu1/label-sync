"""ERP 产品种类字段解析：拆 `<code> - <description>` 两段。

源 ERP 导出的「产品种类」格式如：`FL017-11 - 塑料大盒子ΠΛΑΣΤΙΚΕΣ_ΚΟΥΤΙ_...`
入库时既保留原字符串（防解析失败），也拆出 code 供分析用。
"""

import pytest

from app.parsers.erp_category import parse_erp_category


@pytest.mark.parametrize(
    "raw,expected_code,expected_desc",
    [
        # 标准格式
        (
            "FL017-11 - 塑料大盒子ΠΛΑΣΤΙΚΕΣ_ΚΟΥΤΙ_ΑΠΟΘΗΚΕΥΣΗΣ",
            "FL017-11",
            "塑料大盒子ΠΛΑΣΤΙΚΕΣ_ΚΟΥΤΙ_ΑΠΟΘΗΚΕΥΣΗΣ",
        ),
        # 简单 4 字符码
        ("FL004 - 渔具系列", "FL004", "渔具系列"),
        # A 系列老编码（多层级深码）
        (
            "A002-021001 - 汽车-工具 固定工具 卡扣",
            "A002-021001",
            "汽车-工具 固定工具 卡扣",
        ),
        # 描述里有 " - "（应只在第一个 " - " 处分割）
        ("FL001 - 渔具 - 高端", "FL001", "渔具 - 高端"),
        # 只有 code 没 description
        ("FL017-11", "FL017-11", ""),
        # 只有 description 没 code（罕见，比如 ERP 没分类的）
        ("未分类", "", "未分类"),
    ],
)
def test_parse_erp_category(raw: str, expected_code: str, expected_desc: str) -> None:
    code, desc = parse_erp_category(raw)
    assert code == expected_code
    assert desc == expected_desc


def test_parse_erp_category_empty() -> None:
    assert parse_erp_category("") == ("", "")


def test_parse_erp_category_none() -> None:
    assert parse_erp_category(None) == ("", "")


def test_parse_erp_category_strips_whitespace() -> None:
    code, desc = parse_erp_category("  FL004 - 渔具系列  ")
    assert code == "FL004"
    assert desc == "渔具系列"
