"""collab routes 单测：Pydantic 边界校验。"""

import unittest
from unittest import mock

from flask import Flask

from app.services import message as message_service
from routes_collab import bp


class CollabRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    # ---------- /text_send ----------

    def test_text_send_ok_default_sender(self) -> None:
        with mock.patch.object(
            message_service, "send_text_message", return_value={"ok": True, "msg": {}}
        ) as m:
            rv = self.client.post("/text_send", json={"text": "hi"})
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with("hi", "A")

    def test_text_send_strips_text(self) -> None:
        with mock.patch.object(
            message_service, "send_text_message", return_value={"ok": True, "msg": {}}
        ) as m:
            rv = self.client.post("/text_send", json={"text": "  hi  ", "sender": "B"})
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with("hi", "B")

    def test_text_send_empty_text_400(self) -> None:
        rv = self.client.post("/text_send", json={"text": "  "})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("text", rv.get_json()["msg"])

    def test_text_send_missing_text_400(self) -> None:
        rv = self.client.post("/text_send", json={})
        self.assertEqual(rv.status_code, 400)

    # ---------- /text_delete ----------

    def test_text_delete_ok(self) -> None:
        from app.schemas import ServiceResult

        with mock.patch.object(
            message_service, "delete_text_message", return_value=ServiceResult(ok=True)
        ) as m:
            rv = self.client.post("/text_delete", json={"id": 5})
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with(5)

    def test_text_delete_string_id_coerced(self) -> None:
        from app.schemas import ServiceResult

        with mock.patch.object(
            message_service, "delete_text_message", return_value=ServiceResult(ok=True)
        ) as m:
            rv = self.client.post("/text_delete", json={"id": "7"})
        self.assertEqual(rv.status_code, 200)
        m.assert_called_once_with(7)

    def test_text_delete_missing_id_400(self) -> None:
        rv = self.client.post("/text_delete", json={})
        self.assertEqual(rv.status_code, 400)
        self.assertIn("id", rv.get_json()["msg"])

    def test_text_delete_non_int_id_400(self) -> None:
        rv = self.client.post("/text_delete", json={"id": "abc"})
        self.assertEqual(rv.status_code, 400)


if __name__ == "__main__":
    unittest.main()
