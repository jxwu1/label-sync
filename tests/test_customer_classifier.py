"""客户类型识别 (2026-05-23 简化): 任何中文字符 → chinese, 否则 foreign / unknown.
mixed 档已合并入 chinese (用户决策: "所有名字带中文的客户都算做 cn")."""

import pytest

from app.utils.customer_classifier import classify_customer, has_chinese_chars


@pytest.mark.parametrize(
    "name,expected",
    [
        # 希腊语 → foreign
        ("ΚΙΡΚΙΝΕΖΗΣ ΗΡΑΚΛΗΣ", "foreign"),
        ("ΑΝΔΡΕΟΥ", "foreign"),
        ("ΚΙΡΚΙΝΕΖΗΣ 12345", "foreign"),
        ("Α/Φ ΑΝΔΡΕΟΥ", "foreign"),
        # 英文名 / 拉丁字母 → foreign
        ("JOHN SMITH", "foreign"),
        ("HOMEPLAST", "foreign"),
        ("HOMEPLAST 6972888853", "foreign"),
        ("François", "foreign"),
        # 含中文 → chinese (含夹杂希腊/拉丁字母也一律 CN)
        ("张三", "chinese"),
        ("李四批发", "chinese"),
        ("张三 6972888833", "chinese"),
        ("张三 ΑΘΗΝΑ", "chinese"),
        ("中国 ΑΝΔΡΕΟΥ 客", "chinese"),
        ("HOMEPLAST 6972888853 (希腊塑料供应商)", "chinese"),
        ("John 张三", "chinese"),
        # 纯数字 / 空 / 符号 → unknown
        ("156188672", "unknown"),
        ("", "unknown"),
        ("   ", "unknown"),
        ("---", "unknown"),
    ],
)
def test_classify_customer(name: str, expected: str) -> None:
    assert classify_customer(name) == expected


def test_has_chinese_chars_helper() -> None:
    assert has_chinese_chars("张三") is True
    assert has_chinese_chars("John 张三") is True
    assert has_chinese_chars("HOMEPLAST") is False
    assert has_chinese_chars("") is False
    assert has_chinese_chars(None) is False


def test_classify_customer_none() -> None:
    assert classify_customer(None) == "unknown"
