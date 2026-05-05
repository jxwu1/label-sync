import sys
from dataclasses import dataclass
from pathlib import Path


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    resource_dir: Path
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    child_process_encoding: str = "utf-8"
    csv_fallback_encoding: str = "gbk"
    web_poll_interval_ms: int = 5000
    enable_transfer: bool = True

    @property
    def input_dir(self) -> Path:
        return self.base_dir / "input"

    @property
    def output_dir(self) -> Path:
        return self.base_dir / "output"

    @property
    def transfer_dir(self) -> Path:
        return self.base_dir / "transfer"

    @property
    def trash_dir(self) -> Path:
        return self.base_dir / "垃圾桶"

    @property
    def templates_dir(self) -> Path:
        return self.resource_dir / "templates"

    @property
    def phase1_script(self) -> Path:
        return self.resource_dir / "phase_scripts" / "update_location_phase1.py"

    @property
    def phase2_script(self) -> Path:
        return self.resource_dir / "phase_scripts" / "update_location_phase2.py"

    @property
    def phase3_script(self) -> Path:
        return self.resource_dir / "phase_scripts" / "update_location.py"

    @property
    def temp_mapping_file(self) -> Path:
        return self.input_dir / "_temp_mapping.json"

    @property
    def temp_results_file(self) -> Path:
        return self.input_dir / "_temp_results.json"

    @property
    def stockpile_db(self) -> Path:
        return self.base_dir / "stockpile.db"


CONFIG = AppConfig(base_dir=_data_dir(), resource_dir=_resource_dir())
