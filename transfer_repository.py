from pathlib import Path

from path_safety import safe_filename
from state import TRANSFER_DIR


def iter_transfer_items() -> list[Path]:
    return sorted(TRANSFER_DIR.iterdir(), key=lambda item: item.name, reverse=True)


def transfer_file_path(filename: str) -> Path:
    return TRANSFER_DIR / safe_filename(filename)
