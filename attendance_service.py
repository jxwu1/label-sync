"""考勤服务：员工 CRUD、月度 CRUD、summary 计算。"""

import json
from datetime import datetime
from pathlib import Path

_ATTENDANCE_DIR = Path(__file__).resolve().parent / "attendance"
_EMPLOYEES_FILE = "employees.json"
_METADATA_FILE = "metadata.json"


def _employees_path() -> Path:
    return _ATTENDANCE_DIR / _EMPLOYEES_FILE


def _metadata_path() -> Path:
    return _ATTENDANCE_DIR / _METADATA_FILE


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_employees() -> list[dict]:
    return _read_json(_employees_path(), [])


def _next_employee_id() -> str:
    metadata = _read_json(_metadata_path(), {"next_id_num": 0})
    next_num = metadata.get("next_id_num", 0) + 1
    metadata["next_id_num"] = next_num
    _write_json(_metadata_path(), metadata)
    return f"e{next_num:03d}"


def create_employee(name: str) -> dict:
    employees = list_employees()
    emp = {
        "id": _next_employee_id(),
        "name": name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    employees.append(emp)
    _write_json(_employees_path(), employees)
    return emp


def delete_employee(employee_id: str) -> None:
    employees = [e for e in list_employees() if e["id"] != employee_id]
    _write_json(_employees_path(), employees)


STANDARD_HOURS = 10.5


def _parse_hm(hm: str) -> int:
    """HH:MM -> 分钟总数"""
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def day_fraction(start: str, end: str) -> float:
    """计算工作日占比（纯函数）。

    Args:
        start: 上班时间，格式 "HH:MM"
        end: 下班时间，格式 "HH:MM"

    Returns:
        [0.0, 1.0] 范围内的占比，超过标准工作时间（10.5h）封顶为 1.0

    Raises:
        ValueError: 若 end <= start
    """
    start_min = _parse_hm(start)
    end_min = _parse_hm(end)
    if end_min <= start_min:
        raise ValueError(f"下班时间必须晚于上班时间：start={start} end={end}")
    hours = (end_min - start_min) / 60
    return min(hours / STANDARD_HOURS, 1.0)


def _month_path(month: str) -> Path:
    return _ATTENDANCE_DIR / f"{month}.json"


def load_month(month: str) -> dict:
    return _read_json(_month_path(month), {})


def set_day(employee_id: str, date: str, times: dict) -> None:
    month = date[:7]
    data = load_month(month)
    data.setdefault(employee_id, {})[date] = {
        "start": times["start"],
        "end": times["end"],
    }
    _write_json(_month_path(month), data)


def clear_day(employee_id: str, date: str) -> None:
    month = date[:7]
    data = load_month(month)
    if employee_id in data and date in data[employee_id]:
        del data[employee_id][date]
        if not data[employee_id]:
            del data[employee_id]
        _write_json(_month_path(month), data)
