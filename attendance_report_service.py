"""考勤报表：PDF（详情 + 工资单总览）。"""

import io
from pathlib import Path

import attendance_service
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_NAME = "AttnSC"
_FONT_REGISTERED = False
_FONT_CANDIDATES = [
    Path(__file__).resolve().parent / "static" / "fonts" / "NotoSansSC-Regular.ttf",
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
]

_PDF_TABLE_HEADER = ["日期", "星期", "上班", "下班", "天数", "请假", "状态"]
_OVERVIEW_HEADER = ["员工", "本月天数", "总工作日", "缺勤天数", "请假天数", "累计天数"]
_STATUS_CN = {
    "normal": "正常", "absent": "缺勤", "sunday": "周日",
    "holiday": "节假日", "special": "特殊日", "special_absent": "特殊日缺勤",
    "leave": "请假",
}

# 状态符号 + 文字 + 配色（极简风 PDF 用）
_STATUS_DISPLAY = {
    "normal":         ("● 正常",      "#059669"),
    "absent":         ("✕ 缺勤",      "#b91c1c"),
    "sunday":         ("○ 周日",      "#6b7280"),
    "holiday":        ("△ 节假日",    "#6b7280"),
    "special":        ("◐ 特殊日",    "#6d28d9"),
    "special_absent": ("✕ 特殊日缺勤", "#b91c1c"),
    "leave":          ("◐ 请假",      "#b45309"),
}

# 通用极简风颜色
_C_TITLE   = colors.HexColor("#111827")
_C_META    = colors.HexColor("#9ca3af")
_C_HEAD    = colors.HexColor("#1f2937")
_C_LINE    = colors.HexColor("#e5e7eb")


def _employee_anchor(emp_id: str) -> str:
    return f"emp_{emp_id}"


def _format_leave_pdf(row: dict) -> str:
    hours = row.get("leave_hours", 0) or 0
    ltype = row.get("leave_type", "")
    start = row.get("leave_start", "")
    end = row.get("leave_end", "")
    if ltype == "range" and start and end:
        return f"{start}-{end}\n{hours:.2f}h"
    if ltype == "left" and start:
        return f"{start}起\n{hours:.2f}h"
    return f"{hours:.2f}h"


def _build_overview(month: str, employees: list, summaries: dict, font_name: str) -> list:
    name_style = getSampleStyleSheet()["Normal"].clone("attn_name_link")
    name_style.fontName = font_name
    name_style.fontSize = 10
    elements = [
        _make_title_paragraph(f"{month} 月度考勤总览", font_name),
        _make_meta_paragraph(f"共 {len(employees)} 名员工", font_name),
    ]
    rows = [_OVERVIEW_HEADER]
    for idx, emp in enumerate(employees, start=1):
        s = summaries[emp["id"]]
        name_link = (
            f'<link href="#{_employee_anchor(emp["id"])}" color="#4f46e5">'
            f'<u>{idx}. {emp["name"]}</u></link>'
        )
        rows.append([
            Paragraph(name_link, name_style),
            f"{s['month_days']}",
            f"{s['total_workdays']}",
            f"{s['absent_days']}",
            f"{s.get('leave_days_equivalent', 0):.1f}",
            f"{s['worked_days']}",
        ])
    table = Table(rows, colWidths=[40 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm])
    style = _minimal_table_style(font_name, header_row=0, font_size=10)
    style.add("ALIGN", (1, 0), (-1, -1), "RIGHT")
    style.add("ALIGN", (0, 0), (0, 0), "LEFT")
    table.setStyle(style)
    elements.append(table)
    return elements


def _make_title_paragraph(text: str, font_name: str):
    """大标题：左对齐、加粗、深黑。"""
    from reportlab.lib.enums import TA_LEFT
    styles = getSampleStyleSheet()
    s = styles["Title"].clone("attn_title_minimal")
    s.fontName = font_name
    s.fontSize = 16
    s.leading = 20
    s.alignment = TA_LEFT
    s.textColor = _C_TITLE
    s.spaceAfter = 2
    return Paragraph(text, s)


