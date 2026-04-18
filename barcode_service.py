import csv
import json

from output_repository import latest_output_csv
from schemas import ServiceResult
from state import TEMP_MAPPING_FILE, TEMP_RESULTS_FILE, task_state


def correct_barcode(old_barcode: str, new_barcode: str) -> ServiceResult:
    is_waiting = task_state.is_waiting() and task_state.waiting_stage() == "anomaly"

    if is_waiting:
        try:
            with TEMP_MAPPING_FILE.open("r", encoding="utf-8") as file:
                temp = json.load(file)
            if old_barcode not in temp["location_map"]:
                return ServiceResult(ok=False, payload={"msg": f"未找到条码：{old_barcode}"}, status_code=404)
            temp["location_map"][new_barcode] = temp["location_map"].pop(old_barcode)
            with TEMP_MAPPING_FILE.open("w", encoding="utf-8") as file:
                json.dump(temp, file, ensure_ascii=False, indent=2)
        except Exception as exc:
            return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    else:
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


def correct_location(old_location: str, new_location: str) -> ServiceResult:
    try:
        with TEMP_MAPPING_FILE.open("r", encoding="utf-8") as file:
            temp = json.load(file)
        updated = False
        for locations in temp["location_map"].values():
            if old_location in locations:
                locations.remove(old_location)
                if new_location not in locations:
                    locations.append(new_location)
                updated = True
        if not updated:
            return ServiceResult(ok=False, payload={"msg": f"未找到库位：{old_location}"}, status_code=404)
        with TEMP_MAPPING_FILE.open("w", encoding="utf-8") as file:
            json.dump(temp, file, ensure_ascii=False, indent=2)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)

    task_state.update_location_warning(old_location, corrected=True, new_location=new_location)
    return ServiceResult(ok=True)


def delete_barcode(barcode: str) -> ServiceResult:
    is_waiting = task_state.is_waiting() and task_state.waiting_stage() == "anomaly"

    if is_waiting:
        try:
            with TEMP_MAPPING_FILE.open("r", encoding="utf-8") as file:
                temp = json.load(file)
            if barcode not in temp["location_map"]:
                return ServiceResult(ok=False, payload={"msg": f"未找到条码：{barcode}"}, status_code=404)
            del temp["location_map"][barcode]
            with TEMP_MAPPING_FILE.open("w", encoding="utf-8") as file:
                json.dump(temp, file, ensure_ascii=False, indent=2)
        except Exception as exc:
            return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)
    else:
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


def resolve_phase2_exception(barcode: str, resolution: str) -> ServiceResult:
    if not TEMP_RESULTS_FILE.exists():
        return ServiceResult(
            ok=False,
            payload={"msg": "找不到阶段二结果文件，请重新处理"},
            status_code=404,
        )

    try:
        with TEMP_RESULTS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        data["exceptions"] = [[b, r] for b, r in data["exceptions"] if b != barcode]
        if resolution != "ignore":
            model = data.get("barcode_model_map", {}).get(barcode, barcode)
            data["results"].append({"model": model, "location": resolution})
        with TEMP_RESULTS_FILE.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except Exception as exc:
        return ServiceResult(ok=False, payload={"msg": str(exc)}, status_code=500)

    task_state.update_phase2_warning(barcode, resolved=True, resolution=resolution)
    return ServiceResult(ok=True)
