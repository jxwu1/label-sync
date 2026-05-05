"""按客户名包含的字符判断客户类型。

批发场景下中国客户和老外客户的购买模式差异巨大（中国大批量低频 vs 老外小批量
高频），分类是后续分析的基础。识别规则：

- 希腊字符在 → foreign（老外）
- 中文字符在 → chinese（中国人）
- 两者都在 → mixed（待人工归类，常见于供应商名带括号说明）
- 都不在 → unknown（纯 ASCII / 数字 / 空）

阶段 4 v1：人工归类 mixed / unknown 留给 customers 表手工 update，本函数只做
机器可判的部分。
"""

# Greek 基本字母块（含小写/大写）
_GREEK_RANGE = (0x0370, 0x03FF)

# CJK 统一汉字（中日韩共用区段，但中国客户名在 4 大主品类批发场景里几乎都落这里）
_CJK_RANGE = (0x4E00, 0x9FFF)


def _has_in_range(text: str, start: int, end: int) -> bool:
    return any(start <= ord(c) <= end for c in text)


def classify_customer(name: str | None) -> str:
    """返回 foreign / chinese / mixed / unknown 之一。"""
    if not name:
        return "unknown"
    has_greek = _has_in_range(name, *_GREEK_RANGE)
    has_chinese = _has_in_range(name, *_CJK_RANGE)
    if has_greek and has_chinese:
        return "mixed"
    if has_greek:
        return "foreign"
    if has_chinese:
        return "chinese"
    return "unknown"
