import json
import os
import time
from pathlib import Path

import pandas as pd

from config import CONFIG

_IO_RETRY_COUNT = 5
_IO_RETRY_DELAY_SEC = 0.02


def _read_json_with_retry(path: Path):
    last_error = None
    for _ in range(_IO_RETRY_COUNT):
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except PermissionError as exc:
            last_error = exc
            time.sleep(_IO_RETRY_DELAY_SEC)
    raise last_error


def _write_json_with_retry(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    last_error = None
    for _ in range(_IO_RETRY_COUNT):
        try:
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(_IO_RETRY_DELAY_SEC)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except PermissionError:
                    pass
    raise last_error


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8", engine="pyarrow")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding=CONFIG.csv_fallback_encoding)


def read_csv_with_sig(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig", engine="pyarrow")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding=CONFIG.csv_fallback_encoding)


def read_input_file(path: Path) -> pd.DataFrame | None:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=0, dtype=str, engine="calamine")
    if suffix == ".csv":
        return read_csv_with_sig(path)
    return None


def find_latest_stockpile_file(directory: Path) -> Path | None:
    stockpile_files = list(directory.glob("*stockpile*.csv"))
    if not stockpile_files:
        return None
    return max(stockpile_files, key=lambda p: p.stat().st_mtime)


def find_single_file(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern))
    if not files:
        return None
    return files[0]


def update_json_file(path: Path, modifier_fn) -> dict | list:
    data = _read_json_with_retry(path)
    modifier_fn(data)
    _write_json_with_retry(path, data)
    return data


def write_phase2_results(
    path: Path,
    results: list[dict[str, str]],
    new_barcodes: list[str],
    exceptions: list,
    unmatched_barcodes: list[str],
    employee_name: str,
    scan_files: list,
    barcode_model_map: dict[str, str],
    stockpile_path: Path,
) -> None:
    _write_json_with_retry(
        path,
        {
            "results": results,
            "new_barcodes": new_barcodes,
            "exceptions": [
                [entry[0], entry[1], entry[2]] if len(entry) > 2 else [entry[0], entry[1]]
                for entry in exceptions
            ],
            "unmatched_barcodes": unmatched_barcodes,
            "employee_name": employee_name,
            "scan_files": scan_files,
            "barcode_model_map": barcode_model_map,
            "stockpile_path": str(stockpile_path),
        },
    )
