from pathlib import Path

from app.utils.path_safety import safe_filename
from app.state import OUTPUT_DIR


def list_output_dirs() -> list[Path]:
    return [path for path in OUTPUT_DIR.iterdir() if path.is_dir()]


def latest_output_dir() -> Path | None:
    output_dirs = list_output_dirs()
    if not output_dirs:
        return None
    return max(output_dirs, key=lambda path: path.stat().st_mtime)


def list_output_csv_files() -> list[Path]:
    output_dir = latest_output_dir()
    if output_dir is None:
        return []
    return sorted(output_dir.glob("*.csv"))


def latest_output_csv() -> Path | None:
    csv_files = list_output_csv_files()
    return csv_files[0] if csv_files else None


def list_output_xlsx_files() -> list[Path]:
    output_dir = latest_output_dir()
    if output_dir is None:
        return []
    return sorted(output_dir.glob("*.xlsx"))


def iter_output_items() -> list[Path]:
    return sorted(OUTPUT_DIR.iterdir(), key=lambda item: item.name, reverse=True)


def output_zip_path(filename: str) -> Path:
    return OUTPUT_DIR / safe_filename(filename)
