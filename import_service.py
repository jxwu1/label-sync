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


_SYSTEM_INSTRUCTION = """You are extracting product line items from supplier invoice photos.
Invoices may be in Greek or English, printed or handwritten, in any table layout.

For EACH product/item line extract:
- barcode: the numeric product code, typically EAN-13 (13 digits) or EAN-8 (8 digits).
  It appears as a standalone number in a product-code column, or printed below a barcode symbol.
  Copy ALL digits exactly as they appear — do not guess, do not add or remove digits.
- quantity: integer number of units on this line.
- total_price: the line total in euros for this row (NOT the invoice grand total).

Rules:
- Extract EVERY product line — never skip any row.
- Use null ONLY when a value is completely absent or completely illegible.
- Exclude header rows, column labels, invoice totals, subtotals, VAT lines, and discount lines.
- If the same barcode appears on multiple lines (e.g. across pages), keep both rows.

Return ONLY a valid JSON array of objects with keys "barcode", "quantity", "total_price". No other text."""


def recognize_images(image_data_list: list[tuple[bytes, str]], api_key: str) -> list[ImportItem]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    parts: list[types.Part] = [
        types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
        for img_bytes, mime_type in image_data_list
    ]
    parts.append(types.Part.from_text(text="Extract all product line items from these invoice images."))
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
        ),
    )
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
