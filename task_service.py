import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable

from config import CONFIG
from state import (
    BARCODE_WARNING_PATTERN,
    LOCATION_WARNING_PATTERN,
    PHASE1_SCRIPT,
    PHASE2_SCRIPT,
    PHASE2_WARNING_PATTERN,
    PHASE3_SCRIPT,
    PHASE_EXIT_LOCATION_FORMAT_ERROR,
    PHASE_EXIT_OK,
    PHASE_EXIT_REVIEW_REQUIRED,
    task_state,
)
from storage_service import package_latest_output


LineHandler = Callable[[str], None]
ReturnCodeHandler = Callable[[int], bool]


def run_script(script_path: Path):
    process = subprocess.Popen(
        ["python", "-u", str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=CONFIG.child_process_encoding,
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": CONFIG.child_process_encoding},
    )

    if process.stdout is None:
        raise RuntimeError("无法读取子进程输出")

    for line in process.stdout:
        yield line.rstrip()

    process.wait()
    if process.returncode is None:
        raise RuntimeError("子进程未返回退出码")
    return process.returncode


def start_background_task(target) -> None:
    threading.Thread(target=target, daemon=True).start()


def handle_phase_one_line(text: str) -> None:
    if text.startswith("[BARCODE_WARNING]"):
        match = re.match(BARCODE_WARNING_PATTERN, text)
        if match:
            task_state.add_barcode_warning(
                barcode=match.group(1),
                length=int(match.group(2)),
                normal=int(match.group(3)),
            )
        return

    if text.startswith("[LOCATION_WARNING]"):
        match = re.match(LOCATION_WARNING_PATTERN, text)
        if match:
            task_state.add_location_warning(location=match.group(1))


def handle_phase_one_return_code(return_code: int) -> bool:
    if return_code == PHASE_EXIT_LOCATION_FORMAT_ERROR:
        task_state.mark_waiting("location_format")
        return False
    if return_code == PHASE_EXIT_REVIEW_REQUIRED:
        task_state.mark_waiting("anomaly")
        return False
    if return_code == PHASE_EXIT_OK:
        return True
    task_state.mark_error()
    return False


def handle_phase_two_line(text: str) -> None:
    if text.startswith("[NEW_BARCODE]"):
        barcode = text.removeprefix("[NEW_BARCODE]").strip()
        if barcode:
            task_state.add_new_barcode(barcode)
        return

    if text.startswith("[PHASE2_WARNING]"):
        match = re.match(PHASE2_WARNING_PATTERN, text)
        if not match:
            return
        barcode = match.group(1)
        payload_text = match.group(2)
        try:
            payload = json.loads(payload_text)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            reason = payload.get("reason", payload_text)
            task_state.add_phase2_warning(
                barcode=barcode,
                reason=reason,
                locations=[],
                stockpile_stores=payload.get("stockpile_stores", []),
                stockpile_warehouses=payload.get("stockpile_warehouses", []),
                scan_stores=payload.get("scan_stores", []),
                scan_warehouses=payload.get("scan_warehouses", []),
            )
            return
        locations = re.findall(r"'([^']+)'", payload_text)
        task_state.add_phase2_warning(
            barcode=barcode,
            reason=payload_text,
            locations=locations,
        )


def handle_phase_two_return_code(return_code: int) -> bool:
    if return_code == PHASE_EXIT_REVIEW_REQUIRED:
        task_state.mark_waiting("phase2_review")
        return False
    if return_code == PHASE_EXIT_OK:
        return True
    task_state.mark_error()
    return False


def handle_phase_three_return_code(return_code: int) -> bool:
    if return_code != PHASE_EXIT_OK:
        task_state.mark_error()
        return False
    package_latest_output()
    return False


def execute_phase(
    script_path: Path,
    line_handler: LineHandler,
    return_code_handler: ReturnCodeHandler,
) -> bool:
    return_code = None
    script_runner = run_script(script_path)
    while True:
        try:
            text = next(script_runner)
        except StopIteration as stop:
            return_code = stop.value
            break

        task_state.append_log(text)
        line_handler(text)

    if return_code is None:
        raise RuntimeError("子进程未返回退出码")
    return return_code_handler(return_code)


def run_phase_one() -> None:
    task_state.reset()
    auto_continue = False

    try:
        auto_continue = execute_phase(
            script_path=PHASE1_SCRIPT,
            line_handler=handle_phase_one_line,
            return_code_handler=handle_phase_one_return_code,
        )
    except Exception as exc:
        task_state.append_log(f"[错误] {exc}")
        task_state.mark_error()
    finally:
        task_state.set_running(False)

    if auto_continue:
        start_background_task(run_phase_two)


def run_phase_two() -> None:
    task_state.prepare_phase_two()
    auto_continue = False

    try:
        auto_continue = execute_phase(
            script_path=PHASE2_SCRIPT,
            line_handler=handle_phase_two_line,
            return_code_handler=handle_phase_two_return_code,
        )
    except Exception as exc:
        task_state.append_log(f"[错误] {exc}")
        task_state.mark_error()
    finally:
        task_state.set_running(False)

    if auto_continue:
        start_background_task(run_phase_three)


def run_phase_three() -> None:
    task_state.prepare_phase_three()

    try:
        execute_phase(
            script_path=PHASE3_SCRIPT,
            line_handler=lambda _text: None,
            return_code_handler=handle_phase_three_return_code,
        )
    except Exception as exc:
        task_state.append_log(f"[错误] {exc}")
        task_state.mark_error()
    finally:
        task_state.set_running(False)
