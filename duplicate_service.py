import os
import tempfile
from pathlib import Path

from check_duplicates import check_duplicates


def check_duplicate_file(uploaded_file) -> dict:
    ext = Path(uploaded_file.filename).suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        return {"ok": False, "msg": "仅支持 .xlsx / .xls / .csv"}

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
        uploaded_file.save(tmp_file.name)
        temp_path = tmp_file.name

    try:
        return check_duplicates(temp_path)
    except Exception as exc:
        return {"ok": False, "msg": str(exc)}
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
