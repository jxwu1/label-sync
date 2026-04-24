"""考勤报表：PDF + CSV。"""

import csv
import io
from pathlib import Path

import attendance_service
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_CSV_HEADER = ["员工", "日期", "星期", "上班", "下班", "天数", "状态"]

_FONT_NAME = "AttnSC"
_FONT_REGISTERED = False
_FONT_CANDIDATES = [
    Path(__file__).resolve().parent / "static" / "fonts" / "NotoSansSC-Regular.ttf",
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
]

_PDF_TABLE_HEADER = ["日期", "星期", "上班", "下班", "天数", "状态"]
_OVERVIEW_HEADER = ["员工", "累计天数", "缺勤天数", "总工作日", "本月天数"]
_STATUS_CN = {
    "normal": "正常", "absent": "缺勤", "sunday": "周日",
    "holiday": "节假日", "special": "特殊日", "special_absent": "特殊日缺勤",
}


def _employee_anchor(emp_id: str) -> str:
    return f"emp_{emp_id}"


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
        ])
    table = Table(rows, colWidths=[40 * mm, 26 * mm, 26 * mm, 26 * mm, 26 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
    ]))
    elements.append(table)
    return elements


def build_csv(month: str) -> bytes:
    employees = attendance_service.list_employees()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_HEADER)
    for emp in employees:
        summary = attendance_service.compute_summary(emp["id"], month)
        for row in summary["detail"]:
            writer.writerow([
                emp["name"], row["date"], row["weekday"],
                row["start"], row["end"],
                row["day_fraction"], _STATUS_CN.get(row["status"], row["status"]),
            ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


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
        f'<a name="{_employee_anchor(emp["id"])}"/>{emp["name"]} — 累计 {summary["worked_days"]} 天 / 缺勤 {summary["absent_days"]} 天 / 总工作日 {summary["total_workdays"]}',
        title,
    )
    rows = [_PDF_TABLE_HEADER]
    for r in summary["detail"]:
        rows.append([
            r["date"], r["weekday"], r["start"] or "—", r["end"] or "—",
            f"{r['day_fraction']:.2f}", _STATUS_CN.get(r["status"], r["status"]),
        ])
    table = Table(rows, colWidths=[28 * mm, 14 * mm, 20 * mm, 20 * mm, 16 * mm, 20 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
    ]))
    return [header, Spacer(1, 4 * mm), table, Spacer(1, 10 * mm)]


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
