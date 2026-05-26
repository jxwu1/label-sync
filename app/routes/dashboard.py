import shutil
import subprocess
from datetime import datetime

from flask import Blueprint, jsonify
from sqlalchemy import distinct, func, select

from app.models import (
    AttendanceRecord,
    PurchaseOrder,
    PurchaseOrderLine,
    StockpileChange,
    get_session,
)
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

_DQ_KEYS = (
    "whitespace_anomalies",
    "multi_same_kind",
    "flippers",
    "unknown_prefix",
    "duplicate_segments",
    "empty_locations",
    "negative_stock",
)


@bp.get("/api/dashboard")
def dashboard():
    stats = _build_stats()
    dq = _build_dq()
    feed = _build_feed()
    sys_rows = _build_sys(stats)
    total_anomalies = sum(item["count"] for item in dq)

    stats["anomalies"] = f"{total_anomalies:,}" if total_anomalies else "0"
    stats["anomalyDetail"] = f"{len([d for d in dq if d['count'] > 0])} 类"

    return jsonify({"ok": True, "stats": stats, "dq": dq, "sys": sys_rows, "feed": feed})


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
            "lastImportDetail": (
                last_import[11:16] if last_import and len(last_import) > 16 else ""
            ),
        }
    except Exception:
        return {"sku": "—", "inactive": "—", "scans": "—", "lastImport": "—"}


def _build_dq() -> list[dict]:
    try:
        report = dq_service.build_report()
    except Exception:
        return []
    result = []
    for key in _DQ_KEYS:
        section = report.get(key, {})
        count = section.get("count", 0) if isinstance(section, dict) else len(section)
        result.append({"label": _DQ_LABELS.get(key, key), "count": count})
    return result


def _build_feed() -> list[dict]:
    items: list[dict] = []
    try:
        with get_session() as session:
            _feed_imports(session, items)
            _feed_changes(session, items)
            _feed_purchases(session, items)
    except Exception:
        pass
    items.sort(key=lambda x: x.get("_ts", ""), reverse=True)
    return items[:10]


def _feed_imports(session, items: list[dict]) -> None:
    rows = session.execute(
        select(
            StockpileChange.created_at,
            func.count(distinct(StockpileChange.product_barcode)),
        )
        .where(StockpileChange.change_type == "insert")
        .group_by(func.substr(StockpileChange.created_at, 1, 16))
        .order_by(StockpileChange.created_at.desc())
        .limit(5)
    ).all()
    for ts, cnt in rows:
        if not ts:
            continue
        items.append(
            {
                "type": "import",
                "title": f"Stockpile 导入 · <span class='mono'>+{cnt}</span> 条",
                "meta": [f"{cnt} 新增"],
                "time": _format_time(ts),
                "_ts": ts,
            }
        )


def _feed_changes(session, items: list[dict]) -> None:
    rows = session.execute(
        select(
            StockpileChange.created_at,
            func.count(StockpileChange.id),
        )
        .where(StockpileChange.change_type == "update")
        .group_by(func.substr(StockpileChange.created_at, 1, 16))
        .order_by(StockpileChange.created_at.desc())
        .limit(5)
    ).all()
    for ts, cnt in rows:
        if not ts:
            continue
        items.append(
            {
                "type": "change",
                "title": f"数据变更 · <span class='mono'>{cnt}</span> 条",
                "meta": [f"{cnt} 字段变更"],
                "time": _format_time(ts),
                "_ts": ts,
            }
        )


def _feed_purchases(session, items: list[dict]) -> None:
    orders = (
        session.execute(select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()).limit(5))
        .scalars()
        .all()
    )
    for po in orders:
        ts = po.created_at or po.order_date
        line_count = (
            session.execute(
                select(func.count(PurchaseOrderLine.id)).where(PurchaseOrderLine.order_id == po.id)
            ).scalar()
            or 0
        )
        meta = [f"{line_count} 行"]
        if po.total_amount:
            meta.append(f"€{po.total_amount:,.0f}")
        items.append(
            {
                "type": "import",
                "title": f"采购导入 · <span class='mono'>{po.source_file or po.order_date}</span>",
                "meta": meta,
                "time": _format_time(ts),
                "_ts": ts or "",
            }
        )


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

    try:
        usage = shutil.disk_usage("/data")
        used_gb = usage.used / (1024**3)
        total_gb = usage.total / (1024**3)
        rows.append(
            {
                "status": "ok" if used_gb / total_gb < 0.85 else "warn",
                "label": "磁盘",
                "value": f"{used_gb:.1f} / {total_gb:.0f} GB",
            }
        )
    except Exception:
        pass

    try:
        month = datetime.now().strftime("%Y-%m")
        with get_session() as session:
            emp_count = (
                session.execute(
                    select(func.count(distinct(AttendanceRecord.employee_id))).where(
                        AttendanceRecord.work_date.like(f"{month}%")
                    )
                ).scalar()
                or 0
            )
        if emp_count:
            rows.append({"status": "ok", "label": "考勤", "value": f"{month} · {emp_count}人"})
    except Exception:
        pass

    try:
        rev = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        commit = rev.stdout.strip() if rev.returncode == 0 else "unknown"
        rows.append({"status": "ok", "label": "版本", "value": f"v4.8 · {commit}"})
    except Exception:
        rows.append({"status": "ok", "label": "版本", "value": "v4.8"})

    return rows


def _format_time(ts: str | None) -> str:
    if not ts:
        return "—"
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (
        datetime.now()
        .replace(day=datetime.now().day - 1 if datetime.now().day > 1 else 1)
        .strftime("%Y-%m-%d")
    )
    date_part = ts[:10]
    time_part = ts[11:16] if len(ts) > 15 else ""
    if date_part == today:
        return time_part or "今天"
    if date_part == yesterday:
        return "昨天"
    return date_part[5:]
