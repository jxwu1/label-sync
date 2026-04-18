import io
import json
import re
from dataclasses import dataclass, field

import openpyxl


@dataclass
class ImportItem:
    barcode: str | None
    quantity: int | None
    total_price: float | None
    unit_price: float | None = field(init=False)
    flagged: bool = field(init=False)
    barcode_suspect: bool = field(init=False)

    def __post_init__(self):
        if self.quantity and self.total_price is not None:
            self.unit_price = round(self.total_price / self.quantity, 4)
        else:
            self.unit_price = None
        self.flagged = self.barcode is None or self.quantity is None or self.total_price is None
        self.barcode_suspect = (
            self.barcode is not None and not re.fullmatch(r"\d{8}|\d{13}", self.barcode)
        )

    def to_dict(self) -> dict:
        return {
            "barcode": self.barcode,
            "quantity": self.quantity,
            "total_price": self.total_price,
            "unit_price": self.unit_price,
            "flagged": self.flagged,
            "barcode_suspect": self.barcode_suspect,
        }


def parse_gemini_response(raw: str) -> list[ImportItem]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = []
    for row in data:
        barcode = row.get("barcode")
        quantity = row.get("quantity")
        total_price = row.get("total_price")
        items.append(ImportItem(
            barcode=str(barcode) if barcode is not None else None,
            quantity=int(quantity) if quantity is not None else None,
            total_price=float(total_price) if total_price is not None else None,
        ))
    return items


def recognize_images(image_bytes_list: list[bytes], api_key: str) -> list[ImportItem]:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=(
            "You are a data extraction assistant. Given one or more supplier invoice images "
            "(possibly in Greek, English, or other languages), extract all line items. "
            "Return ONLY a JSON array with objects: "
            '{"barcode": "...", "quantity": N, "total_price": N.NN}. '
            "If a field is uncertain or missing, use null. Do not guess. No extra text."
        ),
    )
    parts = []
    for img_bytes in image_bytes_list:
        parts.append({"mime_type": "image/jpeg", "data": img_bytes})
    parts.append("Extract all line items from these invoice images.")
    response = model.generate_content(parts)
    return parse_gemini_response(response.text)


def build_excel_bytes(items: list[ImportItem]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Barcode", "数量", "单价(€)", "总价(€)"])
    for item in sorted(items, key=lambda x: x.barcode or ""):
        ws.append([item.barcode, item.quantity, item.unit_price, item.total_price])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
