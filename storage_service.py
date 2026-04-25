import re
import zipfile
from datetime import datetime
from pathlib import Path

from file_io import find_latest_stockpile_file
from output_repository import latest_output_dir
from path_safety import safe_filename
from schemas import ServiceResult
from state import INPUT_DIR, OUTPUT_DIR, TRANSFER_DIR, task_state
from transfer_repository import iter_transfer_items, transfer_file_path


def startup_cleanup() -> None:
    """Clear transient inputs and transfer files while keeping output history."""
    for folder in (INPUT_DIR, TRANSFER_DIR):
        for path in folder.iterdir():
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass

    for path in OUTPUT_DIR.iterdir():
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                path.unlink()
            except OSError:
                pass


def save_uploaded_files(files, target_dir: Path) -> list[str]:
    saved = []
    for file_storage in files:
        if not file_storage.filename:
            continue
        filename = safe_filename(file_storage.filename)
        if "stockpile" in filename.lower() and filename.lower().endswith(".csv"):
            for old_stockpile in INPUT_DIR.glob("*stockpile*.csv"):
                try:
                    old_stockpile.unlink()
                except OSError:
                    pass
        file_storage.save(target_dir / filename)
        saved.append(filename)
    return saved


def find_stockpile_file() -> Path | None:
    return find_latest_stockpile_file(INPUT_DIR)


def parse_date_from_filename(filename: str) -> datetime | None:
    patterns = [
        r"(20\d{2}-\d{2}-\d{2})",
        r"(20\d{2}_\d{2}_\d{2})",
        r"(20\d{6})",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if not match:
            continue
        raw = match.group(1)
        for fmt in ("%Y-%m-%d", "%Y_%m_%d", "%Y%m%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def validate_stockpile_is_today() -> tuple[bool, str | None]:
    stockpile_path = find_stockpile_file()
    if stockpile_path is None:
        return False, "未找到系统导出文件，请先上传当天的 stockpile CSV"

    extracted_date = parse_date_from_filename(stockpile_path.name)
    source_label = "文件名"
    if extracted_date is None:
        extracted_date = datetime.fromtimestamp(stockpile_path.stat().st_mtime)
        source_label = "文件修改时间"

    export_date = extracted_date.date()
    today = datetime.now().date()
    if export_date != today:
        return (
            False,
            f"系统导出文件不是当天的。当前文件日期为 {export_date.isoformat()}（按{source_label}判断），今天是 {today.isoformat()}，请提供当天的 stockpile 文件。",
        )

    return True, None


def validate_stockpile_is_ready() -> tuple[bool, str | None]:
    from stockpile_db import is_initialized

    if not is_initialized():
        return False, 'stockpile 数据库尚未初始化，请先通过"初始化 stockpile 数据库"上传系统导出文件'
    return True, None


def package_latest_output() -> None:
    latest_dir = latest_output_dir()
    if latest_dir is None:
        return

    zip_path = latest_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for path in latest_dir.iterdir():
            if path.is_file():
                zip_file.write(path, path.name)

    task_state.set_result_zip(str(zip_path))


def current_result_path() -> str | None:
    return task_state.snapshot().result_zip


def list_transfer_files() -> list[dict]:
    items = []
    for path in iter_transfer_items():
        if path.name.startswith("."):
            continue
        try:
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "size": round(stat.st_size / 1024, 1),
                    "mtime": stat.st_mtime,
                }
            )
        except OSError:
            pass
    return items


def delete_transfer_file(filename: str) -> ServiceResult:
    file_path = transfer_file_path(filename)
    if not file_path.exists():
        return ServiceResult(ok=False, payload={"msg": "文件不存在"}, status_code=404)
    file_path.unlink()
    return ServiceResult(ok=True)
