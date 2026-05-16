"""pages_tasks routes 单测：Pydantic 边界校验。

聚焦 4 个迁移到 Pydantic 的 endpoint：缺字段 / 空字符串 / 类型错 → 400；
正常通过 → 200 + service mock 调用。其它 endpoint（/upload / /run / /continue
/ /status / /download）不在本次校验改造范围内，留给后续。
"""

import unittest
from unittest import mock

from flask import Flask

import barcode_service
from routes_pages_tasks import bp
from app.schemas import ServiceResult


def _ok() -> ServiceResult:
    return ServiceResult(ok=True, payload={})


class PagesTasksRoutesValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    # ---------- /correct ----------

    def test_correct_ok_strips_whitespace(self) -> None:
        with mock.patch.object(barcode_service, "correct_barcode", return_value=_ok()) as m:
            rv = self.client.post(
                "/correct", json={"old_barcode": "  A1  ", "new_barcode": "  B2  "}
            )
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with("A1", "B2")

    def test_correct_missing_field_400(self) -> None:
        rv = self.client.post("/correct", json={"old_barcode": "A1"})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("new_barcode", rv.get_json()["msg"])

    def test_correct_empty_string_400(self) -> None:
        rv = self.client.post("/correct", json={"old_barcode": "  ", "new_barcode": "B2"})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("old_barcode", rv.get_json()["msg"])

    def test_correct_null_value_400(self) -> None:
        rv = self.client.post("/correct", json={"old_barcode": None, "new_barcode": "B2"})
        self.assertEqual(rv.status_code, 400)

    # ---------- /correct_location ----------

    def test_correct_location_ok(self) -> None:
        with mock.patch.object(barcode_service, "correct_location", return_value=_ok()) as m:
            rv = self.client.post(
                "/correct_location", json={"old_location": "A1-1", "new_location": "B2-2"}
            )
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with("A1-1", "B2-2")

    def test_correct_location_missing_400(self) -> None:
        rv = self.client.post("/correct_location", json={"old_location": "A1-1"})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("new_location", rv.get_json()["msg"])

    # ---------- /resolve_exception ----------

    def test_resolve_exception_ok(self) -> None:
        with mock.patch.object(
            barcode_service, "resolve_phase2_exception", return_value=_ok()
        ) as m:
            rv = self.client.post(
                "/resolve_exception", json={"barcode": "X1", "resolution": "ignore"}
            )
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with("X1", "ignore")

    def test_resolve_exception_missing_resolution_400(self) -> None:
        rv = self.client.post("/resolve_exception", json={"barcode": "X1"})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("resolution", rv.get_json()["msg"])

    # ---------- /delete_barcode ----------

    def test_delete_barcode_ok(self) -> None:
        with mock.patch.object(barcode_service, "delete_barcode", return_value=_ok()) as m:
            rv = self.client.post("/delete_barcode", json={"barcode": "X1"})
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with("X1")

    def test_delete_barcode_empty_400(self) -> None:
        rv = self.client.post("/delete_barcode", json={"barcode": ""})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("barcode", rv.get_json()["msg"])

    def test_delete_barcode_no_body_400(self) -> None:
        rv = self.client.post("/delete_barcode")
        self.assertEqual(rv.status_code, 400)


if __name__ == "__main__":
    unittest.main()
