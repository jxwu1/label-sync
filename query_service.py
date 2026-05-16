import csv
import logging
from pathlib import Path

import pandas as pd

from app.repositories.input import list_input_files
from app.repositories.output import (
    iter_output_items,
    latest_output_csv,
    list_output_xlsx_files,
)
from app.state import task_state


def _file_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size": round(stat.st_size / 1024, 1),
        "mtime": stat.st_mtime,
    }


def read_barcode_list() -> dict:
    xlsx_files = list_output_xlsx_files()
    if not xlsx_files:
        return {"ok": False, "msg": "找不到扫描文件"}

    all_barcodes: list[str] = []
    all_models: list[str] = []
    for xlsx_path in xlsx_files:
        try:
            dataframe = pd.read_excel(xlsx_path, dtype=str, engine="calamine")
        except Exception as exc:
            logging.warning("Skipping invalid Excel file %s: %s", xlsx_path.name, exc)
            continue

        if "条码/库位" not in dataframe.columns:
            continue

        for _, row in dataframe.iterrows():
            value = str(row["条码/库位"]).strip() if pd.notna(row["条码/库位"]) else ""
            if value and not value[:1].isalpha():
                all_barcodes.append(value)
                model = str(row.get("型号", "")).strip() if "型号" in dataframe.columns else ""
                all_models.append("" if model == "nan" else model)

    return {"ok": True, "barcodes": all_barcodes, "models": all_models}


def read_model_list() -> dict:
    csv_path = latest_output_csv()
    if csv_path is None:
        return {"ok": False, "msg": "找不到输出 CSV 文件"}

    try:
        with csv_path.open("r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            model_list = [row["型号"].strip() for row in reader if row.get("型号", "").strip()]
    except Exception as exc:
        return {"ok": False, "msg": str(exc)}

    return {"ok": True, "models": model_list}


def read_file_list() -> dict:
    input_files = []
    for path in list_input_files():
        if path.name == "README.md":
            continue
        try:
            input_files.append(_file_info(path))
        except OSError:
            pass

    output_items = []
    for path in iter_output_items():
        if path.name.startswith(".") or path.name == "README.md":
            continue
        try:
            stat = path.stat()
            output_items.append(
                {
                    "name": path.name,
                    "is_dir": path.is_dir(),
                    "is_zip": path.suffix.lower() == ".zip",
                    "size": round(stat.st_size / 1024, 1),
                    "mtime": stat.st_mtime,
                }
            )
        except OSError:
            pass

    snapshot = task_state.snapshot()
    status_data = {
        "running": snapshot.running,
        "log": snapshot.log,
        "done": not snapshot.running and snapshot.result_zip is not None,
        "error": snapshot.error,
    }

    return {"input": input_files, "output": output_items, "status": status_data}
