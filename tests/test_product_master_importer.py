"""产品总档导入器测试。"""

import json
import shutil
import unittest
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Stockpile, Supplier
from app.importers.product_master import (
    DEFAULT_PRODUCT_MAPPING,
    _is_active_from_web_status,
    _row_to_extra,
    import_product_master,
)

_TEST_DIR = Path(__file__).resolve().parent / "_test_product_master_importer"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = _TEST_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.test_dir / 'test.db'}", future=True)
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        shutil.rmtree(self.test_dir, ignore_errors=True)


class WebStatusToActiveTests(unittest.TestCase):
    def test_yes_to_active(self) -> None:
        assert _is_active_from_web_status("Y") == 1

    def test_no_to_inactive(self) -> None:
        assert _is_active_from_web_status("N") == 0

    def test_nan_to_inactive(self) -> None:
        assert _is_active_from_web_status(float("nan")) == 0

    def test_empty_to_inactive(self) -> None:
        assert _is_active_from_web_status("") == 0
        assert _is_active_from_web_status(None) == 0


class ExtraJsonTests(unittest.TestCase):
    def test_packs_pack_dimensions_and_packaging(self) -> None:
        row = pd.Series(
            {
                "product_id": "abc123",
                "stockpile_shelf": "A",
                "stockpile_quantity": 100,
                "middle_quantity": 6,
                "pack_length": 0.5,
                "product_color": float("nan"),  # NaN 跳过
            }
        )
        extra = json.loads(_row_to_extra(row))
        assert extra["product_id"] == "abc123"
        assert extra["stockpile_shelf"] == "A"
        assert extra["stockpile_quantity"] == "100"
        assert extra["middle_quantity"] == "6"
        assert extra["pack_length"] == "0.5"
        assert "product_color" not in extra  # NaN 不进 extra


