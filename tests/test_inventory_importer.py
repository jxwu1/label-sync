"""inventory_importer 集成测试。

策略：每个 case 自己起 temp DB + sqlite engine + Base.metadata.create_all，
不动生产 DB。Session 直接传给 importer，避免依赖 stockpile_db 全局 engine。
"""

import shutil
import unittest
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.importers.inventory import (
    DEFAULT_MAPPING,
    _clean_barcode_or_model,
    _clean_date,
    _clean_int,
    _clean_str,
    import_events,
)
from app.models import Base, Customer, InventoryEvent, Stockpile, Supplier
from app.parsers.xls_html import parse_xls_html

_TEST_DIR = Path(__file__).resolve().parent / "_test_inventory_importer"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _BaseImporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = _TEST_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.test_dir / 'test.db'}", future=True)
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        shutil.rmtree(self.test_dir, ignore_errors=True)


class TypeCleaningTests(unittest.TestCase):
    """纯函数类型清洗。"""

    def test_clean_barcode_float_to_int_string(self) -> None:
        assert _clean_barcode_or_model(5828079113422.0) == "5828079113422"

    def test_clean_barcode_string_passthrough(self) -> None:
        assert _clean_barcode_or_model("11342") == "11342"
        assert _clean_barcode_or_model("  11342  ") == "11342"

    def test_clean_barcode_nan(self) -> None:
        assert _clean_barcode_or_model(float("nan")) is None

    def test_clean_int_handles_float_string(self) -> None:
        assert _clean_int("100") == 100
        assert _clean_int("100.0") == 100
        assert _clean_int(100.0) == 100
        assert _clean_int(100) == 100

    def test_clean_date_slash_no_zero_pad(self) -> None:
        assert _clean_date("2026/4/27") == "2026-04-27"

    def test_clean_date_iso(self) -> None:
        assert _clean_date("2026-05-05") == "2026-05-05"

    def test_clean_date_invalid(self) -> None:
        assert _clean_date("not a date") is None
        assert _clean_date("9999/99/99") is None  # 月日越界

    def test_clean_str_strips_and_nans(self) -> None:
        assert _clean_str("  hi  ") == "hi"
        assert _clean_str("") is None
        assert _clean_str("   ") is None
        assert _clean_str(float("nan")) is None


class ImportPurchaseTests(_BaseImporterTest):
    def test_purchase_fixture_imports_2_events(self) -> None:
        df = parse_xls_html(_FIXTURES / "purchase_sample.xls")
        with Session(self.engine) as session:
            result = import_events(df, DEFAULT_MAPPING, "purchase", session)
            session.commit()

        assert result.rows_imported == 2
        assert result.rows_skipped == 0
        assert result.new_suppliers == 1  # 同一 GR0007 出现两次只算一个
        assert result.new_skus == 2

        with Session(self.engine) as session:
            events = session.execute(select(InventoryEvent)).scalars().all()
            assert len(events) == 2
            assert all(e.event_type == "purchase" for e in events)
            assert all(e.supplier_id == "GR0007" for e in events)
            # 条码强制 string
            barcodes = {e.product_barcode for e in events}
            assert "5200310901638" in barcodes
            assert "5828079113422" in barcodes

            suppliers = session.execute(select(Supplier)).scalars().all()
            assert len(suppliers) == 1
            assert suppliers[0].supplier_id == "GR0007"
            assert "HOMEPLAST" in suppliers[0].supplier_name

            skus = session.execute(select(Stockpile)).scalars().all()
            assert len(skus) == 2
            # SKU 带产品名 + 希腊语品名 + erp 类别
            sp = next(s for s in skus if s.product_barcode == "5828079113422")
            assert sp.product_name_zh == "测试鱼竿 2.7m"
            assert sp.product_name_local == "ΚΑΛΑΜΙ 2.7m"
            assert sp.erp_category_code == "FL004-01"
            assert sp.manual_grade == 3

    def test_reimport_same_file_idempotent(self) -> None:
        df = parse_xls_html(_FIXTURES / "purchase_sample.xls")
        with Session(self.engine) as session:
            r1 = import_events(df, DEFAULT_MAPPING, "purchase", session)
            session.commit()
        assert r1.rows_imported == 2

        # 重 import 同一 df
        with Session(self.engine) as session:
            r2 = import_events(df, DEFAULT_MAPPING, "purchase", session)
            session.commit()
        assert r2.rows_imported == 0
        assert r2.rows_skipped_duplicate == 2
        assert r2.new_suppliers == 0
        assert r2.new_skus == 0

        with Session(self.engine) as session:
            events = session.execute(select(InventoryEvent)).scalars().all()
            assert len(events) == 2  # 仍然只有 2 条，没翻倍


