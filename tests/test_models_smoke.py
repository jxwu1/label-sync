"""阶段 1.0 smoke：验证 automap ORM 在同一 schema 上与 raw sqlite3 行为一致。

不动生产 stockpile.db；用临时 DB，借 stockpile_db.ensure_db 建表，
然后另起一个 SQLAlchemy engine + automap，对比 ORM 和 raw 的读写结果。
"""
import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, select
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session

import stockpile_db

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_models_smoke"


class ModelsSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db.ensure_db()

        self.engine = create_engine(f"sqlite:///{self.test_db}", future=True)
        Base = automap_base()
        Base.prepare(autoload_with=self.engine)
        self.Stockpile = Base.classes.stockpile
        self.StockpileChange = Base.classes.stockpile_changes

    def tearDown(self) -> None:
        self.engine.dispose()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _raw_insert(self, **kwargs) -> None:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        with sqlite3.connect(str(self.test_db)) as conn:
            conn.execute(
                f"INSERT INTO stockpile ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
            conn.commit()

    def test_orm_select_sees_raw_inserted_row(self) -> None:
        self._raw_insert(
            product_barcode="B001",
            product_model="M001",
            stockpile_location="A22-04-04",
        )
        with Session(self.engine) as session:
            row = session.execute(
                select(self.Stockpile).where(self.Stockpile.product_barcode == "B001")
            ).scalar_one()
        self.assertEqual(row.product_model, "M001")
        self.assertEqual(row.stockpile_location, "A22-04-04")
        self.assertEqual(row.is_active, 1)
        self.assertEqual(row.source, "system_export")
        self.assertEqual(row.extra, "{}")

    def test_orm_insert_visible_to_raw_sqlite(self) -> None:
        with Session(self.engine) as session:
            session.add(
                self.Stockpile(
                    product_barcode="B002",
                    product_model="M002",
                    stockpile_location="B13-01-02",
                    is_active=1,
                    extra=json.dumps({"note": "smoke"}),
                    source="user_correction",
                )
            )
            session.commit()
        with sqlite3.connect(str(self.test_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM stockpile WHERE product_barcode = ?", ("B002",)
            ).fetchone()
        self.assertEqual(row["product_model"], "M002")
        self.assertEqual(row["stockpile_location"], "B13-01-02")
        self.assertEqual(row["source"], "user_correction")
        self.assertEqual(json.loads(row["extra"]), {"note": "smoke"})

    def test_is_active_column_accepts_int_and_returns_int(self) -> None:
        """阶段 1 风险点：is_active 是 INTEGER NOT NULL DEFAULT 1，
        ORM 不能把它当 Boolean，否则 1/True 比较语义会偏。"""
        self._raw_insert(
            product_barcode="B003",
            product_model="M003",
            stockpile_location="C01",
            is_active=0,
        )
        with Session(self.engine) as session:
            row = session.execute(
                select(self.Stockpile).where(self.Stockpile.product_barcode == "B003")
            ).scalar_one()
        self.assertEqual(row.is_active, 0)
        self.assertIsInstance(row.is_active, int)

    def test_default_timestamps_populated_by_db(self) -> None:
        """created_at / updated_at 默认值由 SQLite datetime('now','localtime') 生成，
        ORM insert 不传值时仍应自动填充。"""
        with Session(self.engine) as session:
            obj = self.Stockpile(
                product_barcode="B004",
                product_model="M004",
                stockpile_location="X11",
            )
            session.add(obj)
            session.commit()
        with sqlite3.connect(str(self.test_db)) as conn:
            row = conn.execute(
                "SELECT created_at, updated_at FROM stockpile WHERE product_barcode = ?",
                ("B004",),
            ).fetchone()
        self.assertIsNotNone(row[0])
        self.assertIsNotNone(row[1])

    def test_changes_table_orm_insert_visible_to_raw(self) -> None:
        with Session(self.engine) as session:
            session.add(
                self.StockpileChange(
                    product_barcode="B005",
                    field_name="stockpile_location",
                    old_value="A22",
                    new_value="X11",
                    change_type="update",
                )
            )
            session.commit()
        with sqlite3.connect(str(self.test_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM stockpile_changes WHERE product_barcode = ?", ("B005",)
            ).fetchone()
        self.assertEqual(row["field_name"], "stockpile_location")
        self.assertEqual(row["old_value"], "A22")
        self.assertEqual(row["new_value"], "X11")


if __name__ == "__main__":
    unittest.main()
