import unittest
from unittest.mock import patch

from flask import Flask

from routes import register_routes


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__)
        app.config["TESTING"] = True
        register_routes(app)
        self.client = app.test_client()

    def test_run_rejects_when_stockpile_is_not_today(self):
        with (
            patch("routes_pages_tasks.task_state.is_running", return_value=False),
            patch(
                "routes_pages_tasks.task_state.is_waiting",
                return_value=False,
            ),
            patch(
                "routes_pages_tasks.storage_service.validate_stockpile_is_ready",
                return_value=(False, "系统导出文件不是当天的"),
            ),
        ):
            response = self.client.post("/run")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"ok": False, "msg": "系统导出文件不是当天的"})

    def test_run_starts_background_task_when_validation_passes(self):
        with (
            patch("routes_pages_tasks.task_state.is_running", return_value=False),
            patch(
                "routes_pages_tasks.task_state.is_waiting",
                return_value=False,
            ),
            patch(
                "routes_pages_tasks.storage_service.validate_stockpile_is_ready",
                return_value=(True, None),
            ),
            patch("routes_pages_tasks.task_service.start_background_task") as start_task,
        ):
            response = self.client.post("/run")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        start_task.assert_called_once()

    def test_text_send_validates_empty_content(self):
        response = self.client.post("/text_send", json={"text": "   ", "sender": "A"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"ok": False, "msg": "内容不能为空"})

    def test_transfer_delete_validates_filename(self):
        response = self.client.post("/transfer_delete", json={"filename": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"ok": False, "msg": "文件名不能为空"})


if __name__ == "__main__":
    unittest.main()
