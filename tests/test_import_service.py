import unittest
from unittest.mock import MagicMock, patch

from import_service import ImportItem, parse_gemini_response, build_excel_bytes


class TestImportItem(unittest.TestCase):
    def test_unit_price_computed_when_both_present(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=250.0)
        self.assertAlmostEqual(item.unit_price, 25.0)

    def test_unit_price_none_when_quantity_none(self):
        item = ImportItem(barcode="1234567890123", quantity=None, total_price=250.0)
        self.assertIsNone(item.unit_price)

    def test_unit_price_none_when_total_price_none(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=None)
        self.assertIsNone(item.unit_price)

    def test_flagged_when_barcode_none(self):
        item = ImportItem(barcode=None, quantity=10, total_price=100.0)
        self.assertTrue(item.flagged)

    def test_not_flagged_when_all_present(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=100.0)
        self.assertFalse(item.flagged)

    def test_barcode_suspect_when_wrong_length(self):
        item = ImportItem(barcode="123", quantity=10, total_price=100.0)
        self.assertTrue(item.barcode_suspect)

    def test_barcode_not_suspect_when_13_digits(self):
        item = ImportItem(barcode="1234567890123", quantity=10, total_price=100.0)
        self.assertFalse(item.barcode_suspect)


class TestParseGeminiResponse(unittest.TestCase):
    def test_parses_valid_json(self):
        raw = '[{"barcode": "1234567890123", "quantity": 5, "total_price": 100.0}]'
        items = parse_gemini_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].barcode, "1234567890123")
        self.assertEqual(items[0].quantity, 5)
        self.assertAlmostEqual(items[0].total_price, 100.0)

    def test_parses_null_fields(self):
        raw = '[{"barcode": null, "quantity": 3, "total_price": null}]'
        items = parse_gemini_response(raw)
        self.assertIsNone(items[0].barcode)
        self.assertIsNone(items[0].total_price)
        self.assertTrue(items[0].flagged)

    def test_strips_markdown_code_fence(self):
        raw = '```json\n[{"barcode": "111", "quantity": 1, "total_price": 10.0}]\n```'
        items = parse_gemini_response(raw)
        self.assertEqual(len(items), 1)

    def test_returns_empty_on_invalid_json(self):
        items = parse_gemini_response("not json at all")
        self.assertEqual(items, [])


class TestBuildExcelBytes(unittest.TestCase):
    def test_returns_bytes(self):
        items = [ImportItem(barcode="1234567890123", quantity=2, total_price=50.0)]
        result = build_excel_bytes(items)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_sorted_by_barcode(self):
        import io
        import openpyxl
        items = [
            ImportItem(barcode="9999999999999", quantity=1, total_price=10.0),
            ImportItem(barcode="1111111111111", quantity=2, total_price=20.0),
        ]
        data = build_excel_bytes(items)
        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.assertEqual(rows[0][0], "1111111111111")
        self.assertEqual(rows[1][0], "9999999999999")
