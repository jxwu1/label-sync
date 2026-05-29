import io
import unittest
from unittest import mock

import openpyxl

from app.services import pricing_sheet


def _eur() -> str:
    return '#,##0.00 "€"'


class TestMedianAndTarget(unittest.TestCase):
    def test_median_odd_even_empty(self):
        self.assertAlmostEqual(pricing_sheet._median([27.0, 35.0, 30.0]), 30.0)
        self.assertAlmostEqual(pricing_sheet._median([27.0, 35.0]), 31.0)
        self.assertIsNone(pricing_sheet._median([]))
        self.assertIsNone(pricing_sheet._median([None, None]))
        self.assertAlmostEqual(pricing_sheet._median([10.0, None, 20.0]), 15.0)

    def test_target_margin_filters_supplier_and_nones(self):
        summary = [
            {"barcode": "A", "supplier_id": "S1", "margin_pct": 35.0},
            {"barcode": "B", "supplier_id": "S1", "margin_pct": 27.0},
            {"barcode": "C", "supplier_id": "S1", "margin_pct": None},
            {"barcode": "D", "supplier_id": "S2", "margin_pct": 99.0},
        ]
        res = pricing_sheet.compute_target_margin_pct(summary, "S1")
        self.assertEqual(res["n_samples"], 2)
        self.assertAlmostEqual(res["median"], 31.0)

    def test_target_margin_no_supplier_or_no_data(self):
        self.assertEqual(pricing_sheet.compute_target_margin_pct([], ""),
                         {"median": None, "n_samples": 0})
        self.assertEqual(
            pricing_sheet.compute_target_margin_pct(
                [{"barcode": "A", "supplier_id": "S9", "margin_pct": None}], "S9"),
            {"median": None, "n_samples": 0})


class TestDetectChanged(unittest.TestCase):
    def test_changed_skipped_and_unknown(self):
        rows = [
            {"barcode": "OLD1", "price": 1.05, "quantity": 50},
            {"barcode": "OLD2", "price": 2.00, "quantity": 10},
            {"barcode": "OLD3", "price": 3.00, "quantity": 5},
            {"barcode": "NEW1", "price": 9.00, "quantity": 1},
        ]
        baselines = {"OLD1": 1.10, "OLD2": 2.00, "OLD3": None}
        changed, skipped = pricing_sheet.detect_changed_old(rows, baselines)
        self.assertEqual(skipped, 1)
        self.assertEqual([c["barcode"] for c in changed], ["OLD1"])
        self.assertAlmostEqual(changed[0]["old_price"], 1.10)
        self.assertAlmostEqual(changed[0]["new_price"], 1.05)
        self.assertEqual(changed[0]["quantity"], 50)

    def test_duplicate_barcode_deduped(self):
        rows = [
            {"barcode": "OLD1", "price": 1.05, "quantity": 50},
            {"barcode": "OLD1", "price": 1.06, "quantity": 10},  # 第二次出现，应被去重
        ]
        changed, skipped = pricing_sheet.detect_changed_old(rows, {"OLD1": 1.10})
        self.assertEqual(len(changed), 1)
        self.assertAlmostEqual(changed[0]["new_price"], 1.05)  # 第一条胜出


class TestBuildItems(unittest.TestCase):
    def test_new_and_changed_assembled(self):
        rows = [
            {"barcode": "NEW1", "price": 5.15, "quantity": 100},
            {"barcode": "OLD1", "price": 1.05, "quantity": 50},
        ]
        new_entries = [{"barcode": "NEW1", "name": "不锈钢勺", "invoice_name": "spoon"}]
        products = {  # 主档已知（=老品），含基准/现售价/品名
            "OLD1": {"name_zh": "陶瓷碗", "sale_price": 1.98, "last_purchase_unit_price": 1.10},
        }
        summary_by_bc = {"OLD1": {"urgency_score": 78.0}}
        out = pricing_sheet.build_pricing_items(new_entries, rows, products, summary_by_bc)
        self.assertEqual(out["skipped_no_baseline"], 0)
        self.assertEqual(len(out["new"]), 1)
        self.assertEqual(len(out["changed"]), 1)

        n = out["new"][0]
        self.assertEqual((n["section"], n["barcode"], n["name_zh"]), ("new", "NEW1", "不锈钢勺"))
        self.assertEqual(n["quantity"], 100)
        self.assertAlmostEqual(n["new_price"], 5.15)
        self.assertIsNone(n["old_price"])
        self.assertIsNone(n["sale_price"])
        self.assertIsNone(n["urgency"])

        c = out["changed"][0]
        self.assertEqual((c["section"], c["barcode"], c["name_zh"]), ("changed", "OLD1", "陶瓷碗"))
        self.assertAlmostEqual(c["old_price"], 1.10)
        self.assertAlmostEqual(c["new_price"], 1.05)
        self.assertAlmostEqual(c["sale_price"], 1.98)
        self.assertAlmostEqual(c["urgency"], 78.0)


