import csv
from pathlib import Path

from file_io import update_json_file
from output_repository import latest_output_csv
from schemas import ServiceResult
from state import TEMP_MAPPING_FILE, TEMP_RESULTS_FILE, task_state


def _correct_in_phase1_mapping(old_barcode: str, new_barcode: str) -> ServiceResult:
    def _modifier(temp: dict) -> None:
        if old_barcode not in temp["location_map"]:
            raise KeyError(f"未找到条码：{old_barcode}")
        temp["location_map"][new_barcode] = temp["location_map"].pop(old_barcode)

    try:
        update_json_file(TEMP_MAPPING_FILE, _modifier)
    except KeyError:
        return ServiceResult(ok=False, payload={"msg": f"未找到条码：{old_barcode}"}, status_code=404)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    task_state.update_barcode_warning(old_barcode, corrected=True, new_barcode=new_barcode)
    return ServiceResult(ok=True)


def _correct_in_output_csv(old_barcode: str, new_barcode: str) -> ServiceResult:
    csv_path = latest_output_csv()
    if csv_path is None:
        return ServiceResult(ok=False, payload={"msg": "找不到输出 CSV 文件"}, status_code=404)
    try:
        content = csv_path.read_text(encoding="utf-8-sig")
        if old_barcode not in content:
            return ServiceResult(
                ok=False,
                payload={"msg": f"未在输出文件中找到条码：{old_barcode}"},
                status_code=404,
            )
        csv_path.write_text(content.replace(old_barcode, new_barcode), encoding="utf-8-sig")
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    task_state.update_barcode_warning(old_barcode, corrected=True, new_barcode=new_barcode)
    return ServiceResult(ok=True)


def _load_stockpile_records(stockpile_path: str) -> dict[str, dict[str, str]]:
    from update_location_phase2 import build_system_records, read_csv
    _, records = build_system_records(read_csv(Path(stockpile_path)))
    return records


def _correct_new_barcode(old_barcode: str, new_barcode: str) -> ServiceResult:
    from update_location_phase2 import compose_location, parse_system_location

    if not TEMP_RESULTS_FILE.exists():
        return ServiceResult(ok=False, payload={"msg": "找不到阶段二结果文件"}, status_code=404)

    mismatch = None

    def _modifier(data: dict) -> None:
        nonlocal mismatch
        new_list: list[str] = data.get("new_barcodes", [])
        if old_barcode not in new_list:
            mismatch = f"未找到新条码：{old_barcode}"
            return

        entry_idx = next(
            (i for i, r in enumerate(data["results"]) if r.get("model") == old_barcode),
            None,
        )

        records = _load_stockpile_records(data["stockpile_path"])
        barcode_model_map: dict[str, str] = data.setdefault("barcode_model_map", {})

        if new_barcode in records:
            system_item = records[new_barcode]
            old_store, old_warehouse, system_issue = parse_system_location(system_item["stockpile_location"])
            if system_issue:
                mismatch = f"stockpile 库位异常：{system_issue}"
                return
            scan_store, scan_warehouse, _ = parse_system_location(
                data["results"][entry_idx]["location"] if entry_idx is not None else ""
            )
            final_location = compose_location(old_store, old_warehouse, scan_store, scan_warehouse)
            if not final_location:
                mismatch = "合成最终库位失败"
                return
            if entry_idx is not None:
                data["results"][entry_idx] = {"model": system_item["model"], "location": final_location}
            new_list.remove(old_barcode)
            barcode_model_map.pop(old_barcode, None)
            barcode_model_map[new_barcode] = system_item["model"]
            task_state.remove_new_barcode(old_barcode)
        else:
            if entry_idx is not None:
                data["results"][entry_idx]["model"] = new_barcode
            new_list[new_list.index(old_barcode)] = new_barcode
            barcode_model_map.pop(old_barcode, None)
            barcode_model_map[new_barcode] = new_barcode
            task_state.replace_new_barcode(old_barcode, new_barcode)

        data["new_barcodes"] = new_list

    try:
        update_json_file(TEMP_RESULTS_FILE, _modifier)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    if mismatch:
        status = 400 if "库位" in mismatch else 404
        return ServiceResult(ok=False, payload={"msg": mismatch}, status_code=status)
    return ServiceResult(ok=True)


