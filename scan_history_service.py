"""扫描历史 service — 浏览 output/{员工}价格标{时间戳}/ 文件夹。

仅文件系统操作，不写 DB、不缓存（51 个 batch 的扫描 < 100ms）。
"""

import re
from pathlib import Path

from config import CONFIG

OUTPUT_DIR = CONFIG.output_dir

_FOLDER_PATTERN = re.compile(r"^(?P<employee>.+?)价格标(?P<timestamp>\d{14})$")


def _parse_folder_name(name: str) -> dict | None:
    """从文件夹名抽员工 + 14 位时间戳。不匹配返回 None。"""
    m = _FOLDER_PATTERN.match(name)
    if not m:
        return None
    return {"employee": m.group("employee"), "timestamp": m.group("timestamp")}


def list_batches(limit: int = 100) -> list[dict]:
    """扫 OUTPUT_DIR，按时间倒序返回最近 limit 个 batch 概览。

    每条 dict 字段：
        batch_id, employee, scanned_at (ISO),
        csv_filename, csv_rows, csv_size_bytes,
        xlsx_files: [{name, size_bytes}]

    员工筛选由前端做（dropdown），服务端不过滤。
    """
    if not OUTPUT_DIR.exists():
        return []

    parsed = []
    for entry in OUTPUT_DIR.iterdir():
        if not entry.is_dir():
            continue
        info = _parse_folder_name(entry.name)
        if info is None:
            continue
        parsed.append((entry, info))

    parsed.sort(key=lambda x: x[1]["timestamp"], reverse=True)
    parsed = parsed[:limit]

    return [_build_batch_dict(entry, info) for entry, info in parsed]


def _build_batch_dict(batch_dir: Path, info: dict) -> dict:
    """组装一条 batch 概览。Task 3 会填 CSV/xlsx 元信息；当前先返回占位。"""
    return {
        "batch_id": batch_dir.name,
        "employee": info["employee"],
        "scanned_at": _format_timestamp(info["timestamp"]),
        "csv_filename": None,
        "csv_rows": None,
        "csv_size_bytes": None,
        "xlsx_files": [],
    }


def _format_timestamp(ts: str) -> str:
    """20260423155137 → 2026-04-23 15:51:37 (ISO-ish)."""
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
