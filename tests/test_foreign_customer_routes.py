"""老外客人 routes 测试。"""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

from app.repositories import stockpile_db
from app.models import Customer
from routes_foreign_customers import bp

_TEST_DIR = Path(__file__).resolve().parent / "_test_foreign_customer_routes"


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

        with stockpile_db._session() as session:
            session.add(
                Customer(customer_id="F1", customer_name="ΑΝΔΡΕΟΥ", customer_type="foreign")
            )
            session.add(Customer(customer_id="C1", customer_name="张三", customer_type="chinese"))
            session.commit()

        app = Flask(__name__)
        app.register_blueprint(bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)


class CustomerListRouteTests(_Base):
    def test_list_returns_all(self) -> None:
        rv = self.client.get("/foreign-customers/customers")
        body = rv.get_json()
        assert body["ok"]
        assert len(body["customers"]) == 2


class RecordRouteTests(_Base):
    def test_add_record_ok(self) -> None:
        rv = self.client.post(
            "/foreign-customers/records",
            json={
                "customer_id": "F1",
                "record_month": "2026-05",
                "amount_due": 1500.0,
                "tax_number": "GR123",
            },
        )
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["ok"]
        assert body["record"]["amount_due"] == 1500.0

    def test_add_unknown_customer_400(self) -> None:
        rv = self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "NOPE", "record_month": "2026-05"},
        )
        assert rv.status_code == 400

    def test_add_duplicate_400(self) -> None:
        self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "F1", "record_month": "2026-05"},
        )
        rv = self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "F1", "record_month": "2026-05"},
        )
        assert rv.status_code == 400
        assert "已有" in rv.get_json()["msg"]

    def test_add_missing_required_field_400(self) -> None:
        rv = self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "F1"},  # 缺 record_month
        )
        assert rv.status_code == 400
        assert "record_month" in rv.get_json()["msg"]

    def test_list_records_filtered(self) -> None:
        self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "F1", "record_month": "2026-05", "amount_due": 100},
        )
        self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "F1", "record_month": "2026-04", "amount_due": 50},
        )
        rv = self.client.get("/foreign-customers/records?month=2026-05")
        records = rv.get_json()["records"]
        assert len(records) == 1
        assert records[0]["record_month"] == "2026-05"

    def test_update_record_ok(self) -> None:
        added = self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "F1", "record_month": "2026-05", "amount_due": 100},
        ).get_json()
        rec_id = added["record"]["id"]
        rv = self.client.put(
            f"/foreign-customers/records/{rec_id}",
            json={"payment_date": "2026-05-15", "notes": "OK"},
        )
        assert rv.status_code == 200
        assert rv.get_json()["record"]["payment_date"] == "2026-05-15"

    def test_update_unknown_404(self) -> None:
        rv = self.client.put("/foreign-customers/records/99999", json={"amount_due": 100})
        assert rv.status_code == 404

    def test_delete_record(self) -> None:
        added = self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "F1", "record_month": "2026-05"},
        ).get_json()
        rec_id = added["record"]["id"]
        rv = self.client.delete(f"/foreign-customers/records/{rec_id}")
        assert rv.status_code == 200
        # 再删 404
        rv2 = self.client.delete(f"/foreign-customers/records/{rec_id}")
        assert rv2.status_code == 404


class PdfRouteTests(_Base):
    def test_pdf_empty_month_ok(self) -> None:
        rv = self.client.get("/foreign-customers/pdf/2099-01")
        assert rv.status_code == 200
        assert rv.mimetype == "application/pdf"
        assert rv.data[:4] == b"%PDF"  # PDF magic header

    def test_pdf_with_records_ok(self) -> None:
        self.client.post(
            "/foreign-customers/records",
            json={
                "customer_id": "F1",
                "record_month": "2026-05",
                "amount_due": 1000,
                "tax_number": "GR123",
                "payment_date": "2026-05-10",
                "notes": "正常付款",
            },
        )
        self.client.post(
            "/foreign-customers/records",
            json={
                "customer_id": "C1",
                "record_month": "2026-05",
                "amount_due": 500,
            },
        )
        rv = self.client.get("/foreign-customers/pdf/2026-05")
        assert rv.status_code == 200
        assert rv.mimetype == "application/pdf"
        assert rv.data[:4] == b"%PDF"
        # 文件名带月份
        assert "2026-05" in rv.headers.get("Content-Disposition", "")


class SummaryRouteTests(_Base):
    def test_summary_aggregates(self) -> None:
        self.client.post(
            "/foreign-customers/records",
            json={
                "customer_id": "F1",
                "record_month": "2026-05",
                "amount_due": 1000,
                "payment_date": "2026-05-10",
            },
        )
        self.client.post(
            "/foreign-customers/records",
            json={"customer_id": "C1", "record_month": "2026-05", "amount_due": 500},
        )
        rv = self.client.get("/foreign-customers/summary/2026-05")
        s = rv.get_json()["summary"]
        assert s["record_count"] == 2
        assert s["total_amount_due"] == 1500
        assert s["paid_count"] == 1
        assert s["unpaid_count"] == 1


if __name__ == "__main__":
    unittest.main()