class ImportSalesTests(_BaseImporterTest):
    def test_sales_fixture_imports_3_events_2_customers(self) -> None:
        df = parse_xls_html(_FIXTURES / "sales_sample.xls")
        with Session(self.engine) as session:
            result = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()

        assert result.rows_imported == 3
        assert result.new_customers == 2  # 156188672 + 200001
        assert result.new_skus == 3

        with Session(self.engine) as session:
            customers = session.execute(select(Customer)).scalars().all()
            by_id = {c.customer_id: c for c in customers}
            # 希腊语名 → foreign（老外）
            assert by_id["156188672"].customer_type == "foreign"
            # 中文名 → chinese
            assert by_id["200001"].customer_type == "chinese"

            events = session.execute(select(InventoryEvent)).scalars().all()
            assert all(e.event_type == "sale" for e in events)
            assert all(e.supplier_id is None for e in events)
            customer_ids = {e.customer_id for e in events}
            assert customer_ids == {"156188672", "200001"}


class CrossEventTypeTests(_BaseImporterTest):
    """同一 SKU 既出现在采购又出现在销售里。"""

    def test_same_sku_purchase_then_sale_creates_2_events_1_sku(self) -> None:
        # 鱼竿 5828079113422 在 purchase fixture 里被进货 50 件，
        # 在 sales fixture 里被卖出 500 件。SKU 应该只有 1 个，但事件 2 条。
        with Session(self.engine) as session:
            p_df = parse_xls_html(_FIXTURES / "purchase_sample.xls")
            r_p = import_events(p_df, DEFAULT_MAPPING, "purchase", session)
            session.commit()
            s_df = parse_xls_html(_FIXTURES / "sales_sample.xls")
            r_s = import_events(s_df, DEFAULT_MAPPING, "sale", session)
            session.commit()

        # purchase 加了 2 个 SKU；sales 里 11342 已存在（不算 new）+ 11775 新 +
        # 18894 新 = 2 个新 SKU
        assert r_p.new_skus == 2
        assert r_s.new_skus == 2

        with Session(self.engine) as session:
            sku_count = session.execute(select(Stockpile)).scalars().all()
            assert (
                len(sku_count) == 4
            )  # 5200310901638 + 5828079113422 + 5828079117758 + 5828079188949

            events_for_fishing_rod = (
                session.execute(
                    select(InventoryEvent).where(InventoryEvent.product_barcode == "5828079113422")
                )
                .scalars()
                .all()
            )
            types = {e.event_type for e in events_for_fishing_rod}
            assert types == {"purchase", "sale"}


class MissingFieldTests(_BaseImporterTest):
    """缺关键字段的行被跳过。"""

    def test_row_without_barcode_skipped(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "单号": "X1",
                    "ID号": "C1",
                    "名称": "客户1",
                    "日期": "2026-05-05",
                    "型号": "M1",
                    "条形码": None,  # 缺
                    "数量": 5,
                    "单价": 1.0,
                },
                {
                    "单号": "X2",
                    "ID号": "C1",
                    "名称": "客户1",
                    "日期": "2026-05-05",
                    "型号": "M2",
                    "条形码": "BC-OK",
                    "数量": 5,
                    "单价": 1.0,
                },
            ]
        )
        with Session(self.engine) as session:
            result = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
        assert result.rows_imported == 1
        # 销售里 barcode 空 + qty>0 走 orphan 路径反查；型号 M1 在 stockpile 里不存在 →
        # 计入 orphan_barcode 而不是 missing_key（语义更精确）
        assert result.rows_skipped_orphan_barcode == 1
        assert any("反查 未找到" in s for s in result.skipped_reasons)

    def test_completely_empty_row_silently_skipped(self) -> None:
        """ERP 导出常带末尾合计/页脚空行：不报 missing_key，静默跳过。"""
        df = pd.DataFrame(
            [
                {
                    "单号": "X2",
                    "ID号": "C1",
                    "名称": "客户1",
                    "日期": "2026-05-05",
                    "型号": "M2",
                    "条形码": "BC-OK",
                    "数量": 5,
                    "单价": 1.0,
                },
                # 完全空行（合计行）
                {
                    "单号": None,
                    "ID号": None,
                    "名称": None,
                    "日期": None,
                    "型号": None,
                    "条形码": None,
                    "数量": None,
                    "单价": None,
                },
            ]
        )
        with Session(self.engine) as session:
            result = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
        assert result.rows_imported == 1
        # 关键：完全空行不算 missing_key（不让用户以为出错）
        assert result.rows_skipped_missing_key == 0
        assert result.rows_skipped == 0
        assert result.skipped_reasons == []


