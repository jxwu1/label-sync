import json
from pathlib import Path

import pandas as pd

from config import CONFIG


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding=CONFIG.csv_fallback_encoding)


def read_csv_with_sig(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding=CONFIG.csv_fallback_encoding)


def read_input_file(path: Path) -> pd.DataFrame | None:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=0, dtype=str)
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
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    modifier_fn(data)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data