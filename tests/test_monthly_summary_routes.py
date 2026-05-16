"""monthly_summary routes 单测：Pydantic 边界校验。"""

import unittest
from unittest import mock

from flask import Flask

from app.services import monthly_summary as monthly_summary_service
from app.routes.monthly_summary import bp


class MonthlySummaryRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def _payload(self, **overrides) -> dict:
        base = {
            "supplier_name": "供应商X",
            "total_price": 1000,
            "tax": 130,
            "invoice_date": "2026-05-05",
            "month": "2026-05",
        }
        base.update(overrides)
        return base

    # ---------- /save ----------

    def test_save_ok(self) -> None:
        with mock.patch.object(monthly_summary_service, "save_record", return_value={"id": 1}) as m:
            rv = self.client.post("/monthly-summary/save", json=self._payload())
        self.assertEqual(rv.status_code, 200)
        self.assertTrue(rv.get_json()["ok"])
        m.assert_called_once()
        # special_tax 默认 0.0
        self.assertEqual(m.call_args.kwargs["special_tax"], 0.0)

    def test_save_with_special_tax(self) -> None:
        with mock.patch.object(monthly_summary_service, "save_record", return_value={"id": 1}) as m:
            rv = self.client.post("/monthly-summary/save", json=self._payload(special_tax=50.5))
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(m.call_args.kwargs["special_tax"], 50.5)

    def test_save_missing_supplier_400(self) -> None:
        payload = self._payload()
        del payload["supplier_name"]
        rv = self.client.post("/monthly-summary/save", json=payload)
        self.assertEqual(rv.status_code, 400)
        self.assertIn("supplier_name", rv.get_json()["msg"])

    def test_save_zero_price_ok(self) -> None:
        # 原行为：0 是合法值（赠品 / 免单），不算 missing
        with mock.patch.object(monthly_summary_service, "save_record", return_value={"id": 1}):
            rv = self.client.post("/monthly-summary/save", json=self._payload(total_price=0, tax=0))
        self.assertEqual(rv.status_code, 200)

    def test_save_invalid_price_400(self) -> None:
        # 强化：原本 float("abc") 抛 → 500，现在边界 400
        rv = self.client.post("/monthly-summary/save", json=self._payload(total_price="abc"))
        self.assertEqual(rv.status_code, 400)
        self.assertIn("total_price", rv.get_json()["msg"])

    def test_save_no_body_400(self) -> None:
        rv = self.client.post("/monthly-summary/save")
        self.assertEqual(rv.status_code, 400)


if __name__ == "__main__":
    unittest.main()
