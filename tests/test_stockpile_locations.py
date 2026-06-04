"""阶段 1.5 PR1：stockpile_locations 子表 dual-write 测试。

主表 stockpile_location 字符串保留作为月度比对源，子表是派生视图。
"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from sqlalchemy import select

from app.models import Stockpile, StockpileLocation
from app.repositories import stockpile_db

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_stockpile_locations"


def _import(rows: list[dict]) -> int:
    return stockpile_db.import_from_dataframe(pd.DataFrame(rows))


def _get_locations(barcode: str) -> list[dict]:
    with stockpile_db._session() as session:
        rows = session.execute(
            select(
                StockpileLocation.location,
                StockpileLocation.kind,
                StockpileLocation.position,
            )
            .join(Stockpile, Stockpile.id == StockpileLocation.stockpile_id)
            .where(Stockpile.product_barcode == barcode)
            .order_by(StockpileLocation.position)
        ).all()
    return [{"location": r[0], "kind": r[1], "position": r[2]} for r in rows]


def _get_raw_location(barcode: str) -> str:
    with stockpile_db._session() as session:
        return session.execute(
            select(Stockpile.stockpile_location).where(Stockpile.product_barcode == barcode)
        ).scalar_one()


class StockpileLocationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # 引擎缓存可能含其他测试的旧 path，强制清掉
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_single_store_location_creates_one_subtable_row(self) -> None:
        _import(
            [{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22-04-04"}]
        )
        locs = _get_locations("B1")
        self.assertEqual(len(locs), 1)
        self.assertEqual(locs[0], {"location": "A22-04-04", "kind": "store", "position": 0})

    def test_store_plus_warehouse_creates_two_rows_in_order(self) -> None:
        _import(
            [
                {
                    "product_barcode": "B1",
                    "product_model": "M1",
                    "stockpile_location": "A22-04-04/X11-02",
                }
            ]
        )
        locs = _get_locations("B1")
        self.assertEqual(len(locs), 2)
        self.assertEqual(locs[0]["location"], "A22-04-04")
        self.assertEqual(locs[0]["kind"], "store")
        self.assertEqual(locs[1]["location"], "X11-02")
        self.assertEqual(locs[1]["kind"], "warehouse")

    def test_three_segments_one_store_two_warehouses(self) -> None:
        _import(
            [
                {
                    "product_barcode": "B1",
                    "product_model": "M1",
                    "stockpile_location": "A05-06-01/XA05-06/XA05-13",
                }
            ]
        )
        locs = _get_locations("B1")
        self.assertEqual([loc["kind"] for loc in locs], ["store", "warehouse", "warehouse"])

    def test_two_stores_no_warehouses(self) -> None:
        _import(
            [
                {
                    "product_barcode": "B1",
                    "product_model": "M1",
                    "stockpile_location": "A14-12-01/A14-13-01",
                }
            ]
        )
        locs = _get_locations("B1")
        self.assertEqual([loc["kind"] for loc in locs], ["store", "store"])
        self.assertEqual([loc["location"] for loc in locs], ["A14-12-01", "A14-13-01"])

    def test_unknown_prefix_falls_back_to_unknown_kind(self) -> None:
        _import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "Q99-01"}])
        locs = _get_locations("B1")
        self.assertEqual(locs[0]["kind"], "unknown")

    def test_empty_location_creates_no_subtable_rows(self) -> None:
        _import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": ""}])
        self.assertEqual(_get_locations("B1"), [])

    def test_reimport_with_changed_location_replaces_subtable(self) -> None:
        _import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22"}])
        self.assertEqual([loc["location"] for loc in _get_locations("B1")], ["A22"])
        _import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "B13/X11"}])
        locs = _get_locations("B1")
        self.assertEqual([loc["location"] for loc in locs], ["B13", "X11"])
        self.assertEqual([loc["kind"] for loc in locs], ["store", "warehouse"])

    def test_reimport_same_location_does_not_dup(self) -> None:
        _import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22"}])
        _import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22"}])
        self.assertEqual(len(_get_locations("B1")), 1)

    def test_main_table_raw_location_preserved_with_trailing_space(self) -> None:
        """关键约束：raw 字符串原样存主表，不 strip，不 normalize。"""
        raw = "B04-22-04 /Z202-01"  # 中间有尾随空格
        _import([{"product_barcode": "B1", "product_model": "M1", "stockpile_location": raw}])
        self.assertEqual(_get_raw_location("B1"), raw)
        # 子表则保留 strip 后的版本（每段独立 strip）
        locs = _get_locations("B1")
        self.assertEqual(locs[0]["location"], "B04-22-04")  # 空格 strip 掉
        self.assertEqual(locs[1]["location"], "Z202-01")

    def test_segment_with_empty_segment_ignored(self) -> None:
        _import(
            [{"product_barcode": "B1", "product_model": "M1", "stockpile_location": "A22//X11"}]
        )
        locs = _get_locations("B1")
        self.assertEqual(len(locs), 2)  # 空段忽略，不报错

    def test_insert_or_update_also_dual_writes(self) -> None:
        stockpile_db.insert_or_update("B1", "M1", "A22/X11")
        locs = _get_locations("B1")
        self.assertEqual(len(locs), 2)


if __name__ == "__main__":
    unittest.main()