def _make_meta_paragraph(text: str, font_name: str):
    """副标题/meta：左对齐、灰色小字。"""
    from reportlab.lib.enums import TA_LEFT
    styles = getSampleStyleSheet()
    s = styles["Normal"].clone("attn_meta_minimal")
    s.fontName = font_name
    s.fontSize = 9
    s.alignment = TA_LEFT
    s.textColor = _C_META
    s.spaceAfter = 12
    return Paragraph(text, s)


def _make_status_cell(status: str, font_name: str):
    """状态单元格：彩色符号+文字 Paragraph。未知状态用默认中灰。"""
    label, color = _STATUS_DISPLAY.get(status, (_STATUS_CN.get(status, status), "#6b7280"))
    styles = getSampleStyleSheet()
    s = styles["Normal"].clone("attn_status_cell")
    s.fontName = font_name
    s.fontSize = 9
    s.textColor = colors.HexColor(color)
    s.alignment = 1  # TA_CENTER
    return Paragraph(label, s)


def _minimal_table_style(font_name: str, header_row: int = 0, font_size: int = 9):
    """极简风通用 TableStyle：无网格，thead 1.5pt 底线，行间 0.3pt 浅灰线。"""
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("FONTSIZE", (0, header_row), (-1, header_row), font_size + 1),
        ("FONTNAME", (0, header_row), (-1, header_row), font_name),
        ("TEXTCOLOR", (0, header_row), (-1, header_row), _C_HEAD),
        ("LINEBELOW", (0, header_row), (-1, header_row), 1.5, _C_HEAD),
        ("LINEBELOW", (0, header_row + 1), (-1, -1), 0.3, _C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ])


def _register_font() -> None:
    global _FONT_REGISTERED, _FONT_NAME
    if _FONT_REGISTERED:
        return
    for fp in _FONT_CANDIDATES:
        if fp.exists():
            try:
                pdfmetrics.registerFont(TTFont(_FONT_NAME, str(fp)))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue
    _FONT_NAME = "Helvetica"
    _FONT_REGISTERED = True


def _build_employee_block(emp: dict, summary: dict) -> list:
    anchor_para = Paragraph(f'<a name="{_employee_anchor(emp["id"])}"/>', getSampleStyleSheet()["Normal"])
    title = _make_title_paragraph(emp["name"], _FONT_NAME)
    meta_text = (
        f'累计 {summary["worked_days"]} 天 · '
        f'缺勤 {summary["absent_days"]} 天 · '
        f'请假 {summary.get("leave_hours_total", 0)}h'
    )
    meta = _make_meta_paragraph(meta_text, _FONT_NAME)

    rows = [_PDF_TABLE_HEADER]
    for r in summary["detail"]:
        leave_h = r.get("leave_hours", 0) or 0
        rows.append([
            r["date"],
            r["weekday"],
            r["start"] or "—",
            r["end"] or "—",
            f"{r['day_fraction']:.2f}",
            _format_leave_pdf(r) if leave_h else "—",
            _make_status_cell(r["status"], _FONT_NAME),
        ])
    table = Table(rows, colWidths=[26 * mm, 12 * mm, 18 * mm, 18 * mm, 14 * mm, 22 * mm, 26 * mm])
    style = _minimal_table_style(_FONT_NAME, header_row=0, font_size=9)
    # 列对齐：date/weekday/start/end 居中；天数 右；请假 左；状态 中
    style.add("ALIGN", (0, 0), (3, -1), "CENTER")
    style.add("ALIGN", (4, 0), (4, -1), "RIGHT")
    style.add("ALIGN", (5, 0), (5, -1), "LEFT")
    style.add("ALIGN", (6, 0), (6, -1), "CENTER")
    table.setStyle(style)
    return [anchor_para, title, meta, table, Spacer(1, 10 * mm)]


_PAYROLL_HEADER = ["员工", "本月天数", "总工作日", "缺勤天数", "请假", "累计天数", "实际工资", "应付工资"]


