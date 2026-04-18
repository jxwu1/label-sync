import io
import unittest

import openpyxl

from purchase_service import PurchaseRow, parse_purchase_excel, build_output_excel


def _make_excel(data_rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["条码", "col2", "价格", "col4", "col5", "数量", "col7"])
    for row in data_rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestPurchaseRow(unittest.TestCase):
    def test_formatted_two_decimal(self):
        row = PurchaseRow(barcode="1234567890123", price_raw="9.48", price=9.48, quantity=144, price_flagged=False)
        self.assertEqual(row.formatted(), "1234567890123,9.48,,144")

    def test_formatted_pads_whole_number_to_two_decimal(self):
        row = PurchaseRow(barcode="1234567890123", price_raw="12", price=12.0, quantity=36, price_flagged=False)
        self.assertEqual(row.formatted(), "1234567890123,12.00,,36")

    def test_to_dict_has_expected_keys(self):
        row = PurchaseRow(barcode="1111", price_raw="5.0", price=5.0, quantity=10, price_flagged=False)
        d = row.to_dict()
        self.assertEqual(d["barcode"], "1111")
        self.assertAlmostEqual(d["price"], 5.0)
        self.assertEqual(d["quantity"], 10)
        self.assertFalse(d["price_flagged"])
        self.assertEqual(d["formatted"], "1111,5.00,,10")


class TestParsePurchaseExcel(unittest.TestCase):
    def test_parses_basic_row(self):
        data = _make_excel([["1234567890123", "x", 9.48, "x", "x", 144, "x"]])
        rows = parse_purchase_excel(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].barcode, "1234567890123")
        self.assertAlmostEqual(rows[0].price, 9.48)
        self.assertEqual(rows[0].quantity, 144)
        self.assertFalse(rows[0].price_flagged)

    def test_flags_price_with_more_than_two_decimals(self):
        data = _make_excel([["1234567890123", "x", 9.4812, "x", "x", 10, "x"]])
        rows = parse_purchase_excel(data)
        self.assertTrue(rows[0].price_flagged)

    def test_does_not_flag_trailing_zeros(self):
        data = _make_excel([["1234567890123", "x", 9.480, "x", "x", 10, "x"]])
        rows = parse_purchase_excel(data)
        self.assertFalse(rows[0].price_flagged)

    def test_parses_multiple_data_rows_skips_header(self):
        data = _make_excel([
            ["BC1", "x", 1.0, "x", "x", 5, "x"],
            ["BC2", "x", 2.0, "x", "x", 3, "x"],
        ])
        rows = parse_purchase_excel(data)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].barcode, "BC1")
        self.assertEqual(rows[1].barcode, "BC2")


class TestBuildOutputExcel(unittest.TestCase):
    def test_appends_header_and_data(self):
        file_bytes = _make_excel([["BC1", "x", 9.48, "x", "x", 10, "x"]])
        rows_data = [{"formatted": "BC1,9.48,,10"}]
        result = build_output_excel(file_bytes, rows_data)
        wb = openpyxl.load_workbook(io.BytesIO(result))
        ws = wb.active
        self.assertEqual(ws.cell(row=1, column=8).value, "导入信息")
        self.assertEqual(ws.cell(row=2, column=8).value, "BC1,9.48,,10")

    def test_original_data_preserved(self):
        file_bytes = _make_excel([["BC1", "x", 9.48, "x", "x", 10, "x"]])
        result = build_output_excel(file_bytes, [{"formatted": "BC1,9.48,,10"}])
        wb = openpyxl.load_workbook(io.BytesIO(result))
        ws = wb.active
        self.assertEqual(ws.cell(row=2, column=1).value, "BC1")
        self.assertAlmostEqual(ws.cell(row=2, column=3).value, 9.48)
