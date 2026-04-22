import json
from datetime import date, datetime
from pathlib import Path

_SUMMARY_DIR = Path(__file__).resolve().parent / "monthly_summary"

_MONTHS_TO_KEEP = 6


def _month_file(month: str) -> Path:
    return _SUMMARY_DIR / f"{month}.json"


def _read_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_record(
    supplier_name: str,
    total_price: float,
    tax: float,
    invoice_date: str,
    month: str,
) -> dict:
    record = {
        "supplier_name": supplier_name,
        "total_price": total_price,
        "tax": tax,
        "total_with_tax": total_price + tax,
        "invoice_date": invoice_date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = _month_file(month)
    records = _read_json(path)
    records.append(record)
    _write_json(path, records)
    return record


def load_records(month: str) -> list[dict]:
    return _read_json(_month_file(month))


def list_months() -> list[str]:
    if not _SUMMARY_DIR.exists():
        return []
    months = [
        f.stem for f in _SUMMARY_DIR.glob("*.json")
        if f.stem[:4].isdigit()
    ]
    months.sort(reverse=True)
    return months


def cleanup_expired(reference_date: date | None = None) -> None:
    ref = reference_date or date.today()
    cutoff_year = ref.year
    cutoff_month = ref.month - _MONTHS_TO_KEEP
    if cutoff_month <= 0:
        cutoff_year -= 1
        cutoff_month += 12
    cutoff = f"{cutoff_year:04d}-{cutoff_month:02d}"
    if not _SUMMARY_DIR.exists():
        return
    for f in _SUMMARY_DIR.glob("*.json"):
        if f.stem < cutoff:
            f.unlink()
