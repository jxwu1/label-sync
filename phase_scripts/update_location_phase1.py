import json
import re
import sys
from pathlib import Path

import pandas as pd

from app.config import CONFIG
from app.state import (
    PHASE_EXIT_LOCATION_FORMAT_ERROR,
    PHASE_EXIT_OK,
    PHASE_EXIT_REVIEW_REQUIRED,
)

LOCATION_FORMAT = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$")
VALID_LOCATION_PREFIXES = {"A", "B", "C", "X", "Z"}

INPUT_DIR = CONFIG.input_dir
TEMP_MAPPING_FILE = CONFIG.temp_mapping_file
TEMPLATE_PATH = CONFIG.resource_dir / "static" / "templates" / "产品信息导入模板.csv"

_BARCODE_LENGTH_TOLERANCE = 2


def collect_location_map(scan_files: list[Path]) -> dict[str, list[str]]:
    location_map: dict[str, list[str]] = {}
    print(f"Found {len(scan_files)} scan files, parsing...")

    for scan_file in scan_files:
        print(f"READ {scan_file.name}")
        try:
            dataframe = pd.read_excel(scan_file, header=None, dtype=str, engine="calamine")
            values = dataframe.iloc[:, 0].dropna().astype(str).str.strip()
        except Exception as exc:
            print(f"SKIP {scan_file.name}: {exc}")
            continue

        current_location = None
        for value in values:
            if value[:1].isalpha():
                current_location = value
                continue
            if not current_location:
                continue
            location_map.setdefault(value, [])
            if current_location not in location_map[value]:
                location_map[value].append(current_location)

    return location_map


def is_valid_location(location: str) -> bool:
    if not LOCATION_FORMAT.match(location):
        return False
    return location[:1].upper() in VALID_LOCATION_PREFIXES


def detect_invalid_locations(location_map: dict[str, list[str]]) -> list[str]:
    all_locations = {location for locations in location_map.values() for location in locations}
    return sorted(location for location in all_locations if not is_valid_location(location))


def detect_barcode_outliers(barcodes: list[str]) -> tuple[list[tuple[str, int, int]], int]:
    if not barcodes:
        return [], 0

    lengths = sorted(len(barcode) for barcode in barcodes)
    total = len(lengths)
    median = lengths[total // 2]
    q1 = lengths[total // 4]
    q3 = lengths[(total * 3) // 4]
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    warnings: list[tuple[str, int, int]] = []
    for barcode in barcodes:
        length = len(barcode)
        if length < lower or length > upper or abs(length - median) >= _BARCODE_LENGTH_TOLERANCE:
            warnings.append((barcode, length, median))

    return warnings, median


def analyze_phase_one(
    location_map: dict[str, list[str]],
) -> dict[str, object]:
    duplicate_barcodes = {
        barcode: locations for barcode, locations in location_map.items() if len(locations) > 1
    }
    invalid_locations = detect_invalid_locations(location_map)
    barcode_warnings, median = detect_barcode_outliers(list(location_map))
    if invalid_locations:
        exit_code = PHASE_EXIT_LOCATION_FORMAT_ERROR
    elif barcode_warnings:
        exit_code = PHASE_EXIT_REVIEW_REQUIRED
    else:
        exit_code = PHASE_EXIT_OK
    return {
        "duplicate_barcodes": duplicate_barcodes,
        "invalid_locations": invalid_locations,
        "barcode_warnings": barcode_warnings,
        "median": median,
        "exit_code": exit_code,
    }


def save_temp_mapping(
    location_map: dict[str, list[str]], employee_name: str, scan_files: list[Path]
) -> None:
    with TEMP_MAPPING_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "location_map": location_map,
                "employee_name": employee_name,
                "scan_files": [str(path) for path in scan_files],
            },
            file,
            ensure_ascii=False,
            indent=2,
        )


def main() -> int:
    if not TEMPLATE_PATH.exists():
        print("ERROR: missing template csv")
        return 1
    template_file = TEMPLATE_PATH
    print(f"TEMPLATE {template_file.name}")

    scan_files = sorted(INPUT_DIR.glob("*.xlsx"))
    if not scan_files:
        print("ERROR: missing scan xlsx files in input/")
        return 1

    employee_name = scan_files[0].stem
    print(f"EMPLOYEE {employee_name}")

    location_map = collect_location_map(scan_files)
    analysis = analyze_phase_one(location_map)

    duplicate_barcodes = analysis["duplicate_barcodes"]
    if duplicate_barcodes:
        print(f"[DUPLICATE_BARCODE] {len(duplicate_barcodes)}")
        for barcode, locations in duplicate_barcodes.items():
            print(f"[DUPLICATE_BARCODE] {barcode} {' / '.join(locations)}")

    invalid_locations = analysis["invalid_locations"]
    if invalid_locations:
        for location in invalid_locations:
            print(f"[LOCATION_WARNING] {location}")
        save_temp_mapping(location_map, employee_name, scan_files)
        print("[WAITING] invalid locations need correction")
        return PHASE_EXIT_LOCATION_FORMAT_ERROR

    barcode_warnings = analysis["barcode_warnings"]
    median = analysis["median"]
    if barcode_warnings:
        for barcode, length, normal in barcode_warnings:
            print(f"[BARCODE_WARNING] {barcode} length={length} normal={normal}")

    save_temp_mapping(location_map, employee_name, scan_files)
    print(f"[PHASE1_DONE] total={len(location_map)}")
    if barcode_warnings:
        print(f"[WAITING] barcode warnings need review median={median}")
        return PHASE_EXIT_REVIEW_REQUIRED
    return PHASE_EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