def build_payroll_pdf(month: str) -> bytes:
    """工资单 PDF：仅总览页，横版 A4，含两列空白工资栏供手填。"""
    _register_font()
    employees = attendance_service.list_employees()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        topMargin=14 * mm, bottomMargin=14 * mm,
        leftMargin=14 * mm, rightMargin=14 * mm,
    )

    elements = [
        _make_title_paragraph(f"{month} 月度工资单", _FONT_NAME),
        _make_meta_paragraph(f"共 {len(employees)} 名员工 · 实际/应付工资请手填", _FONT_NAME),
    ]

    if not employees:
        empty = getSampleStyleSheet()["Normal"].clone("payroll_empty")
        empty.fontName = _FONT_NAME
        elements.append(Paragraph("暂无员工", empty))
        doc.build(elements)
        return buf.getvalue()

    name_style = getSampleStyleSheet()["Normal"].clone("payroll_name")
    name_style.fontName = _FONT_NAME
    name_style.fontSize = 10

    rows = [_PAYROLL_HEADER]
    for idx, emp in enumerate(employees, start=1):
        s = attendance_service.compute_summary(emp["id"], month)
        leave_h = s.get("leave_hours_total", 0)
        leave_d = s.get("leave_days_equivalent", 0)
        leave_text = f"{leave_h:.2f}h (≈{leave_d:.2f}d)" if leave_h else "—"
        rows.append([
            Paragraph(f"{idx}. {emp['name']}", name_style),
            f"{s['month_days']}",
            f"{s['total_workdays']}",
            f"{s['absent_days']}",
            leave_text,
            f"{s['worked_days']}",
            "",  # 实际工资（横线由 TableStyle 画）
            "",  # 应付工资
        ])

    col_widths = [40 * mm, 22 * mm, 24 * mm, 22 * mm, 30 * mm, 22 * mm, 50 * mm, 50 * mm]
    table = Table(rows, colWidths=col_widths)
    style = _minimal_table_style(_FONT_NAME, header_row=0, font_size=10)
    # 列对齐：员工 左；数字列 右；请假 中；工资栏 中
    style.add("ALIGN", (1, 0), (5, -1), "RIGHT")
    style.add("ALIGN", (4, 0), (4, -1), "CENTER")
    style.add("ALIGN", (6, 0), (-1, -1), "CENTER")
    # 工资块视觉分隔：累计列与实际工资列之间一条粗一点的线，实际工资与应付工资之间一条细线
    style.add("LINEBEFORE", (6, 0), (6, -1), 1.0, _C_HEAD)
    style.add("LINEBEFORE", (7, 0), (7, -1), 0.5, _C_HEAD)
    # 工资栏（最后两列）的数据行加 0.5pt 横线占位
    for row_idx in range(1, len(rows)):
        style.add("LINEBELOW", (6, row_idx), (-1, row_idx), 0.5, _C_HEAD)
    table.setStyle(style)
    elements.append(table)

    doc.build(elements)
    return buf.getvalue()


def build_pdf(month: str) -> bytes:
    _register_font()
    employees = attendance_service.list_employees()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    elements = []

    styles = getSampleStyleSheet()

    if not employees:
        title_style = styles["Title"].clone("attn_title")
        title_style.fontName = _FONT_NAME
        elements.append(Paragraph(f"{month} 月度考勤报表", title_style))
        elements.append(Spacer(1, 8 * mm))
        normal = styles["Normal"].clone("attn_empty")
        normal.fontName = _FONT_NAME
        elements.append(Paragraph("暂无员工", normal))
    else:
        summaries = {
            emp["id"]: attendance_service.compute_summary(emp["id"], month)
            for emp in employees
        }
        elements.extend(_build_overview(month, employees, summaries, _FONT_NAME))
        elements.append(PageBreak())
        for emp in employees:
            elements.append(KeepTogether(_build_employee_block(emp, summaries[emp["id"]])))

    doc.build(elements)
    return buf.getvalue()
