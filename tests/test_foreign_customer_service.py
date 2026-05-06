"""老外客人月度记录 service 测试。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

import stockpile_db
from foreign_customer_service import (
    add_record,
    delete_record,
    get_record,
    list_eligible_customers,
    list_records,
    month_summary,
    update_record,
)
from models import Customer

_TEST_DIR = Path(__file__).resolve().parent / "_test_foreign_customer"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = _TEST_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()

        # seed 几个客户：foreign / mixed / chinese / unknown
        with stockpile_db._session() as session:
            for cid, name, ctype in [
                ("F1", "ΑΝΔΡΕΟΥ", "foreign"),
                ("F2", "ΚΙΡΚΙΝΕΖΗΣ", "foreign"),
                ("M1", "周跃勇 ΚΟΖΑΝΗΣ", "mixed"),
                ("C1", "张三", "chinese"),
                ("U1", "JOHN", "unknown"),
            ]:
                session.add(Customer(customer_id=cid, customer_name=name, customer_type=ctype))
            session.commit()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)


class CustomerListTests(_Base):
    def test_list_eligible_customers_sorted_by_type(self) -> None:
        out = list_eligible_customers()
        # foreign 在前，chinese 在后
        types_seq = [c["customer_type"] for c in out]
        # 5 个客户全部列出
        assert len(out) == 5
        # 先 foreign，再 mixed，再 unknown，再 chinese
        assert types_seq[:2] == ["foreign", "foreign"]
        assert types_seq[2] == "mixed"
        assert types_seq[3] == "unknown"
        assert types_seq[4] == "chinese"


class RecordCrudTests(_Base):
    def test_add_record_basic(self) -> None:
        rec = add_record(
            customer_id="F1",
            record_month="2026-05",
            amount_due=1500.0,
            tax_number="GR1234567",
            payment_date="2026-05-10",
        )
        assert rec["customer_id"] == "F1"
        assert rec["record_month"] == "2026-05"
        assert rec["amount_due"] == 1500.0
        assert rec["tax_number"] == "GR1234567"
        assert rec["customer_name"] == "ΑΝΔΡΕΟΥ"

    def test_add_duplicate_same_month_raises(self) -> None:
        add_record(customer_id="F1", record_month="2026-05", amount_due=100.0)
        with self.assertRaises(ValueError, msg="已有记录"):
            add_record(customer_id="F1", record_month="2026-05", amount_due=200.0)

    def test_add_unknown_customer_raises(self) -> None:
        with self.assertRaises(ValueError):
            add_record(customer_id="NOT_EXIST", record_month="2026-05")

    def test_list_records_filters_by_month(self) -> None:
        add_record(customer_id="F1", record_month="2026-04", amount_due=100)
        add_record(customer_id="F1", record_month="2026-05", amount_due=200)
        add_record(customer_id="F2", record_month="2026-05", amount_due=300)

        all_may = list_records(month="2026-05")
        assert len(all_may) == 2
        all_apr = list_records(month="2026-04")
        assert len(all_apr) == 1

    def test_list_records_filters_by_customer(self) -> None:
        add_record(customer_id="F1", record_month="2026-04", amount_due=100)
        add_record(customer_id="F1", record_month="2026-05", amount_due=200)
        add_record(customer_id="F2", record_month="2026-05", amount_due=300)

        f1_records = list_records(customer_id="F1")
        assert len(f1_records) == 2
        # 按月降序
        assert f1_records[0]["record_month"] == "2026-05"

    def test_update_record_partial(self) -> None:
        rec = add_record(customer_id="F1", record_month="2026-05", amount_due=100)
        updated = update_record(rec["id"], payment_date="2026-05-15", notes="款已到")
        assert updated["payment_date"] == "2026-05-15"
        assert updated["notes"] == "款已到"
        assert updated["amount_due"] == 100  # 没传不动

    def test_update_unknown_record_raises(self) -> None:
        with self.assertRaises(ValueError):
            update_record(99999, amount_due=100)

    def test_delete_record(self) -> None:
        rec = add_record(customer_id="F1", record_month="2026-05", amount_due=100)
        assert delete_record(rec["id"]) is True
        assert get_record(rec["id"]) is None
        # 二次删返 False
        assert delete_record(rec["id"]) is False

    def test_get_record_returns_with_customer_name(self) -> None:
        rec = add_record(customer_id="F1", record_month="2026-05", amount_due=100)
        got = get_record(rec["id"])
        assert got is not None
        assert got["customer_name"] == "ΑΝΔΡΕΟΥ"


class SummaryTests(_Base):
    def test_summary_basic(self) -> None:
        add_record(
            customer_id="F1", record_month="2026-05", amount_due=1000, payment_date="2026-05-10"
        )
        add_record(customer_id="F2", record_month="2026-05", amount_due=2000)
        add_record(
            customer_id="M1",
            record_month="2026-05",
            amount_due=500,
            shipping_date="2026-05-12",
        )

        s = month_summary("2026-05")
        assert s["record_count"] == 3
        assert s["total_amount_due"] == 3500
        assert s["paid_count"] == 1  # 只有 F1 有 payment_date
        assert s["unpaid_count"] == 2
        assert s["shipped_count"] == 1  # 只有 M1 有 shipping_date

    def test_summary_empty_month(self) -> None:
        s = month_summary("2099-01")
        assert s["record_count"] == 0
        assert s["total_amount_due"] == 0


if __name__ == "__main__":
    unittest.main()
