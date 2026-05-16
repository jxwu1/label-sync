"""ERP 产品种类字段解析。

源 ERP「产品种类」字段格式约定：`<code> - <description>`
例如：`FL017-11 - 塑料大盒子ΠΛΑΣΤΙΚΕΣ_ΚΟΥΤΙ_ΑΠΟΘΗΚΕΥΣΗΣ`

import 时同时存：
- erp_category_raw：原字符串，万一某天解析逻辑变了还能回追
- erp_category_code：拆出的码（如 FL017-11），分析时用

注意分割只在**第一个** " - "（前后必有空格）处切，避免误伤描述里出现的 dash。
判断"是不是 code"：开头连续的非空白 + 至少一段是字母数字。
"""

import re

# code 形如 FL017-11 / A001 / A002-021001 / FL098-04 —— 字母+数字+横线，不含空格
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9\-]+$")


def parse_erp_category(raw: str | None) -> tuple[str, str]:
    """返回 (code, description)，找不到 code 时第一项为空串。"""
    if not raw:
        return "", ""
    s = raw.strip()
    if not s:
        return "", ""

    # 第一个 " - " 切两段（前后必须有空格才是分隔符，避免误伤 code 内的 dash）
    parts = s.split(" - ", 1)
    if len(parts) == 2:
        candidate_code = parts[0].strip()
        description = parts[1].strip()
        if _CODE_PATTERN.match(candidate_code):
            return candidate_code, description
        # 第一段不像 code，整串当 description
        return "", s

    # 没分隔符：判断整串是否像 code
    if _CODE_PATTERN.match(s):
        return s, ""
    return "", s
