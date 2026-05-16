"""etl/parquet_importer 集成测试。

每个 case 自起 temp DB，verify 行真正落到 inventory_events + 主档 UPSERT。
模仿 tests/test_inventory_importer.py 的 setUp 模式。
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from etl.parquet_importer import (
    PURCHASE_MAPPING,
    SALE_MAPPING,
    import_cleaned_parquet,
    import_dataframe,
)
from app.models import Base, Customer, InventoryEvent, Stockpile, Supplier

_TEST_DIR = Path(__file__).resolve().parent / "_test_parquet_importer"


def _row(**kw):
    base = {
        "event_at": "2025-06-01",
        "event_type": "sale",
        "product_barcode": "1234567890123",
        "qty": 2,
        "unit_price": 5.0,
        "discount_pct": 0.0,
        "document_no": "D1",
        "shipping_doc": None,
        "customer_id": "C001",
        "customer_name": "小明",
        "supplier_id": None,
        "supplier_name": None,
        "warehouse": "WH1",
        "erp_category_raw": "A01-基础",
        "product_name_zh": "测试品",
        "product_name_local": "test",
    }
    base.update(kw)
    return base


class ParquetImporterTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = _TEST_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.test_dir / 'test.db'}", future=True)
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_import_sale_row_lands_in_db(self):
        df = pd.DataFrame([_row()])
        with Session(self.engine) as session:
            sale_r, purchase_r = import_dataframe(df, session)
            session.commit()
        assert sale_r.rows_imported == 1
        assert purchase_r.rows_imported == 0

        with Session(self.engine) as session:
            events = session.execute(select(InventoryEvent)).scalars().all()
            assert len(events) == 1
            e = events[0]
            assert e.event_type == "sale"
            assert e.product_barcode == "1234567890123"
            assert e.qty == 2
            assert e.customer_id == "C001"
            assert e.supplier_id is None

    def test_import_purchase_row(self):
        df = pd.DataFrame(
            [
                _row(
                    event_type="purchase",
                    customer_id=None,
                    customer_name=None,
                    supplier_id="V001",
                    supplier_name="HOMEPLAST",
                    document_no="P1",
                )
            ]
        )
        with Session(self.engine) as session:
            sale_r, purchase_r = import_dataframe(df, session)
            session.commit()
        assert sale_r.rows_imported == 0
        assert purchase_r.rows_imported == 1

        with Session(self.engine) as session:
            e = session.execute(select(InventoryEvent)).scalars().one()
            assert e.event_type == "purchase"
            assert e.supplier_id == "V001"
            assert e.customer_id is None

    def test_mixed_sale_and_purchase_split_correctly(self):
        df = pd.DataFrame(
            [
                _row(),
                _row(
                    event_type="purchase",
                    document_no="P1",
                    customer_id=None,
                    customer_name=None,
                    supplier_id="V001",
                    supplier_name="HOMEPLAST",
                ),
                _row(document_no="D2", customer_id="C002", customer_name="希腊客户"),
            ]
        )
        with Session(self.engine) as session:
            sale_r, purchase_r = import_dataframe(df, session)
            session.commit()
        assert sale_r.rows_imported == 2
        assert purchase_r.rows_imported == 1

    def test_customer_auto_upserted_from_sale(self):
        df = pd.DataFrame([_row()])
        with Session(self.engine) as session:
            import_dataframe(df, session)
            session.commit()
            customers = session.execute(select(Customer)).scalars().all()
            assert len(customers) == 1
            assert customers[0].customer_id == "C001"
            assert customers[0].customer_name == "小明"
            assert customers[0].customer_type == "chinese"

    def test_supplier_auto_upserted_from_purchase(self):
        df = pd.DataFrame(
            [
                _row(
                    event_type="purchase",
                    customer_id=None,
                    customer_name=None,
                    supplier_id="V001",
                    supplier_name="HOMEPLAST",
                    document_no="P1",
                )
            ]
        )
        with Session(self.engine) as session:
            import_dataframe(df, session)
            session.commit()
            suppliers = session.execute(select(Supplier)).scalars().all()
            assert len(suppliers) == 1
            assert suppliers[0].supplier_id == "V001"
            assert suppliers[0].supplier_name == "HOMEPLAST"

    def test_stockpile_sku_auto_created(self):
        df = pd.DataFrame([_row()])
        with Session(self.engine) as session:
            import_dataframe(df, session)
            session.commit()
            sps = session.execute(select(Stockpile)).scalars().all()
            assert len(sps) == 1
            assert sps[0].product_barcode == "1234567890123"
            assert sps[0].erp_category_raw == "A01-基础"

    def test_idempotent_rerun(self):
        df = pd.DataFrame([_row()])
        for _ in range(2):
            with Session(self.engine) as session:
                import_dataframe(df, session)
                session.commit()
        with Session(self.engine) as session:
            n = session.execute(select(InventoryEvent)).scalars().all()
            assert len(n) == 1

    def test_import_cleaned_parquet_file(self):
        df = pd.DataFrame([_row(), _row(document_no="D2")])
        p = self.test_dir / "x.parquet"
        df.to_parquet(p, index=False)

        with Session(self.engine) as session:
            sale_r, _ = import_cleaned_parquet(p, session)
            session.commit()
        assert sale_r.rows_imported == 2

    def test_missing_event_type_raises(self):
        df = pd.DataFrame([{"event_at": "2025-06-01", "qty": 1}])
        with Session(self.engine) as session:
            with self.assertRaises(ValueError):
                import_dataframe(df, session)

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["event_type"])
        with Session(self.engine) as session:
            sale_r, purchase_r = import_dataframe(df, session)
        assert sale_r.rows_imported == 0
        assert purchase_r.rows_imported == 0

    def test_sale_mapping_routes_customer_to_partner(self):
        assert SALE_MAPPING["customer_id"] == "partner_id"
        assert SALE_MAPPING["customer_name"] == "partner_name"
        assert "supplier_id" not in SALE_MAPPING

    def test_purchase_mapping_routes_supplier_to_partner(self):
        assert PURCHASE_MAPPING["supplier_id"] == "partner_id"
        assert PURCHASE_MAPPING["supplier_name"] == "partner_name"
        assert "customer_id" not in PURCHASE_MAPPING

    def test_erp_category_code_not_in_mapping(self):
        assert "erp_category_code" not in SALE_MAPPING
        assert "erp_category_code" not in PURCHASE_MAPPING


if __name__ == "__main__":
    unittest.main()
