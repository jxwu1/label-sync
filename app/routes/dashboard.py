from flask import Blueprint, jsonify

from app.repositories import stockpile_db
from app.services import data_quality as dq_service

bp = Blueprint("dashboard", __name__)

_DQ_LABELS = {
    "whitespace_anomalies": "空白异常",
    "unknown_prefix": "未知前缀",
    "duplicate_segments": "重复片段",
    "empty_locations": "空库位",
    "negative_stock": "负库存",
    "multi_same_kind": "同类多条",
    "flippers": "翻转记录",
}


@bp.get("/api/dashboard")
def dashboard():
    stats = _build_stats()
    dq = _build_dq()
    sys_rows = _build_sys(stats)
    total_anomalies = sum(item["count"] for item in dq)

    stats["anomalies"] = f"{total_anomalies:,}" if total_anomalies else "0"
    stats["anomalyDetail"] = f"{len([d for d in dq if d['count'] > 0])} 类"

    return jsonify(
        {"ok": True, "stats": stats, "dq": dq, "sys": sys_rows, "feed": [], "task": None}
    )


def _build_stats() -> dict:
    try:
        if not stockpile_db.is_initialized():
            return {"sku": "—", "inactive": "—", "scans": "—", "lastImport": "—"}
        active = stockpile_db.count_records()
        inactive = stockpile_db.count_inactive_records()
        last_import = stockpile_db.last_import_at()
        return {
            "sku": f"{active:,}",
            "inactive": f"{inactive:,}",
            "scans": "—",
            "lastImport": last_import[:10] if last_import else "—",
            "lastImportDetail": last_import[11:16] if last_import and len(last_import) > 16 else "",
        }
    except Exception:
        return {"sku": "—", "inactive": "—", "scans": "—", "lastImport": "—"}


def _build_dq() -> list[dict]:
    try:
        report = dq_service.build_report()
    except Exception:
        return []
    result = []
    for key in (
        "whitespace_anomalies",
        "multi_same_kind",
        "flippers",
        "unknown_prefix",
        "duplicate_segments",
        "empty_locations",
        "negative_stock",
    ):
        items = report.get(key, [])
        result.append({"label": _DQ_LABELS.get(key, key), "count": len(items)})
    return result


def _build_sys(stats: dict) -> list[dict]:
    rows = []
    try:
        initialized = stockpile_db.is_initialized()
        active = stockpile_db.count_records() if initialized else 0
        rows.append(
            {
                "status": "ok" if initialized else "warn",
                "label": "Stockpile DB",
                "value": f"{active:,} active" if initialized else "未初始化",
            }
        )
    except Exception:
        rows.append({"status": "warn", "label": "Stockpile DB", "value": "错误"})

    last_import = stats.get("lastImport", "—")
    detail = stats.get("lastImportDetail", "")
    rows.append(
        {
            "status": "ok" if last_import != "—" else "warn",
            "label": "上次导入",
            "value": f"{last_import} {detail}".strip(),
        }
    )

    return rows