class InvalidEventTypeTests(_BaseImporterTest):
    def test_raises_on_unknown_event_type(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaises(ValueError, msg="event_type"):
                import_events(pd.DataFrame(), DEFAULT_MAPPING, "transfer", session)


class SalesOrphanBarcodeTests(_BaseImporterTest):
    """销售：barcode 空时按业务规则处理（无日期删 / qty=0 删 / 反查救回）。"""

    def _row(self, **fields) -> dict:
        base = {
            "单号": "S1",
            "ID号": "C1",
            "名称": "客户A",
            "日期": "2026-05-05",
            "型号": "SKU001",
            "条形码": "BC-001",
            "数量": 5,
            "单价": 10.0,
        }
        base.update(fields)
        return base

    def _seed_stockpile(self, sku_records: list[dict]) -> None:
        """直接 seed stockpile 主档（模拟"采购已先导入"场景）。"""
        with Session(self.engine) as session:
            for r in sku_records:
                session.add(
                    Stockpile(
                        product_barcode=r["barcode"],
                        product_model=r["model"],
                        stockpile_location="",
                        is_active=1,
                    )
                )
            session.commit()

    def test_sale_no_barcode_no_date_skipped_no_date_bucket(self) -> None:
        df = pd.DataFrame([self._row(条形码=None, 日期=None)])
        with Session(self.engine) as session:
            r = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
        assert r.rows_imported == 0
        assert r.rows_skipped_no_date == 1
        assert r.rows_skipped_orphan_barcode == 0
        assert r.rows_skipped_missing_key == 0

    def test_sale_no_barcode_qty_zero_skipped_orphan(self) -> None:
        df = pd.DataFrame([self._row(条形码=None, 数量=0)])
        with Session(self.engine) as session:
            r = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
        assert r.rows_imported == 0
        assert r.rows_skipped_orphan_barcode == 1

    def test_sale_no_barcode_qty_pos_model_match_recovered(self) -> None:
        # stockpile 有 SKU001 → BC-001 的对应
        self._seed_stockpile([{"barcode": "BC-001", "model": "SKU001"}])
        df = pd.DataFrame([self._row(条形码=None, 型号="SKU001", 数量=3)])
        with Session(self.engine) as session:
            r = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
            # 事件落库且 barcode 是反查救回的 BC-001
            events = session.execute(select(InventoryEvent)).scalars().all()
            assert len(events) == 1
            assert events[0].product_barcode == "BC-001"
        assert r.rows_imported == 1
        assert r.barcodes_recovered == 1
        assert r.rows_skipped_orphan_barcode == 0

    def test_sale_no_barcode_qty_pos_model_not_found_orphan(self) -> None:
        # stockpile 里没有 UNKNOWN_SKU → 反查 0 match
        df = pd.DataFrame([self._row(条形码=None, 型号="UNKNOWN_SKU")])
        with Session(self.engine) as session:
            r = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
        assert r.rows_imported == 0
        assert r.rows_skipped_orphan_barcode == 1
        assert r.barcodes_recovered == 0
        # 报到 reason
        assert any("反查 未找到" in s for s in r.skipped_reasons)

    def test_sale_no_barcode_qty_pos_model_multi_match_orphan(self) -> None:
        # 同 model 的 2 条 stockpile（不同 barcode）→ 反查 >1 不确定
        self._seed_stockpile(
            [
                {"barcode": "BC-A", "model": "DUP_SKU"},
                {"barcode": "BC-B", "model": "DUP_SKU"},
            ]
        )
        df = pd.DataFrame([self._row(条形码=None, 型号="DUP_SKU")])
        with Session(self.engine) as session:
            r = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
        assert r.rows_imported == 0
        assert r.rows_skipped_orphan_barcode == 1
        assert any("2 个 match" in s for s in r.skipped_reasons)

    def test_sale_no_barcode_no_model_orphan(self) -> None:
        df = pd.DataFrame([self._row(条形码=None, 型号=None)])
        with Session(self.engine) as session:
            r = import_events(df, DEFAULT_MAPPING, "sale", session)
            session.commit()
        assert r.rows_skipped_orphan_barcode == 1
        assert any("无反查依据" in s for s in r.skipped_reasons)

    def test_purchase_no_barcode_still_missing_key_no_recovery(self) -> None:
        """采购导入不启用反查，barcode 空时仍走 missing_key（旧行为）。"""
        # 即使 stockpile 里有 SKU001，采购导入也不去反查
        self._seed_stockpile([{"barcode": "BC-001", "model": "SKU001"}])
        df = pd.DataFrame(
            [
                {
                    "单号": "P1",
                    "ID号": "S1",
                    "名称": "供应商A",
                    "日期": "2026-05-05",
                    "型号": "SKU001",
                    "条形码": None,  # 采购里 barcode 空
                    "数量": 100,
                    "单价": 5.0,
                }
            ]
        )
        with Session(self.engine) as session:
            r = import_events(df, DEFAULT_MAPPING, "purchase", session)
            session.commit()
        assert r.rows_imported == 0
        assert r.rows_skipped_missing_key == 1
        assert r.barcodes_recovered == 0  # 采购不反查
        assert r.rows_skipped_orphan_barcode == 0


if __name__ == "__main__":
    unittest.main()