class TestBuildXlsx(unittest.TestCase):
    def _items(self):
        return {
            "new": [{"section": "new", "barcode": "NEW1", "name_zh": "勺",
                     "quantity": 100, "old_price": None, "new_price": 5.15,
                     "sale_price": None, "urgency": None}],
            "changed": [{"section": "changed", "barcode": "OLD1", "name_zh": "碗",
                         "quantity": 50, "old_price": 1.10, "new_price": 1.05,
                         "sale_price": 1.98, "urgency": 78.0}],
        }

    def test_layout_formulas_and_format(self):
        data = pricing_sheet.build_pricing_xlsx(self._items(), 0.30, "雅典XX贸易", "20260529")
        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active
        # B2 = 目标利润率小数 + 百分比格式
        self.assertAlmostEqual(ws["B2"].value, 0.30)
        self.assertEqual(ws["B2"].number_format, "0.00%")
        # 表头行（第 4 行）
        self.assertEqual(ws.cell(row=4, column=1).value, "图片")
        self.assertEqual(ws.cell(row=4, column=2).value, "条码")
        self.assertEqual(ws.cell(row=4, column=9).value, "建议批发价")
        # 收集所有单元格文本，确认两个分段标题存在
        texts = {c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)}
        self.assertIn("◆ 新产品", texts)
        self.assertIn("◆ 调价老产品", texts)
        # 找到第一条数据行（条码列=NEW1），断言建议批发价公式引用 $B$2、热度="新品"
        new_r = next(r for r in range(1, ws.max_row + 1)
                     if ws.cell(row=r, column=2).value == "NEW1")
        self.assertIn("$B$2", str(ws.cell(row=new_r, column=9).value))
        self.assertEqual(ws.cell(row=new_r, column=6).value, 5.15)        # 新进价
        self.assertEqual(ws.cell(row=new_r, column=13).value, "新品")      # 热度
        self.assertIsNone(ws.cell(row=new_r, column=5).value)            # 旧进价空
        self.assertEqual(ws.cell(row=new_r, column=6).number_format, _eur())
        # 调价老品行
        old_r = next(r for r in range(1, ws.max_row + 1)
                     if ws.cell(row=r, column=2).value == "OLD1")
        self.assertEqual(ws.cell(row=old_r, column=5).value, 1.10)        # 旧进价
        self.assertEqual(ws.cell(row=old_r, column=7).value, 1.98)        # 现售价
        self.assertEqual(ws.cell(row=old_r, column=13).value, 78.0)       # 热度数值
        self.assertIn("/", str(ws.cell(row=old_r, column=8).value))       # 现利润率是公式
        # 图片列空 + 行高加高
        self.assertIsNone(ws.cell(row=new_r, column=1).value)
        self.assertIsNotNone(ws.row_dimensions[new_r].height)
        self.assertGreaterEqual(ws.row_dimensions[new_r].height, 60)


    def test_name_formula_injection_neutralized(self):
        items = {
            "new": [{"section": "new", "barcode": "X1", "name_zh": "=1+1",
                     "quantity": 1, "old_price": None, "new_price": 2.0,
                     "sale_price": None, "urgency": None}],
            "changed": [],
        }
        data = pricing_sheet.build_pricing_xlsx(items, 0.30, "S", "20260529")
        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active
        row = next(r for r in range(1, ws.max_row + 1)
                   if ws.cell(row=r, column=2).value == "X1")
        cell = ws.cell(row=row, column=3)
        # openpyxl 存入 "'=1+1"（带前导撇号），roundtrip 后 data_type='s'（文本）不是 'f'（活公式）
        self.assertNotEqual(cell.data_type, "f")  # 不能是活公式
        self.assertEqual(cell.value, "'=1+1")      # 存储的是带撇号的字面文本


class TestOrchestration(unittest.TestCase):
    def _fixture(self):
        rows = [
            {"barcode": "NEW1", "price": 5.15, "quantity": 100},
            {"barcode": "OLD1", "price": 1.05, "quantity": 50},
            {"barcode": "OLD2", "price": 2.00, "quantity": 10},  # 不变
        ]
        new_entries = [{"barcode": "NEW1", "name": "勺", "invoice_name": "spoon"}]
        products = {
            "OLD1": {"name_zh": "碗", "sale_price": 1.98, "last_purchase_unit_price": 1.10},
            "OLD2": {"name_zh": "铲", "sale_price": 3.0, "last_purchase_unit_price": 2.00},
        }
        summary = [
            {"barcode": "OLD1", "supplier_id": "S1", "margin_pct": 35.0, "urgency_score": 78.0},
            {"barcode": "OLD2", "supplier_id": "S1", "margin_pct": 27.0, "urgency_score": 12.0},
        ]
        p1 = mock.patch.object(pricing_sheet.stockpile_db,
                               "query_products_by_barcodes", return_value=products)
        p2 = mock.patch.object(pricing_sheet.analytics_service,
                               "list_sku_summary", return_value=summary)
        return rows, new_entries, p1, p2

    def test_preview(self):
        rows, new_entries, p1, p2 = self._fixture()
        with p1, p2:
            res = pricing_sheet.preview_pricing(rows, new_entries, "S1")
        self.assertAlmostEqual(res["target_margin_pct"], 31.0)  # median(35,27)
        self.assertEqual(res["n_samples"], 2)
        self.assertEqual(res["n_new"], 1)
        self.assertEqual(res["n_changed"], 1)  # 仅 OLD1 变动
        self.assertEqual(res["skipped_no_baseline"], 0)

    def test_export_bytes_roundtrip(self):
        rows, new_entries, p1, p2 = self._fixture()
        with p1, p2:
            data = pricing_sheet.export_pricing_bytes(
                rows, new_entries, "S1", "雅典XX贸易", 30.0, "20260529")
        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active
        self.assertAlmostEqual(ws["B2"].value, 0.30)  # 30.0% → 0.30
        texts = {c.value for r_ in ws.iter_rows() for c in r_ if isinstance(c.value, str)}
        self.assertIn("◆ 新产品", texts)
        self.assertIn("◆ 调价老产品", texts)
