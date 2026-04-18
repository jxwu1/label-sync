import io
from dataclasses import dataclass

import openpyxl
import pandas as pd


def _decimal_places(value) -> int:
    s = str(float(value))
    if '.' in s:
        return len(s.split('.')[1].rstrip('0'))
    return 0


@dataclass
class PurchaseRow:
    barcode: str
    price_raw: str
    price: float
    quantity: int
    price_flagged: bool

    def formatted(self) -> str:
        return f"{self.barcode},{self.price:.2f},,{self.quantity}"

    def to_dict(self) -> dict:
        return {
            "barcode": self.barcode,
            "price": self.price,
            "quantity": self.quantity,
            "price_flagged": self.price_flagged,
            "formatted": self.formatted(),
        }


def parse_purchase_excel(file_bytes: bytes) -> list[PurchaseRow]:
    df = pd.read_excel(io.BytesIO(file_bytes), header=0)
    rows = []
    for _, row in df.iterrows():
        barcode = str(row.iloc[0]).strip()
        price_val = row.iloc[2]
        qty_val = row.iloc[5]
        try:
            price = float(price_val)
            price_flagged = _decimal_places(price) > 2
        except (ValueError, TypeError):
            price = 0.0
            price_flagged = True
        try:
            quantity = int(qty_val)
        except (ValueError, TypeError):
            quantity = 0
        rows.append(PurchaseRow(
            barcode=barcode,
            price_raw=str(price_val),
            price=price,
            quantity=quantity,
            price_flagged=price_flagged,
        ))
    return rows


def build_output_excel(file_bytes: bytes, rows_data: list[dict]) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
    ws = wb.active
    col = ws.max_column + 1
    ws.cell(row=1, column=col, value="导入信息")
    for i, row in enumerate(rows_data):
        ws.cell(row=i + 2, column=col, value=row["formatted"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
