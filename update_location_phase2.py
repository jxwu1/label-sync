import json
import sys
from pathlib import Path

import pandas as pd

from config import CONFIG
from file_io import write_phase2_results
from location_parser import categorize_locations, categorize_stockpile, compose_if_single
from state import PHASE_EXIT_OK, PHASE_EXIT_REVIEW_REQUIRED

INPUT_DIR = CONFIG.input_dir
TEMP_MAPPING_FILE = CONFIG.temp_mapping_file
TEMP_RESULTS_FILE = CONFIG.temp_results_file


def _classify_barcode_entry(
    barcode: str,
    scanned_locations: list[str],
    system_records: dict[str, dict[str, str]],
) -> tuple[str, dict | tuple]:
    scan_stores, scan_warehouses, scan_issue = categorize_locations(scanned_locations)
    if scan_issue:
        return "exception", (barcode, f"scan issue: {scan_issue}")

    system_item = system_records.get(barcode)
    stockpile_stores: list[str] = []
    stockpile_warehouses: list[str] = []
    if system_item is not None:
        stockpile_stores, stockpile_warehouses, system_issue = categorize_stockpile(
            system_item["stockpile_location"]
        )
        if system_issue:
            return "exception", (barcode, f"system issue: {system_issue}")

    multi = (
        len(scan_stores) > 1
        or len(scan_warehouses) > 1
        or len(stockpile_stores) > 1
        or len(stockpile_warehouses) > 1
    )
    if multi:
        return "exception", (
            barcode,
            "multi_location",
            {
                "stockpile_stores": stockpile_stores,
                "stockpile_warehouses": stockpile_warehouses,
                "scan_stores": scan_stores,
                "scan_warehouses": scan_warehouses,
            },
        )

    final_location = compose_if_single(
        stockpile_stores, stockpile_warehouses, scan_stores, scan_warehouses
    )
    if not final_location:
        reason = (
            "new barcode missing valid location"
            if system_item is None
            else "failed to generate final location"
        )
        return "exception", (barcode, reason)

    if system_item is None:
        return "new", {"model": barcode, "location": final_location}
    return "matched", {"model": system_item["model"], "location": final_location}


def build_phase_two_results(
    location_map: dict[str, list[str]],
    system_records: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[str], list, list[str]]:
    results: list[dict[str, str]] = []
    new_barcodes: list[str] = []
    exceptions: list = []

    for barcode, scanned_locations in location_map.items():
        category, data = _classify_barcode_entry(barcode, scanned_locations, system_records)
        if category == "exception":
            exceptions.append(data)
        elif category == "new":
            new_barcodes.append(barcode)
            results.append(data)
        else:
            results.append(data)

    unmatched_barcodes = [barcode for barcode in system_records if barcode not in location_map]
    return results, new_barcodes, exceptions, unmatched_barcodes


def load_phase1_mapping() -> dict | None:
    if not TEMP_MAPPING_FILE.exists():
        print("ERROR: missing phase1 temp mapping")
        return None
    with TEMP_MAPPING_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    TEMP_MAPPING_FILE.unlink()
    return data


def build_system_records(
    dataframe: pd.DataFrame,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
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
    return barcode_model_map, system_records


def main() -> int:
    temp_data = load_phase1_mapping()
    if temp_data is None:
        return 1

    location_map: dict[str, list[str]] = temp_data["location_map"]
    employee_name: str = temp_data["employee_name"]
    scan_files = temp_data["scan_files"]

    print(f"EMPLOYEE {employee_name}")
    print(f"SCAN_COUNT {len(location_map)}")

    from stockpile_db import query_all_as_system_records

    if not INPUT_DIR.exists():
        print("ERROR: input directory not found")
        return 1

    barcode_model_map, system_records = query_all_as_system_records()
    if not system_records:
        print("ERROR: stockpile database is empty, please initialize it first")
        return 1
    print(f"STOCKPILE_DB {len(system_records)} records")
    results, new_barcodes, exceptions, unmatched_barcodes = build_phase_two_results(
        location_map, system_records
    )

    write_phase2_results(
        TEMP_RESULTS_FILE, results, new_barcodes, exceptions, unmatched_barcodes,
        employee_name, scan_files, barcode_model_map, Path("stockpile.db"),
    )

    matched_count = len(results) - len(new_barcodes)
    print(f"[PHASE2_DONE] matched={matched_count}")
    for barcode in new_barcodes:
        print(f"[NEW_BARCODE] {barcode}")
    for entry in exceptions:
        barcode = entry[0]
        reason = entry[1]
        payload = entry[2] if len(entry) > 2 else {}
        message = json.dumps({"reason": reason, **payload}, ensure_ascii=False)
        print(f"[PHASE2_WARNING] {barcode} {message}")

    if new_barcodes or exceptions:
        print("[WAITING] phase2 review required")
        return PHASE_EXIT_REVIEW_REQUIRED
    return PHASE_EXIT_OK


if __name__ == "__main__":
    sys.exit(main())