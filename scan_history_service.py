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


# 历史上模板叫 "1产品信息导入模板.csv"，后来改成 "产品信息导入模板.csv"。
# 旧文件夹保留旧名，新文件夹用新名。检测时按顺序找第一个存在的。
_CSV_FILENAME_CANDIDATES = (
    "产品信息导入模板.csv",
    "1产品信息导入模板.csv",
)


def _find_csv_in_batch(batch_dir: Path) -> Path | None:
    for name in _CSV_FILENAME_CANDIDATES:
        p = batch_dir / name
        if p.exists() and p.is_file():
            return p
    return None


def _build_batch_dict(batch_dir: Path, info: dict) -> dict:
    """组装一条 batch 概览。CSV 缺失或不可读时 csv_* 字段为 None。"""
    csv_path = _find_csv_in_batch(batch_dir)
    csv_filename: str | None = None
    csv_rows: int | None = None
    csv_size_bytes: int | None = None
    if csv_path is not None:
        csv_filename = csv_path.name
        try:
            csv_size_bytes = csv_path.stat().st_size
            csv_rows = _count_csv_rows(csv_path)
        except OSError:
            csv_size_bytes = None
            csv_rows = None

    xlsx_files: list[dict] = []
    for entry in batch_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".xlsx":
            try:
                xlsx_files.append(
                    {
                        "name": entry.name,
                        "size_bytes": entry.stat().st_size,
                    }
                )
            except OSError:
                continue
    xlsx_files.sort(key=lambda f: f["name"])

    return {
        "batch_id": batch_dir.name,
        "employee": info["employee"],
        "scanned_at": _format_timestamp(info["timestamp"]),
        "csv_filename": csv_filename,
        "csv_rows": csv_rows,
        "csv_size_bytes": csv_size_bytes,
        "xlsx_files": xlsx_files,
    }


def _format_timestamp(ts: str) -> str:
    """20260423155137 → 2026-04-23 15:51:37 (ISO-ish)."""
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"


def _count_csv_rows(csv_path: Path) -> int:
    """数 CSV 数据行（不含 header）。空文件返回 0。"""
    with csv_path.open("r", encoding="utf-8-sig") as f:
        line_count = sum(1 for _ in f)
    return max(0, line_count - 1)


def list_employees() -> list[str]:
    """从现有 batch 中抽出 unique 员工名，按字母序。"""
    if not OUTPUT_DIR.exists():
        return []
    seen = set()
    for entry in OUTPUT_DIR.iterdir():
        if not entry.is_dir():
            continue
        info = _parse_folder_name(entry.name)
        if info:
            seen.add(info["employee"])
    return sorted(seen)


def get_batch_csv_path(batch_id: str) -> Path | None:
    """返回 batch 内主 CSV 的 Path；不存在/不安全返回 None。

    兼容新旧两种文件名（见 _CSV_FILENAME_CANDIDATES）。
    """
    batch_dir = _safe_resolve_batch(batch_id)
    if batch_dir is None:
        return None
    return _find_csv_in_batch(batch_dir)


def _safe_resolve_batch(batch_id: str) -> Path | None:
    """把 batch_id 解析为绝对路径，确认在 OUTPUT_DIR 下且匹配命名规则。"""
    if _parse_folder_name(batch_id) is None:
        return None
    candidate = (OUTPUT_DIR / batch_id).resolve()
    try:
        if not candidate.is_relative_to(OUTPUT_DIR.resolve()):
            return None
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_dir():
        return None
    return candidate


def get_batch_xlsx_path(batch_id: str, filename: str) -> Path | None:
    """返回指定 xlsx 文件 Path；越界/不存在/非 xlsx 后缀返回 None。"""
    batch_dir = _safe_resolve_batch(batch_id)
    if batch_dir is None:
        return None

    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    if not filename.lower().endswith(".xlsx"):
        return None

    candidate = (batch_dir / filename).resolve()
    try:
        if not candidate.is_relative_to(batch_dir):
            return None
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate
