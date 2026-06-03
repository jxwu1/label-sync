import threading
from copy import deepcopy

from app.config import CONFIG
from app.schemas import BarcodeWarning, LocationWarning, Phase2Warning, TaskSnapshot, TextMessage

BASE_DIR = CONFIG.base_dir
INPUT_DIR = CONFIG.input_dir
OUTPUT_DIR = CONFIG.output_dir
TRANSFER_DIR = CONFIG.transfer_dir
PHASE1_SCRIPT = CONFIG.phase1_script
PHASE2_SCRIPT = CONFIG.phase2_script
PHASE3_SCRIPT = CONFIG.phase3_script
TEMP_MAPPING_FILE = CONFIG.temp_mapping_file
TEMP_RESULTS_FILE = CONFIG.temp_results_file
STOCKPILE_DB = CONFIG.stockpile_db

BARCODE_WARNING_PATTERN = r"\[BARCODE_WARNING\] (\S+) length=(\d+) normal=(\d+)"
LOCATION_WARNING_PATTERN = r"\[LOCATION_WARNING\] (\S+)"
PHASE2_WARNING_PATTERN = r"\[PHASE2_WARNING\] (\S+) (.+)"

# Phase 脚本退出码（在 phase1/phase2/task_service 三处共用）
PHASE_EXIT_OK = 0
PHASE_EXIT_REVIEW_REQUIRED = 2  # 需要人工复核（条码异常 / phase2 审核）
PHASE_EXIT_LOCATION_FORMAT_ERROR = 3  # 位置格式错误，需修正后重跑


class TaskState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = TaskSnapshot()

    def reset(self) -> None:
        with self._lock:
            self._data = TaskSnapshot(running=True)

    def clear(self) -> None:
        """清回完全空闲状态 (取消/重置卡住的任务用)。"""
        with self._lock:
            self._data = TaskSnapshot()

    def prepare_phase_two(self) -> None:
        with self._lock:
            self._data.running = True
            self._data.waiting = False
            self._data.waiting_stage = None
            self._data.new_barcodes = []

    def prepare_phase_three(self) -> None:
        with self._lock:
            self._data.running = True
            self._data.waiting = False
            self._data.waiting_stage = None

    def append_log(self, message: str) -> None:
        with self._lock:
            self._data.log.append(message)

    def add_barcode_warning(self, barcode: str, length: int, normal: int) -> None:
        with self._lock:
            self._data.barcode_warnings.append(
                BarcodeWarning(barcode=barcode, length=length, normal=normal)
            )

    def update_barcode_warning(self, barcode: str, **changes) -> None:
        with self._lock:
            for warning in self._data.barcode_warnings:
                if warning.barcode != barcode:
                    continue
                for key, value in changes.items():
                    setattr(warning, key, value)

    def add_location_warning(self, location: str) -> None:
        with self._lock:
            self._data.location_warnings.append(LocationWarning(location=location))

    def update_location_warning(self, location: str, **changes) -> None:
        with self._lock:
            for warning in self._data.location_warnings:
                if warning.location != location:
                    continue
                for key, value in changes.items():
                    setattr(warning, key, value)

    def add_new_barcode(self, barcode: str) -> None:
        with self._lock:
            self._data.new_barcodes.append(barcode)

    def remove_new_barcode(self, barcode: str) -> None:
        with self._lock:
            self._data.new_barcodes = [b for b in self._data.new_barcodes if b != barcode]

    def replace_new_barcode(self, old_barcode: str, new_barcode: str) -> None:
        with self._lock:
            self._data.new_barcodes = [
                new_barcode if b == old_barcode else b for b in self._data.new_barcodes
            ]

    def add_phase2_warning(
        self,
        barcode: str,
        reason: str,
        locations: list[str],
        stockpile_stores: list[str] | None = None,
        stockpile_warehouses: list[str] | None = None,
        scan_stores: list[str] | None = None,
        scan_warehouses: list[str] | None = None,
        warehouse_only_location: str | None = None,
    ) -> None:
        with self._lock:
            self._data.phase2_warnings.append(
                Phase2Warning(
                    barcode=barcode,
                    reason=reason,
                    locations=locations,
                    stockpile_stores=stockpile_stores or [],
                    stockpile_warehouses=stockpile_warehouses or [],
                    scan_stores=scan_stores or [],
                    scan_warehouses=scan_warehouses or [],
                    warehouse_only_location=warehouse_only_location,
                )
            )

    def update_phase2_warning(self, barcode: str, **changes) -> None:
        with self._lock:
            for warning in self._data.phase2_warnings:
                if warning.barcode != barcode:
                    continue
                for key, value in changes.items():
                    setattr(warning, key, value)

    def mark_waiting(self, waiting_stage: str) -> None:
        with self._lock:
            self._data.waiting = True
            self._data.waiting_stage = waiting_stage

    def mark_error(self) -> None:
        with self._lock:
            self._data.error = True

    def set_running(self, running: bool) -> None:
        with self._lock:
            self._data.running = running

    def set_result_zip(self, result_zip: str) -> None:
        with self._lock:
            self._data.result_zip = result_zip

    def snapshot(self) -> TaskSnapshot:
        with self._lock:
            return deepcopy(self._data)

    def is_running(self) -> bool:
        with self._lock:
            return self._data.running

    def is_waiting(self) -> bool:
        with self._lock:
            return self._data.waiting

    def waiting_stage(self) -> str | None:
        with self._lock:
            return self._data.waiting_stage


class MessageStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = 0
        self._messages: list[TextMessage] = []

    def add(self, text: str, sender: str, current_time: str) -> TextMessage:
        with self._lock:
            self._counter += 1
            message = TextMessage(id=self._counter, text=text, sender=sender, time=current_time)
            self._messages.append(message)
            return deepcopy(message)

    def list(self) -> list[dict]:
        with self._lock:
            return [message.to_dict() for message in self._messages]

    def delete(self, message_id) -> bool:
        with self._lock:
            before = len(self._messages)
            self._messages = [message for message in self._messages if message.id != message_id]
            return len(self._messages) != before

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()


task_state = TaskState()
message_store = MessageStore()
