"""采购单幂等 (包B): 同文件/同内容重传不重复建单。"""

from __future__ import annotations

import unittest
from unittest import mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.services.purchase import PurchaseRow, create_order, list_orders, record_arrival


def _make_test_db():
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, Session


class _DBTestCase(unittest.TestCase):
    def setUp(self):
        import app.models as models_mod

        self.engine, self.Session = _make_test_db()
        self.patch_engine = mock.patch.object(models_mod, "_engine", self.engine)
        self.patch_session = mock.patch.object(models_mod, "_SessionFactory", self.Session)
        self.patch_engine.start()
        self.patch_session.start()

    def tearDown(self):
        self.patch_session.stop()
        self.patch_engine.stop()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _rows(self, qty=10, price=1.0):
        return [
            PurchaseRow(
                barcode="B1",
                price_raw=str(price),
                price=price,
                quantity=qty,
                price_flagged=False,
                quantity_flagged=False,
            )
        ]


class TestCreateOrderIdempotency(_DBTestCase):
    def test_first_create_is_not_duplicate(self):
        r1 = create_order(self._rows(), source_file="apr.xlsx")
        self.assertFalse(r1.get("duplicate", False))
        self.assertEqual(len(list_orders()), 1)

    def test_same_file_same_content_returns_existing(self):
        r1 = create_order(self._rows(), source_file="apr.xlsx")
        r2 = create_order(self._rows(), source_file="apr.xlsx")
        self.assertEqual(r1["order_id"], r2["order_id"])
        self.assertTrue(r2["duplicate"])
        self.assertEqual(len(list_orders()), 1)

    def test_different_file_creates_new(self):
        create_order(self._rows(), source_file="apr.xlsx")
        r2 = create_order(self._rows(), source_file="may.xlsx")
        self.assertFalse(r2.get("duplicate", False))
        self.assertEqual(len(list_orders()), 2)

    def test_arrived_order_does_not_block_reorder(self):
        r1 = create_order(self._rows(), source_file="apr.xlsx")
        record_arrival(r1["order_id"], "2026-06-01")
        r2 = create_order(self._rows(), source_file="apr.xlsx")
        self.assertNotEqual(r1["order_id"], r2["order_id"])
        self.assertFalse(r2.get("duplicate", False))


if __name__ == "__main__":
    unittest.main()
