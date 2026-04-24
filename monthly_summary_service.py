import io
import json
from datetime import date, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_SUMMARY_DIR = Path(__file__).resolve().parent / "monthly_summary"

_MONTHS_TO_KEEP = 6


def _month_file(month: str) -> Path:
    return _SUMMARY_DIR / f"{month}.json"


def _read_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_record(
    supplier_name: str,
    total_price: float,
    tax: float,
    invoice_date: str,
    month: str,
) -> dict:
    record = {
        "supplier_name": supplier_name,
        "total_price": total_price,
        "tax": tax,
        "total_with_tax": total_price + tax,
        "invoice_date": invoice_date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = _month_file(month)
    records = _read_json(path)
    records.append(record)
    _write_json(path, records)
    return record


def load_records(month: str) -> list[dict]:
    return _read_json(_month_file(month))


def delete_record(month: str, index: int) -> dict:
    path = _month_file(month)
    records = _read_json(path)
    if index < 0 or index >= len(records):
        raise IndexError(f"记录索引越界：month={month} index={index} total={len(records)}")
    removed = records.pop(index)
    if records:
        _write_json(path, records)
    elif path.exists():
        path.unlink()
    return removed


def list_months() -> list[str]:
    if not _SUMMARY_DIR.exists():
        return []
    months = [
        f.stem for f in _SUMMARY_DIR.glob("*.json")
        if f.stem[:4].isdigit()
    ]
    months.sort(reverse=True)
    return months


def cleanup_expired(reference_date: date | None = None) -> None:
    ref = reference_date or date.today()
    cutoff_year = ref.year
    cutoff_month = ref.month - _MONTHS_TO_KEEP
    if cutoff_month <= 0:
        cutoff_year -= 1
        cutoff_month += 12
    cutoff = f"{cutoff_year:04d}-{cutoff_month:02d}"
    if not _SUMMARY_DIR.exists():
        return
    for f in _SUMMARY_DIR.glob("*.json"):
        if f.stem < cutoff:
            f.unlink()


_FONT_NAME = "NotoSansSC"
_FONT_REGISTERED = False

_FONT_CANDIDATES = [
    Path(__file__).resolve().parent / "static" / "fonts" / "NotoSansSC-Regular.ttf",
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
]


def _register_font() -> None:
    global _FONT_REGISTERED, _FONT_NAME
    if _FONT_REGISTERED:
        return
    for font_path in _FONT_CANDIDATES:
        if font_path.exists():
            try:
                pdfmetrics.registerFont(TTFont(_FONT_NAME, str(font_path)))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue
    _FONT_NAME = "Helvetica"
    _FONT_REGISTERED = True


def _format_euro(amount: float) -> str:
    return f"€{amount:,.2f}"


def _build_record_table(rec: dict, font_name: str) -> Table:
    data = [
        ["供应商", rec["supplier_name"]],
        ["开票日期", rec["invoice_date"]],
        ["总价", _format_euro(rec["total_price"])],
        ["税金", _format_euro(rec["tax"])],
        ["加税总价", _format_euro(rec["total_with_tax"])],
    ]
    table = Table(data, colWidths=[40 * mm, 80 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_pdf(month: str) -> bytes:
    """Generate a PDF report for the given month and return its bytes."""
    _register_font()
    records = load_records(month)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("title_cn")
    title_style.fontName = _FONT_NAME
    title_style.fontSize = 16

    elements.append(Paragraph(f"{month} 月度采购财务总结", title_style))
    elements.append(Spacer(1, 10 * mm))

    if not records:
        no_data_style = styles["Normal"].clone("nodata_cn")
        no_data_style.fontName = _FONT_NAME
        elements.append(Paragraph("本月暂无记录", no_data_style))
    else:
        for rec in records:
            elements.append(KeepTogether([
                _build_record_table(rec, _FONT_NAME),
                Spacer(1, 8 * mm),
            ]))

    doc.build(elements)
    return buf.getvalue()
