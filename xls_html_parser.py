"""ERP 导出文件解析。

源 ERP 导出的 .xls 实为 HTML 表格（旧 ERP 经典糊弄做法）。本模块只做最薄一层：
读 HTML → 返回 raw DataFrame，不做任何类型清洗或字段语义解析。

类型清洗（条码 float → str / 日期格式 / qty 转 int 等）由调用方根据列映射做。
"""

from pathlib import Path

import pandas as pd


class XlsHtmlParseError(Exception):
    """xls 解析失败。"""


def parse_xls_html(path: Path | str) -> pd.DataFrame:
    """读 ERP 导出的 HTML 伪装 .xls，返回第一张表的 raw DataFrame。

    抛 XlsHtmlParseError 如果：
    - 文件不存在
    - HTML 里没有 <table>
    - 解析出 0 张表

    pandas.read_html 自动识别 <meta charset>，常见 UTF-8 / GBK 都能跑。
    """
    p = Path(path)
    if not p.exists():
        raise XlsHtmlParseError(f"文件不存在：{p}")

    try:
        tables = pd.read_html(p)
    except Exception as exc:
        raise XlsHtmlParseError(f"HTML 解析失败：{exc}") from exc

    if not tables:
        raise XlsHtmlParseError("文件里没有 <table>")

    return tables[0]
