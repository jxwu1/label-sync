"""HTML 伪装 .xls 解析器测试。"""

from pathlib import Path

import pytest

from xls_html_parser import XlsHtmlParseError, parse_xls_html

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_purchase_sample() -> None:
    df = parse_xls_html(_FIXTURES / "purchase_sample.xls")
    assert df.shape == (2, 25)
    # 列名稳定（这是后续 import 列映射的前提）
    assert list(df.columns)[:6] == ["单号", "查看", "ID号", "名称", "联系方法", "地址"]
    assert "条形码" in df.columns
    assert "产品种类" in df.columns


def test_parse_sales_sample() -> None:
    df = parse_xls_html(_FIXTURES / "sales_sample.xls")
    assert df.shape == (3, 25)
    # 客户名混合中文和希腊语
    names = df["名称"].dropna().tolist()
    assert "ΚΙΡΚΙΝΕΖΗΣ ΗΡΑΚΛΗΣ" in names
    assert "张三批发商" in names


def test_parse_missing_file() -> None:
    with pytest.raises(XlsHtmlParseError, match="不存在"):
        parse_xls_html(_FIXTURES / "does_not_exist.xls")


def test_parse_no_table(tmp_path: Path) -> None:
    bad = tmp_path / "no_table.xls"
    bad.write_text("<html><body>nothing here</body></html>", encoding="utf-8")
    with pytest.raises(XlsHtmlParseError):
        parse_xls_html(bad)


def test_parse_returns_first_table_when_multiple(tmp_path: Path) -> None:
    # 多 table 时取第一张（ERP 实际只导一张，但鲁棒性测试）
    multi = tmp_path / "multi.xls"
    multi.write_text(
        "<html><body>"
        "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>"
        "<table><thead><tr><th>B</th></tr></thead><tbody><tr><td>2</td></tr></tbody></table>"
        "</body></html>",
        encoding="utf-8",
    )
    df = parse_xls_html(multi)
    assert list(df.columns) == ["A"]
