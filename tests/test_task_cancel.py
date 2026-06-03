"""标签处理任务取消/重置 (包D', 单操作员场景: 卡住能清掉重来)。"""

from __future__ import annotations

import unittest

from flask import Flask


class TestTaskStateClear(unittest.TestCase):
    def test_clear_resets_to_idle(self) -> None:
        from app.state import TaskState

        ts = TaskState()
        ts.reset()  # running=True
        ts.mark_waiting("anomaly")
        ts.add_new_barcode("X")
        ts.set_result_zip("/tmp/x.zip")

        ts.clear()

        snap = ts.snapshot()
        self.assertFalse(snap.running)
        self.assertFalse(snap.waiting)
        self.assertEqual(snap.new_barcodes, [])
        self.assertIsNone(snap.result_zip)


class TestCancelRoute(unittest.TestCase):
    def setUp(self) -> None:
        from app.routes.pages_tasks import bp
        from app.state import task_state

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(bp)
        self.client = app.test_client()
        self.task_state = task_state
        self.task_state.clear()

    def tearDown(self) -> None:
        self.task_state.clear()

    def test_cancel_when_waiting_clears(self) -> None:
        self.task_state.reset()
        self.task_state.set_running(False)
        self.task_state.mark_waiting("anomaly")

        resp = self.client.post("/cancel")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        self.assertFalse(self.task_state.is_waiting())
        self.assertFalse(self.task_state.is_running())

    def test_cancel_refused_while_running(self) -> None:
        self.task_state.reset()  # running=True, 非 waiting

        resp = self.client.post("/cancel")
        body = resp.get_json()
        self.assertFalse(body["ok"])
        # 仍在运行, 未被清
        self.assertTrue(self.task_state.is_running())


if __name__ == "__main__":
    unittest.main()