def correct_barcode(old_barcode: str, new_barcode: str) -> ServiceResult:
    stage = task_state.waiting_stage() if task_state.is_waiting() else None
    if stage == "anomaly":
        return _correct_in_phase1_mapping(old_barcode, new_barcode)
    if stage == "phase2_review":
        return _correct_new_barcode(old_barcode, new_barcode)
    return _correct_in_output_csv(old_barcode, new_barcode)


def correct_location(old_location: str, new_location: str) -> ServiceResult:
    updated = False

    def _modifier(temp: dict) -> None:
        nonlocal updated
        for locations in temp["location_map"].values():
            if old_location in locations:
                locations.remove(old_location)
                if new_location not in locations:
                    locations.append(new_location)
                updated = True

    try:
        update_json_file(TEMP_MAPPING_FILE, _modifier)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    if not updated:
        return ServiceResult(ok=False, payload={"msg": f"未找到库位：{old_location}"}, status_code=404)

    task_state.update_location_warning(old_location, corrected=True, new_location=new_location)
    return ServiceResult(ok=True)


def _delete_in_phase1_mapping(barcode: str) -> ServiceResult:
    def _modifier(temp: dict) -> None:
        if barcode not in temp["location_map"]:
            raise KeyError(f"未找到条码：{barcode}")
        del temp["location_map"][barcode]

    try:
        update_json_file(TEMP_MAPPING_FILE, _modifier)
    except KeyError:
        return ServiceResult(ok=False, payload={"msg": f"未找到条码：{barcode}"}, status_code=404)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    task_state.update_barcode_warning(barcode, deleted=True)
    return ServiceResult(ok=True)


def _delete_in_output_csv(barcode: str) -> ServiceResult:
    csv_path = latest_output_csv()
    if csv_path is None:
        return ServiceResult(ok=False, payload={"msg": "找不到输出 CSV 文件"}, status_code=404)
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))
        if not rows:
            return ServiceResult(ok=False, payload={"msg": "输出 CSV 为空"}, status_code=400)
        filtered_rows = [rows[0]] + [
            row for row in rows[1:] if not (row and row[0].strip() == barcode)
        ]
        if len(filtered_rows) == len(rows):
            return ServiceResult(
                ok=False,
                payload={"msg": f"未在输出文件中找到条码：{barcode}"},
                status_code=404,
            )
        with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
            csv.writer(file).writerows(filtered_rows)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    task_state.update_barcode_warning(barcode, deleted=True)
    return ServiceResult(ok=True)


def _delete_new_barcode(barcode: str) -> ServiceResult:
    if not TEMP_RESULTS_FILE.exists():
        return ServiceResult(ok=False, payload={"msg": "找不到阶段二结果文件"}, status_code=404)

    not_found = None

    def _modifier(data: dict) -> None:
        nonlocal not_found
        new_list: list[str] = data.get("new_barcodes", [])
        if barcode not in new_list:
            not_found = f"未找到新条码：{barcode}"
            return
        data["results"] = [r for r in data["results"] if r.get("model") != barcode]
        new_list.remove(barcode)
        data["new_barcodes"] = new_list
        data.get("barcode_model_map", {}).pop(barcode, None)

    try:
        update_json_file(TEMP_RESULTS_FILE, _modifier)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    if not_found:
        return ServiceResult(ok=False, payload={"msg": not_found}, status_code=404)
    task_state.remove_new_barcode(barcode)
    return ServiceResult(ok=True)


def delete_barcode(barcode: str) -> ServiceResult:
    stage = task_state.waiting_stage() if task_state.is_waiting() else None
    if stage == "anomaly":
        return _delete_in_phase1_mapping(barcode)
    if stage == "phase2_review":
        return _delete_new_barcode(barcode)
    return _delete_in_output_csv(barcode)


def resolve_phase2_exception(barcode: str, resolution: str) -> ServiceResult:
    if not TEMP_RESULTS_FILE.exists():
        return ServiceResult(
            ok=False,
            payload={"msg": "找不到阶段二结果文件，请重新处理"},
            status_code=404,
        )

    def _modifier(data: dict) -> None:
        data["exceptions"] = [exc for exc in data["exceptions"] if exc[0] != barcode]
        if resolution != "ignore":
            model = data.get("barcode_model_map", {}).get(barcode, barcode)
            data["results"].append({"model": model, "location": resolution})

    try:
        update_json_file(TEMP_RESULTS_FILE, _modifier)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)

    task_state.update_phase2_warning(barcode, resolved=True, resolution=resolution)
    return ServiceResult(ok=True)
