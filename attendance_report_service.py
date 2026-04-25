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
_OVERVIEW_HEADER = ["员工", "累计天数", "缺勤天数", "总工作日", "本月天数", "请假天数"]
_STATUS_CN = {
    "normal": "正常", "absent": "缺勤", "sunday": "周日",
    "holiday": "节假日", "special": "特殊日", "special_absent": "特殊日缺勤",
    "leave": "请假",
}


def _employee_anchor(emp_id: str) -> str:
    return f"emp_{emp_id}"


def _format_leave_pdf(row: dict) -> str:
    h = row.get("leave_hours", 0) or 0
    t = row.get("leave_type", "")
    s = row.get("leave_start", "")
    e = row.get("leave_end", "")
    if t == "range" and s and e:
        return f"{s}-{e}\n{h:.2f}h"
    if t == "left" and s:
        return f"{s}起\n{h:.2f}h"
    return f"{h:.2f}h"


def _build_overview(month: str, employees: list, summaries: dict, font_name: str) -> list:
    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("attn_overview_title")
    title_style.fontName = font_name
    name_style = styles["Normal"].clone("attn_name_link")
    name_style.fontName = font_name
    name_style.fontSize = 10
    elements = [
        Paragraph(f"{month} 月度考勤总览", title_style),
        Spacer(1, 6 * mm),
    ]
    rows = [_OVERVIEW_HEADER]
    for emp in employees:
        s = summaries[emp["id"]]
        name_link = (
            f'<link href="#{_employee_anchor(emp["id"])}" color="blue">'
            f'<u>{emp["name"]}</u></link>'
        )
        rows.append([
            Paragraph(name_link, name_style),
            f"{s['worked_days']}",
            f"{s['absent_days']}",
            f"{s['total_workdays']}",
            f"{s['month_days']}",
            f"{s.get('leave_days_equivalent', 0):.1f}",
        ])
    table = Table(rows, colWidths=[36 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
    ]))
    elements.append(table)
    return elements


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
    styles = getSampleStyleSheet()
    title = styles["Heading2"].clone("attn_h2")
    title.fontName = _FONT_NAME
    normal = styles["Normal"].clone("attn_n")
    normal.fontName = _FONT_NAME

    header = Paragraph(
        f'<a name="{_employee_anchor(emp["id"])}"/>{emp["name"]} — 累计 {summary["worked_days"]} 天 / 缺勤 {summary["absent_days"]} 天 / 总工作日 {summary["total_workdays"]} / 请假 {summary.get("leave_hours_total", 0)} 小时',
        title,
    )
    rows = [_PDF_TABLE_HEADER]
    for r in summary["detail"]:
        leave_h = r.get("leave_hours", 0) or 0
        rows.append([
            r["date"], r["weekday"], r["start"] or "—", r["end"] or "—",
            f"{r['day_fraction']:.2f}",
            _format_leave_pdf(r) if leave_h else "—",
            _STATUS_CN.get(r["status"], r["status"]),
        ])
    table = Table(rows, colWidths=[26 * mm, 12 * mm, 18 * mm, 18 * mm, 14 * mm, 14 * mm, 18 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
    ]))
    return [header, Spacer(1, 4 * mm), table, Spacer(1, 10 * mm)]


_PAYROLL_HEADER = ["员工", "累计天数", "缺勤天数", "总工作日", "本月天数", "请假", "实际工资", "应付工资"]


def build_payroll_pdf(month: str) -> bytes:
    """工资单 PDF：仅总览页，横版 A4，含两列空白工资栏供手填。"""
    _register_font()
    employees = attendance_service.list_employees()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        topMargin=10 * mm, bottomMargin=10 * mm,
        leftMargin=12 * mm, rightMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("payroll_title")
    title_style.fontName = _FONT_NAME
    title_style.fontSize = 16
    title_style.spaceAfter = 4
    name_style = styles["Normal"].clone("payroll_name")
    name_style.fontName = _FONT_NAME
    name_style.fontSize = 10

    elements = [
        Paragraph(f"{month} 月度工资单", title_style),
        Spacer(1, 3 * mm),
    ]

    if not employees:
        empty = styles["Normal"].clone("payroll_empty")
        empty.fontName = _FONT_NAME
        elements.append(Paragraph("暂无员工", empty))
    else:
        rows = [_PAYROLL_HEADER]
        for emp in employees:
            s = attendance_service.compute_summary(emp["id"], month)
            leave_h = s.get("leave_hours_total", 0)
            leave_d = s.get("leave_days_equivalent", 0)
            leave_text = f"{leave_h} 小时\n(约 {leave_d:.2f} 天)" if leave_h else "—"
            rows.append([
                Paragraph(emp["name"], name_style),
                f"{s['worked_days']}",
                f"{s['absent_days']}",
                f"{s['total_workdays']}",
                f"{s['month_days']}",
                leave_text,
                "",
                "",
            ])
        # 横版 A4 可用宽 ~273mm
        col_widths = [38 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 35 * mm, 35 * mm]
        table = Table(rows, colWidths=col_widths)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.97, 0.97, 0.97)]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
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
