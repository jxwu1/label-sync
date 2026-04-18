import json
import sys
from pathlib import Path

import pandas as pd

from config import CONFIG

INPUT_DIR = CONFIG.input_dir
TEMP_MAPPING_FILE = CONFIG.temp_mapping_file
TEMP_RESULTS_FILE = CONFIG.temp_results_file

STORE_PREFIXES = {"A", "B", "C"}
WAREHOUSE_PREFIXES = {"X", "Z"}


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding=CONFIG.csv_fallback_encoding)


def classify_location(location: str) -> str | None:
    if not location:
        return None
    prefix = location[:1].upper()
    if prefix in STORE_PREFIXES:
        return "store"
    if prefix in WAREHOUSE_PREFIXES:
        return "warehouse"
    return None


def parse_locations(locations: list[str]) -> tuple[str | None, str | None, str | None]:
    cleaned = [location.strip() for location in locations if location and location.strip()]
    if not cleaned:
        return None, None, None

    store_locs: list[str] = []
    warehouse_locs: list[str] = []
    for location in cleaned:
        category = classify_location(location)
        if category is None:
            return None, None, f"unknown location prefix: {location}"
        if category == "store":
            store_locs.append(location)
        else:
            warehouse_locs.append(location)

    if len(store_locs) > 1 or len(warehouse_locs) > 1:
        parts = []
        if store_locs:
            parts.append(f"store=[{','.join(store_locs)}]")
        if warehouse_locs:
            parts.append(f"warehouse=[{','.join(warehouse_locs)}]")
        return None, None, f"duplicate_locations {' '.join(parts)}"

    return (
        store_locs[0] if store_locs else None,
        warehouse_locs[0] if warehouse_locs else None,
        None,
    )


def parse_system_location(value: str) -> tuple[str | None, str | None, str | None]:
    raw = str(value or "").strip()
    if not raw or raw == "nan":
        return None, None, None
    parts = raw.split("/")
    if any(not part.strip() for part in parts):
        return None, None, f"invalid system location: {raw}"
    return parse_locations(parts)


def compose_location(
    old_store: str | None,
    old_warehouse: str | None,
    new_store: str | None,
    new_warehouse: str | None,
) -> str:
    final_store = new_store or old_store
    final_warehouse = new_warehouse or old_warehouse
    if final_store and final_warehouse:
        return f"{final_store}/{final_warehouse}"
    return final_store or final_warehouse or ""


def build_phase_two_results(
    location_map: dict[str, list[str]],
    system_records: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[str], list[tuple[str, str]], list[str]]:
    results: list[dict[str, str]] = []
    new_barcodes: list[str] = []
    exceptions: list[tuple[str, str]] = []

    for barcode, scanned_locations in location_map.items():
        new_store, new_warehouse, scan_issue = parse_locations(scanned_locations)
        if scan_issue:
            exceptions.append((barcode, f"scan issue: {scan_issue}"))
            continue

        system_item = system_records.get(barcode)
        if system_item is None:
            new_barcodes.append(barcode)
            final_location = compose_location(None, None, new_store, new_warehouse)
            if not final_location:
                exceptions.append((barcode, "new barcode missing valid location"))
                continue
            results.append({"model": barcode, "location": final_location})
            continue

        old_store, old_warehouse, system_issue = parse_system_location(
            system_item["stockpile_location"]
        )
        if system_issue:
            exceptions.append((barcode, f"system issue: {system_issue}"))
            continue

        final_location = compose_location(old_store, old_warehouse, new_store, new_warehouse)
        if not final_location:
            exceptions.append((barcode, "failed to generate final location"))
            continue

        results.append({"model": system_item["model"], "location": final_location})

    unmatched_barcodes = [barcode for barcode in system_records if barcode not in location_map]
    return results, new_barcodes, exceptions, unmatched_barcodes


def find_latest_stockpile_file() -> Path | None:
    stockpile_files = list(INPUT_DIR.glob("*stockpile*.csv"))
    if not stockpile_files:
        return None
    return max(stockpile_files, key=lambda path: path.stat().st_mtime)


def main() -> int:
    if not TEMP_MAPPING_FILE.exists():
        print("ERROR: missing phase1 temp mapping")
        return 1

    with TEMP_MAPPING_FILE.open("r", encoding="utf-8") as file:
        temp_data = json.load(file)
    TEMP_MAPPING_FILE.unlink()

    location_map: dict[str, list[str]] = temp_data["location_map"]
    employee_name: str = temp_data["employee_name"]
    scan_files = temp_data["scan_files"]

    print(f"EMPLOYEE {employee_name}")
    print(f"SCAN_COUNT {len(location_map)}")

    stockpile_path = find_latest_stockpile_file()
    if stockpile_path is None:
        print("ERROR: missing stockpile csv")
        return 1
    print(f"STOCKPILE {stockpile_path.name}")
    dataframe = read_csv(stockpile_path)

    barcode_model_map: dict[str, str] = {}
    system_records: dict[str, dict[str, str]] = {}
    for _, row in dataframe.iterrows():
        barcode = str(row.get("product_barcode", "")).strip()
        if not barcode:
            continue
        model = str(row.get("product_model", "")).strip()
        stockpile_location = str(row.get("stockpile_location", "")).strip()
        barcode_model_map[barcode] = "" if model == "nan" else model
        system_records[barcode] = {
            "model": barcode_model_map[barcode],
            "stockpile_location": "" if stockpile_location == "nan" else stockpile_location,
        }
    results, new_barcodes, exceptions, unmatched_barcodes = build_phase_two_results(
        location_map, system_records
    )

    with TEMP_RESULTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "results": results,
                "new_barcodes": new_barcodes,
                "exceptions": [[barcode, reason] for barcode, reason in exceptions],
                "unmatched_barcodes": unmatched_barcodes,
                "employee_name": employee_name,
                "scan_files": scan_files,
                "barcode_model_map": barcode_model_map,
                "stockpile_path": str(stockpile_path),
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    matched_count = len(results) - len(new_barcodes)
    print(f"[PHASE2_DONE] matched={matched_count}")
    for barcode in new_barcodes:
        print(f"[NEW_BARCODE] {barcode}")
    for barcode, reason in exceptions:
        print(f"[PHASE2_WARNING] {barcode} {reason}")

    if new_barcodes or exceptions:
        print("[WAITING] phase2 review required")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
