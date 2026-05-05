"""客户类型识别：希腊语字符 = 老外 / 中文字符 = 中国人 / 混合 / 未知。"""

import pytest

from customer_classifier import classify_customer


@pytest.mark.parametrize(
    "name,expected",
    [
        # 纯希腊语 → foreign（老外）
        ("ΚΙΡΚΙΝΕΖΗΣ ΗΡΑΚΛΗΣ", "foreign"),
        ("ΑΝΔΡΕΟΥ", "foreign"),
        # 希腊字母 + 数字 / ASCII 仍算 foreign
        ("ΚΙΡΚΙΝΕΖΗΣ 12345", "foreign"),
        ("Α/Φ ΑΝΔΡΕΟΥ", "foreign"),
        # 纯中文 → chinese（中国人）
        ("张三", "chinese"),
        ("李四批发", "chinese"),
        # 中文 + 数字 / ASCII 仍算 chinese
        ("张三 6972888833", "chinese"),
        # 混合中希 → mixed（待人工归类）
        ("张三 ΑΘΗΝΑ", "mixed"),
        ("中国 ΑΝΔΡΕΟΥ 客", "mixed"),
        # 纯 ASCII / 数字 / 空 → unknown
        ("JOHN SMITH", "unknown"),
        ("156188672", "unknown"),
        ("", "unknown"),
        ("   ", "unknown"),
    ],
)
def test_classify_customer(name: str, expected: str) -> None:
    assert classify_customer(name) == expected


def test_classify_customer_none() -> None:
    assert classify_customer(None) == "unknown"
