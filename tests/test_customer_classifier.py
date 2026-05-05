"""客户类型识别：非中文字母 = 老外（涵盖希腊/拉丁/...）/ 中文 = 中国人 /
混合 / 未知。"""

import pytest

from customer_classifier import classify_customer


@pytest.mark.parametrize(
    "name,expected",
    [
        # 希腊语 → foreign（老外，希腊本地客户）
        ("ΚΙΡΚΙΝΕΖΗΣ ΗΡΑΚΛΗΣ", "foreign"),
        ("ΑΝΔΡΕΟΥ", "foreign"),
        ("ΚΙΡΚΙΝΕΖΗΣ 12345", "foreign"),
        ("Α/Φ ΑΝΔΡΕΟΥ", "foreign"),
        # 英文名 / 拉丁字母 → foreign（老外，英文名外国客户）
        ("JOHN SMITH", "foreign"),
        ("HOMEPLAST", "foreign"),
        ("HOMEPLAST 6972888853", "foreign"),
        # 罕见欧洲口音字母 → foreign（依然算老外一组群）
        ("François", "foreign"),
        # 中文 → chinese（中国人）
        ("张三", "chinese"),
        ("李四批发", "chinese"),
        ("张三 6972888833", "chinese"),
        # 中文 + 任何非中文字母 → mixed
        ("张三 ΑΘΗΝΑ", "mixed"),
        ("中国 ΑΝΔΡΕΟΥ 客", "mixed"),
        ("HOMEPLAST 6972888853 (希腊塑料供应商)", "mixed"),
        ("John 张三", "mixed"),
        # 纯数字 / 空 / 符号 → unknown
        ("156188672", "unknown"),
        ("", "unknown"),
        ("   ", "unknown"),
        ("---", "unknown"),
    ],
)
def test_classify_customer(name: str, expected: str) -> None:
    assert classify_customer(name) == expected


def test_classify_customer_none() -> None:
    assert classify_customer(None) == "unknown"
