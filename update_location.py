import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import CONFIG

INPUT_DIR = CONFIG.input_dir
OUTPUT_DIR = CONFIG.output_dir
TRASH_DIR = CONFIG.trash_dir
TEMP_RESULTS_FILE = CONFIG.temp_results_file

TRASH_DIR.mkdir(exist_ok=True)


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding=CONFIG.csv_fallback_encoding)


def lookup_model(value, barcode_model_map: dict[str, str]) -> str:
    barcode = str(value).strip() if pd.notna(value) else ""
    if barcode and not barcode[:1].isalpha():
        return barcode_model_map.get(barcode, "")
    return ""


def build_output_dataframe(
    template_df: pd.DataFrame, results: list[dict[str, str]]
) -> pd.DataFrame:
    rows = []
    for item in results:
        row = {
            "型号": item["model"],
            "位置": item["location"],
            "货区": "A",
            "仓库ID号": "101",
            "仓库名称": "店面",
        }
        for column in template_df.columns:
            row.setdefault(column, "")
        rows.append(row)
    return pd.DataFrame(rows, columns=template_df.columns)


def rewrite_scan_export(
    scan_file: Path, target_path: Path, barcode_model_map: dict[str, str]
) -> None:
    scan_df = pd.read_excel(scan_file, header=None, dtype=str)
    scan_df.columns = ["原始值"] + [f"_col{i}" for i in range(1, len(scan_df.columns))]
    scan_df["型号"] = scan_df["原始值"].apply(
        lambda value: lookup_model(value, barcode_model_map)
    )
    scan_df.columns = ["条码/库位"] + [
        f"_col{i}" for i in range(1, len(scan_df.columns) - 1)
    ] + ["型号"]
    scan_df.to_excel(target_path, index=False)


def main() -> int:
    if not TEMP_RESULTS_FILE.exists():
        print("ERROR: missing phase2 results")
        return 1

    with TEMP_RESULTS_FILE.open("r", encoding="utf-8") as file:
        results_data = json.load(file)
    TEMP_RESULTS_FILE.unlink()

    results = results_data["results"]
    new_barcodes = results_data["new_barcodes"]
    exceptions = [(barcode, reason) for barcode, reason in results_data["exceptions"]]
    unmatched_barcodes = results_data["unmatched_barcodes"]
    employee_name = results_data["employee_name"]
    scan_files = [Path(path) for path in results_data["scan_files"]]
    barcode_model_map = results_data["barcode_model_map"]
    stockpile_path = Path(results_data["stockpile_path"])

    print(f"EMPLOYEE {employee_name}")
    print(f"RESULT_COUNT {len(results)}")

    template_files = sorted(INPUT_DIR.glob("*模板*.csv"))
    if not template_files:
        print("ERROR: missing template csv")
        return 1

    template_path = template_files[0]
    print(f"TEMPLATE {template_path.name}")

    template_df = read_csv(template_path).iloc[0:0]
    output_df = build_output_dataframe(template_df, results)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    package_name = f"{employee_name}价格标{timestamp}"
    package_dir = OUTPUT_DIR / package_name
    package_dir.mkdir(exist_ok=True)

    output_path = package_dir / template_path.name
    output_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"OUTPUT {output_path}")
    print(f"MATCHED {len(results) - len(new_barcodes)}")
    print(f"NEW {len(new_barcodes)}")
    print(f"UNMATCHED {len(unmatched_barcodes)}")

    for barcode in new_barcodes:
        print(f"[NEW_BARCODE_CONFIRMED] {barcode}")
    for barcode, reason in exceptions:
        print(f"[PHASE3_WARNING] {barcode} {reason}")

    print("Cleaning up input files...")
    trash_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")

    for scan_file in scan_files:
        target_path = package_dir / scan_file.name
        try:
            rewrite_scan_export(scan_file, target_path, barcode_model_map)
        except Exception as exc:
            print(f"COPY_SCAN_FALLBACK {scan_file.name} {exc}")
            shutil.copy2(scan_file, target_path)

        trash_path = TRASH_DIR / f"{scan_file.stem}_{trash_suffix}.xlsx"
        shutil.move(scan_file, trash_path)
        print(f"TRASH_SCAN {trash_path.name}")

    system_trash_path = TRASH_DIR / f"{stockpile_path.stem}_{trash_suffix}.csv"
    shutil.move(stockpile_path, system_trash_path)
    print(f"TRASH_STOCKPILE {system_trash_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
