import shutil
import subprocess
from datetime import datetime

from flask import Blueprint, jsonify
from sqlalchemy import func, select

from app.models import (
    AttendanceRecord,
    BacktestRun,
    PurchaseOrder,
    PurchaseOrderLine,
    StockpileChange,
    StockpileSnapshot,
    get_session,
)
from app.repositories import stockpile_db
from app.services import data_quality as dq_service
from app.services import scan_history as scan_history_service

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

        scans_total, scan_batches = _count_monthly_scans()

        return {
            "sku": f"{active:,}",
            "inactive": f"{inactive:,}",
            "scans": f"{scans_total:,}" if scans_total else "0",
            "scanBatches": f"{scan_batches} 批次" if scan_batches else "",
            "lastImport": last_import[:10] if last_import else "—",
            "lastImportDetail": (
                last_import[11:16] if last_import and len(last_import) > 16 else ""
            ),
        }
    except Exception:
        return {"sku": "—", "inactive": "—", "scans": "—", "lastImport": "—"}


def _count_monthly_scans() -> tuple[int, int]:
    """Return (total_csv_rows, batch_count) for the current month."""
    try:
        month_prefix = datetime.now().strftime("%Y-%m")
        batches = scan_history_service.list_batches()
        monthly = [b for b in batches if b["scanned_at"][:7] == month_prefix]
        total_rows = sum(b.get("csv_rows") or 0 for b in monthly)
        return total_rows, len(monthly)
    except Exception:
        return 0, 0


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
    for fn in (_feed_snapshots, _feed_changes, _feed_purchases, _feed_scans):
        try:
            fn(items)
        except Exception:
            pass
    items.sort(key=lambda x: x.get("_ts", ""), reverse=True)
    return items[:10]


def _feed_snapshots(items: list[dict]) -> None:
    with get_session() as session:
        for snap in (
            session.execute(
                select(StockpileSnapshot).order_by(StockpileSnapshot.taken_at.desc()).limit(5)
            )
            .scalars()
            .all()
        ):
            label = "Stockpile 导入" if snap.trigger == "import" else "Stockpile 比对"
            meta = [f"{snap.total_local:,} 记录"]
            if snap.only_in_local_count:
                meta.append(f"+{snap.only_in_local_count} 新增")
            if snap.substantive_count:
                meta.append(f"{snap.substantive_count} 变更")
            items.append(
                {
                    "type": "import",
                    "title": f"{label} · 批次 <span class='mono'>#{snap.id}</span>",
                    "meta": meta,
                    "time": _format_time(snap.taken_at),
                    "_ts": snap.taken_at,
                }
            )


def _feed_changes(items: list[dict]) -> None:
    with get_session() as session:
        for day, cnt in session.execute(
            select(
                func.substr(StockpileChange.created_at, 1, 10).label("day"),
                func.count(StockpileChange.id),
            )
            .where(StockpileChange.change_type == "update")
            .group_by("day")
            .order_by(func.substr(StockpileChange.created_at, 1, 10).desc())
            .limit(3)
        ).all():
            if not day or cnt == 0:
                continue
            items.append(
                {
                    "type": "change",
                    "title": f"数据变更 · <span class='mono'>{cnt}</span> 条",
                    "meta": [f"{cnt} 字段变更"],
                    "time": _format_time(day),
                    "_ts": day,
                }
            )


def _feed_purchases(items: list[dict]) -> None:
    with get_session() as session:
        for po in (
            session.execute(
                select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()).limit(5)
            )
            .scalars()
            .all()
        ):
            ts = po.created_at or po.order_date or ""
            line_count = (
                session.execute(
                    select(func.count(PurchaseOrderLine.id)).where(
                        PurchaseOrderLine.order_id == po.id
                    )
                ).scalar()
                or 0
            )
            meta = [f"{line_count} 行"]
            if po.total_amount:
                meta.append(f"€{po.total_amount:,.0f}")
            src = po.source_file or po.order_date
            items.append(
                {
                    "type": "import",
                    "title": f"采购导入 · <span class='mono'>{src}</span>",
                    "meta": meta,
                    "time": _format_time(ts),
                    "_ts": ts,
                }
            )


def _feed_scans(items: list[dict]) -> None:
    try:
        batches = scan_history_service.list_batches(limit=10)
    except Exception:
        return
    for b in batches:
        rows = b.get("csv_rows") or 0
        meta = [f"{rows} 条码"] if rows else []
        items.append(
            {
                "type": "scan",
                "title": f"<span class='hl'>{b['employee']}</span> · 价格标扫描完成",
                "meta": meta,
                "time": _format_time(b["scanned_at"]),
                "_ts": b["scanned_at"],
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
                    select(func.count(AttendanceRecord.employee_id.distinct())).where(
                        AttendanceRecord.work_date.like(f"{month}%")
                    )
                ).scalar()
                or 0
            )
        rows.append(
            {
                "status": "ok" if emp_count else "warn",
                "label": "考勤",
                "value": f"{month} · {emp_count}人" if emp_count else f"{month} · 无数据",
            }
        )
    except Exception:
        rows.append({"status": "warn", "label": "考勤", "value": "—"})

    try:
        with get_session() as session:
            latest_run = (
                session.execute(
                    select(BacktestRun).order_by(BacktestRun.id.desc()).limit(1)
                )
                .scalar()
            )
        if latest_run:
            scored = latest_run.n_skus_scored
            total = latest_run.n_skus_total
            if total and scored < total:
                pct = int(scored / total * 100)
                rows.append({"status": "running", "label": "Backtest", "value": f"运行中 {pct}%"})
            else:
                ts = (latest_run.created_at or "")[:10]
                rows.append({"status": "ok", "label": "Backtest", "value": f"{latest_run.model_name} · {ts}"})
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
