import json
import sys
from pathlib import Path

import pandas as pd

from config import CONFIG
from state import PHASE_EXIT_OK, PHASE_EXIT_REVIEW_REQUIRED

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


def categorize_locations(locations: list[str]) -> tuple[list[str], list[str], str | None]:
    cleaned = [location.strip() for location in locations if location and location.strip()]
    stores: list[str] = []
    warehouses: list[str] = []
    for location in cleaned:
        category = classify_location(location)
        if category is None:
            return [], [], f"unknown location prefix: {location}"
        if category == "store":
            if location not in stores:
                stores.append(location)
        else:
            if location not in warehouses:
                warehouses.append(location)
    return stores, warehouses, None


def parse_locations(locations: list[str]) -> tuple[str | None, str | None, str | None]:
    stores, warehouses, error = categorize_locations(locations)
    if error:
        return None, None, error
    if not stores and not warehouses:
        return None, None, None
    if len(stores) > 1 or len(warehouses) > 1:
        parts = []
        if stores:
            parts.append(f"store=[{','.join(stores)}]")
        if warehouses:
            parts.append(f"warehouse=[{','.join(warehouses)}]")
        return None, None, f"duplicate_locations {' '.join(parts)}"
    return (
        stores[0] if stores else None,
        warehouses[0] if warehouses else None,
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


def _categorize_stockpile(raw: str) -> tuple[list[str], list[str], str | None]:
    text = str(raw or "").strip()
    if not text or text == "nan":
        return [], [], None
    parts = text.split("/")
    if any(not part.strip() for part in parts):
        return [], [], f"invalid system location: {text}"
    return categorize_locations(parts)


def _compose_if_single(
    stockpile_stores: list[str],
    stockpile_warehouses: list[str],
    scan_stores: list[str],
    scan_warehouses: list[str],
) -> str:
    store = (scan_stores[0] if scan_stores else None) or (
        stockpile_stores[0] if stockpile_stores else None
    )
    warehouse = (scan_warehouses[0] if scan_warehouses else None) or (
        stockpile_warehouses[0] if stockpile_warehouses else None
    )
    return compose_location(None, None, store, warehouse)


def build_phase_two_results(
    location_map: dict[str, list[str]],
    system_records: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[str], list, list[str]]:
    """Returns (results, new_barcodes, exceptions, unmatched_barcodes).

    Exceptions are tuples:
      (barcode, reason_str) for simple reasons, or
      (barcode, reason_str, payload_dict) for multi-location conflicts carrying
      {stockpile_stores, stockpile_warehouses, scan_stores, scan_warehouses}.
    """
    results: list[dict[str, str]] = []
    new_barcodes: list[str] = []
    exceptions: list = []

    for barcode, scanned_locations in location_map.items():
        scan_stores, scan_warehouses, scan_issue = categorize_locations(scanned_locations)
        if scan_issue:
            exceptions.append((barcode, f"scan issue: {scan_issue}"))
            continue

        system_item = system_records.get(barcode)
        stockpile_stores: list[str] = []
        stockpile_warehouses: list[str] = []
        if system_item is not None:
            stockpile_stores, stockpile_warehouses, system_issue = _categorize_stockpile(
                system_item["stockpile_location"]
            )
            if system_issue:
                exceptions.append((barcode, f"system issue: {system_issue}"))
                continue

        multi = (
            len(scan_stores) > 1
            or len(scan_warehouses) > 1
            or len(stockpile_stores) > 1
            or len(stockpile_warehouses) > 1
        )
        if multi:
            payload = {
                "stockpile_stores": stockpile_stores,
                "stockpile_warehouses": stockpile_warehouses,
                "scan_stores": scan_stores,
                "scan_warehouses": scan_warehouses,
            }
            exceptions.append((barcode, "multi_location", payload))
            continue

        final_location = _compose_if_single(
            stockpile_stores, stockpile_warehouses, scan_stores, scan_warehouses
        )
        if not final_location:
            reason = (
                "new barcode missing valid location"
                if system_item is None
                else "failed to generate final location"
            )
            exceptions.append((barcode, reason))
            continue

        if system_item is None:
            new_barcodes.append(barcode)
            results.append({"model": barcode, "location": final_location})
        else:
            results.append({"model": system_item["model"], "location": final_location})

    unmatched_barcodes = [barcode for barcode in system_records if barcode not in location_map]
    return results, new_barcodes, exceptions, unmatched_barcodes


def find_latest_stockpile_file() -> Path | None:
    stockpile_files = list(INPUT_DIR.glob("*stockpile*.csv"))
    if not stockpile_files:
        return None
    return max(stockpile_files, key=lambda path: path.stat().st_mtime)


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


def write_phase2_results(
    results: list[dict[str, str]],
    new_barcodes: list[str],
    exceptions: list,
    unmatched_barcodes: list[str],
    employee_name: str,
    scan_files: list,
    barcode_model_map: dict[str, str],
    stockpile_path: Path,
) -> None:
    with TEMP_RESULTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(
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
            file,
            ensure_ascii=False,
            indent=2,
        )


def main() -> int:
    temp_data = load_phase1_mapping()
    if temp_data is None:
        return 1

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

    barcode_model_map, system_records = build_system_records(read_csv(stockpile_path))
    results, new_barcodes, exceptions, unmatched_barcodes = build_phase_two_results(
        location_map, system_records
    )

    write_phase2_results(
        results, new_barcodes, exceptions, unmatched_barcodes,
        employee_name, scan_files, barcode_model_map, stockpile_path,
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
