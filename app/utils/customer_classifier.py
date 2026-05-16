"""按客户名包含的字符判断客户类型。

批发场景下中国客户和老外客户的购买模式差异巨大（中国大批量低频 vs 老外小批量
高频），分类是后续分析的基础。识别规则：

- 中文字符 + 非中文字母（希腊/拉丁/...）都在 → mixed（待人工归类）
- 仅中文字符 → chinese（中国人）
- 仅非中文字母（希腊/拉丁/西里尔等任意非汉字字母） → foreign（老外）
- 都没有（纯数字/符号/空） → unknown

「非中文字母」一刀切的好处：希腊本地客户、英文名外国客户、罕见欧洲口音字母
名字（François）、俄罗斯人 (Иван) 等全归 foreign 一档——对销售分析用户而言
都是"非中国客"这一组群，不必再细分。

阶段 4 v1：mixed / unknown 留给 customers 表手工 update，本函数只做机器可判
的部分。
"""

# CJK 统一汉字（中日韩共用区段，但中国客户名在批发场景里几乎都落这里）
_CJK_START = 0x4E00
_CJK_END = 0x9FFF


def _is_chinese_char(c: str) -> bool:
    return _CJK_START <= ord(c) <= _CJK_END


def classify_customer(name: str | None) -> str:
    """返回 foreign / chinese / mixed / unknown 之一。"""
    if not name:
        return "unknown"
    has_chinese = any(_is_chinese_char(c) for c in name)
    # 任何字母字符（str.isalpha 涵盖各文字系统），但排除汉字
    has_foreign_alpha = any(c.isalpha() and not _is_chinese_char(c) for c in name)
    if has_chinese and has_foreign_alpha:
        return "mixed"
    if has_chinese:
        return "chinese"
    if has_foreign_alpha:
        return "foreign"
    return "unknown"