class ImportProductMasterTests(_Base):
    def _row(self, **fields) -> dict:
        base = {
            "product_barcode": "5828079113422",
            "product_model": "11342",
            "product_description": "测试鱼竿 2.7m",
            "local_description": "ΚΑΛΑΜΙ 2.7m",
            "stockpile_location": "A14-12-01",
            "product_kind_id": "FL004-01",
            "product_kind_name": "渔具鱼竿_鱼竿",
            "valid_grade": 3,
            "stock_price": 8.5,
            "sale_price": 15.0,
            "provider_id": "GR0001",
            "provider_name": "FORMOPLAST",
            "web_status": "Y",
            "product_id": "src_abc",
            "stockpile_shelf": "A",
            "stockpile_quantity": 50,
        }
        base.update(fields)
        return base

    def test_import_single_row_creates_stockpile_and_supplier(self) -> None:
        df = pd.DataFrame([self._row()])
        with Session(self.engine) as session:
            r = import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
        assert r.rows_imported == 1
        assert r.new_suppliers == 1

        with Session(self.engine) as session:
            sp = session.execute(select(Stockpile)).scalar_one()
            assert sp.product_barcode == "5828079113422"
            assert sp.product_model == "11342"
            assert sp.product_name_zh == "测试鱼竿 2.7m"
            assert sp.product_name_local == "ΚΑΛΑΜΙ 2.7m"
            assert sp.erp_category_code == "FL004-01"
            assert sp.erp_category_raw == "渔具鱼竿_鱼竿"
            assert sp.manual_grade == 3
            assert sp.stock_price == 8.5
            assert sp.sale_price == 15.0
            assert sp.is_active == 1
            extra = json.loads(sp.extra)
            assert extra["product_id"] == "src_abc"
            assert extra["stockpile_shelf"] == "A"

            sup = session.execute(select(Supplier)).scalar_one()
            assert sup.supplier_id == "GR0001"
            assert sup.supplier_name == "FORMOPLAST"

    def test_web_status_n_marks_inactive(self) -> None:
        df = pd.DataFrame([self._row(web_status="N")])
        with Session(self.engine) as session:
            import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
            sp = session.execute(select(Stockpile)).scalar_one()
            assert sp.is_active == 0

    def test_kind_id_zero_kept_as_category_code(self) -> None:
        """新分类（kind_id='0'）也存 erp_category_code='0'，不当 NULL。"""
        df = pd.DataFrame(
            [
                self._row(
                    product_kind_id="0",
                    product_kind_name="新分类ΚΑΙΝΟΥΡΙΑ_ΠΡΟΙΟΝΤΑ",
                )
            ]
        )
        with Session(self.engine) as session:
            import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
            sp = session.execute(select(Stockpile)).scalar_one()
            assert sp.erp_category_code == "0"

    def test_duplicate_barcode_first_wins(self) -> None:
        df = pd.DataFrame(
            [
                self._row(product_barcode="DUP1", product_description="第一条"),
                self._row(product_barcode="DUP1", product_description="第二条"),
            ]
        )
        with Session(self.engine) as session:
            r = import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
        assert r.rows_imported == 1
        assert r.rows_skipped_duplicate_barcode == 1
        with Session(self.engine) as session:
            sp = session.execute(select(Stockpile)).scalar_one()
            assert sp.product_name_zh == "第一条"  # 第一行的赢

    def test_missing_barcode_skipped(self) -> None:
        df = pd.DataFrame([self._row(product_barcode=None), self._row(product_barcode="OK1")])
        with Session(self.engine) as session:
            r = import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
        assert r.rows_imported == 1
        assert r.rows_skipped_missing_barcode == 1

    def test_reimport_updates_existing_skus(self) -> None:
        df1 = pd.DataFrame([self._row(stock_price=8.5, web_status="Y")])
        with Session(self.engine) as session:
            import_product_master(df1, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()

        # 新一份 csv：价格变了 + 下架了
        df2 = pd.DataFrame([self._row(stock_price=9.0, web_status="N")])
        with Session(self.engine) as session:
            r = import_product_master(df2, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
        assert r.rows_imported == 0
        assert r.rows_updated == 1

        with Session(self.engine) as session:
            sp = session.execute(select(Stockpile)).scalar_one()
            assert sp.stock_price == 9.0  # 更新
            assert sp.is_active == 0  # 改下架

    def test_supplier_dedup_across_rows(self) -> None:
        """同 csv 多条记录共享同一供应商 → 只新建一个。"""
        df = pd.DataFrame(
            [
                self._row(product_barcode="P1", provider_id="S1", provider_name="供应商 A"),
                self._row(product_barcode="P2", provider_id="S1", provider_name="供应商 A"),
                self._row(product_barcode="P3", provider_id="S2", provider_name="供应商 B"),
            ]
        )
        with Session(self.engine) as session:
            r = import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
        assert r.new_suppliers == 2  # 只 S1 + S2

    def test_no_provider_id_no_supplier_created(self) -> None:
        df = pd.DataFrame([self._row(provider_id=None, provider_name=None)])
        with Session(self.engine) as session:
            r = import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
        assert r.new_suppliers == 0
        with Session(self.engine) as session:
            assert session.execute(select(Supplier)).first() is None

    def test_import_writes_stockpile_changes_log(self) -> None:
        """新建 SKU 写 insert change；已有 SKU 字段变化写 update change。"""
        from app.models import StockpileChange

        # 第一次 import — 新建
        df1 = pd.DataFrame([self._row(stock_price=8.5)])
        with Session(self.engine) as session:
            import_product_master(df1, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
            inserts = (
                session.execute(
                    select(StockpileChange).where(StockpileChange.change_type == "insert")
                )
                .scalars()
                .all()
            )
            assert len(inserts) == 1
            assert inserts[0].field_name == "product_barcode"

        # 第二次 import — 价格 + 库位变了
        df2 = pd.DataFrame([self._row(stock_price=9.0, stockpile_location="B22-04-04")])
        with Session(self.engine) as session:
            import_product_master(df2, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
            updates = (
                session.execute(
                    select(StockpileChange).where(StockpileChange.change_type == "update")
                )
                .scalars()
                .all()
            )
            fields_changed = {u.field_name for u in updates}
            assert "stock_price" in fields_changed
            assert "stockpile_location" in fields_changed

    def test_import_syncs_locations_subtable(self) -> None:
        """新建 / 更新都要同步 stockpile_locations 子表。"""
        from app.models import StockpileLocation

        df = pd.DataFrame([self._row(stockpile_location="A14-12-01/X11-02")])
        with Session(self.engine) as session:
            import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
            locs = session.execute(select(StockpileLocation)).scalars().all()
            kinds = {loc.kind for loc in locs}
            assert "store" in kinds  # A14-12-01 是 store
            assert "warehouse" in kinds  # X11-02 是 warehouse

    def test_import_writes_snapshot(self) -> None:
        """每次 import_product_master 末尾打一个 trigger='import' 的 snapshot，
        让最近改动 tab 把这次产品总档导入当作批次显示。"""
        from app.models import StockpileSnapshot

        df = pd.DataFrame([self._row()])
        with Session(self.engine) as session:
            import_product_master(df, DEFAULT_PRODUCT_MAPPING, session)
            session.commit()
            snap = session.execute(select(StockpileSnapshot)).scalar_one()
            assert snap.trigger == "import"
            assert snap.total_local == 1


if __name__ == "__main__":
    unittest.main()
