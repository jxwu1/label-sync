"""老外客人月度记录 PDF 报表生成。

复用 attendance_report_service 的字体注册、标题/meta、表格样式 helpers。
A4 portrait + 6 列：客户名 / 欠款 / 税号 / 付款日期 / 托运日期 / 备注。
"""

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

import foreign_customer_service
from attendance_report_service import (
    _make_meta_paragraph,
    _make_title_paragraph,
    _minimal_table_style,
    _register_font,
)

_FONT_NAME = "AttnSC"  # 与 attendance 共用
_TABLE_HEADER = ["客户名", "欠款 (€)", "税号", "付款日期", "托运日期", "备注"]


def _name_cell(name: str, ctype: str) -> Paragraph:
    """客户名 + 类型 badge 文字。"""
    type_label = {
        "foreign": "老外",
        "chinese": "中国",
        "mixed": "混合",
        "unknown": "未归类",
    }.get(ctype, "")
    styles = getSampleStyleSheet()
    s = styles["Normal"].clone("fc_name_cell")
    s.fontName = _FONT_NAME
    s.fontSize = 10
    s.alignment = TA_LEFT
    text = f"{name}<br/><font size=8 color='#9ca3af'>[{type_label}]</font>"
    return Paragraph(text, s)


def _wrap_paragraph(text: str, font_size: int = 9) -> Paragraph:
    """把长文本（备注）包成 Paragraph 让它能换行。"""
    styles = getSampleStyleSheet()
    s = styles["Normal"].clone(f"fc_para_{font_size}")
    s.fontName = _FONT_NAME
    s.fontSize = font_size
    s.leading = font_size + 2
    s.alignment = TA_LEFT
    return Paragraph(text or "", s)


def _fmt_money(amt: float | None) -> str:
    if amt is None:
        return "—"
    return f"{amt:,.2f}"


def _fmt_date(d: str | None) -> str:
    return d if d else "—"


def build_pdf(month: str) -> bytes:
    """生成指定月份的老外客人月度记录 PDF。"""
    _register_font()
    records = foreign_customer_service.list_records(month=month)
    summary = foreign_customer_service.month_summary(month)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
    )

    money = _fmt_money(summary["total_amount_due"])
    cnt = summary["record_count"]
    paid = summary["paid_count"]
    unpaid = summary["unpaid_count"]
    shipped = summary["shipped_count"]
    meta_text = (
        f"共 {cnt} 条记录 · 总欠款 €{money} · 已付 {paid} · 未付 {unpaid} · 已托运 {shipped}"
    )
    elements = [
        _make_title_paragraph(f"{month} 老外客人月度记录", _FONT_NAME),
        _make_meta_paragraph(meta_text, _FONT_NAME),
    ]

    if not records:
        empty = getSampleStyleSheet()["Normal"].clone("fc_empty")
        empty.fontName = _FONT_NAME
        elements.append(Paragraph("本月暂无记录", empty))
        doc.build(elements)
        return buf.getvalue()

    rows = [_TABLE_HEADER]
    for r in records:
        rows.append(
            [
                _name_cell(r["customer_name"], ""),  # type 字段不在 list_records 返回里，留空
                _fmt_money(r.get("amount_due")),
                r.get("tax_number") or "—",
                _fmt_date(r.get("payment_date")),
                _fmt_date(r.get("shipping_date")),
                _wrap_paragraph(r.get("notes") or "—"),
            ]
        )

    col_widths = [40 * mm, 22 * mm, 28 * mm, 24 * mm, 24 * mm, 44 * mm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    style = _minimal_table_style(_FONT_NAME, header_row=0, font_size=9)
    # 数字列右对齐
    style.add("ALIGN", (1, 1), (1, -1), "RIGHT")
    # 日期居中
    style.add("ALIGN", (3, 1), (4, -1), "CENTER")
    # 行 padding 收紧
    style.add("TOPPADDING", (0, 1), (-1, -1), 4)
    style.add("BOTTOMPADDING", (0, 1), (-1, -1), 4)
    # 未付行（无 payment_date）淡红背景
    for i, r in enumerate(records, start=1):
        if not r.get("payment_date"):
            style.add(
                "BACKGROUND",
                (0, i),
                (-1, i),
                colors.HexColor("#fef2f2"),
            )
    table.setStyle(style)
    elements.append(table)
    elements.append(Spacer(1, 8 * mm))

    doc.build(elements)
    return buf.getvalue()
