"""按客户名包含的字符判断客户类型。

批发场景下中国客户和老外客户的购买模式差异巨大（中国大批量低频 vs 老外小批量
高频），分类是后续分析的基础。识别规则 (2026-05-23 更新):

- 包含任何中文字符 → chinese (中国人, 即使夹了拼音 / 希腊店名后缀也算)
- 仅非中文字母 (希腊/拉丁/西里尔等任意非汉字字母) → foreign (老外)
- 都没有 (纯数字/符号/空) → unknown

用户决策: "所有名字带中文的客户都算做 cn". 之前 mixed 拆出来留给人工分类,
但实际上"带中文 = CN 老板/CN 中介"100% 满足业务直觉, 不需要中间档.
"""

# CJK 统一汉字（中日韩共用区段，但中国客户名在批发场景里几乎都落这里）
_CJK_START = 0x4E00
_CJK_END = 0x9FFF


def _is_chinese_char(c: str) -> bool:
    return _CJK_START <= ord(c) <= _CJK_END


def has_chinese_chars(name: str | None) -> bool:
    """工具函数: 名字含任何汉字即返 True. 用于运行时强制覆盖 stored type."""
    if not name:
        return False
    return any(_is_chinese_char(c) for c in name)


def classify_customer(name: str | None) -> str:
    """返回 chinese / foreign / unknown 之一 (2026-05-23: 不再返 mixed)."""
    if not name:
        return "unknown"
    if has_chinese_chars(name):
        return "chinese"
    has_foreign_alpha = any(c.isalpha() and not _is_chinese_char(c) for c in name)
    if has_foreign_alpha:
        return "foreign"
    return "unknown"
