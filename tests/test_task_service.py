import unittest
from unittest.mock import patch

import task_service
from state import task_state


class TaskServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        task_state.reset()
        task_state.set_running(False)

    def test_handle_phase_one_line_adds_barcode_warning(self) -> None:
        task_service.handle_phase_one_line("[BARCODE_WARNING] 123456 length=5 normal=8")

        snapshot = task_state.snapshot()
        self.assertEqual(len(snapshot.barcode_warnings), 1)
        self.assertEqual(snapshot.barcode_warnings[0].barcode, "123456")
        self.assertEqual(snapshot.barcode_warnings[0].length, 5)
        self.assertEqual(snapshot.barcode_warnings[0].normal, 8)

    def test_handle_phase_two_line_adds_phase2_warning_with_locations(self) -> None:
        task_service.handle_phase_two_line(
            "[PHASE2_WARNING] 888 duplicate_locations store=['A-01-01'] warehouse=['X-02-02']"
        )

        snapshot = task_state.snapshot()
        self.assertEqual(len(snapshot.phase2_warnings), 1)
        self.assertEqual(snapshot.phase2_warnings[0].barcode, "888")
        self.assertEqual(
            snapshot.phase2_warnings[0].locations,
            ["A-01-01", "X-02-02"],
        )

    def test_execute_phase_appends_logs_and_returns_auto_continue(self) -> None:
        task_state.reset()

        def fake_run_script(_script_path):
            yield "line one"
            yield "line two"
            return 0

        handled_lines: list[str] = []

        with patch("task_service.run_script", side_effect=fake_run_script):
            auto_continue = task_service.execute_phase(
                script_path=task_service.PHASE1_SCRIPT,
                line_handler=handled_lines.append,
                return_code_handler=lambda code: code == 0,
            )

        snapshot = task_state.snapshot()
        self.assertTrue(auto_continue)
        self.assertEqual(handled_lines, ["line one", "line two"])
        self.assertEqual(snapshot.log[-2:], ["line one", "line two"])

    def test_handle_phase_one_return_code_marks_waiting(self) -> None:
        task_service.handle_phase_one_return_code(3)

        snapshot = task_state.snapshot()
        self.assertTrue(snapshot.waiting)
        self.assertEqual(snapshot.waiting_stage, "location_format")

    def test_handle_phase_three_return_code_packages_output(self) -> None:
        with patch("task_service.package_latest_output") as package_output:
            auto_continue = task_service.handle_phase_three_return_code(0)

        self.assertFalse(auto_continue)
        package_output.assert_called_once()


if __name__ == "__main__":
    unittest.main()
