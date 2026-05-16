# recent_changes_service.py
"""货号历史 - 最近改动 service。

按 stockpile_snapshots(trigger='import') 切批次，关联到落在
窗口 (prev_taken_at, current_taken_at] 内的 stockpile_changes。
"""

from typing import Literal

from sqlalchemy import and_, func, select

from app.repositories import stockpile_db
from models import Stockpile, StockpileChange, StockpileSnapshot

_RECENT_IMPORTS_LIMIT = 10
_EPOCH = "1970-01-01 00:00:00"
_FAR_FUTURE = "9999-12-31 23:59:59"

# 「开放批次」：上次 import snapshot 之后到现在的零散改动（标签修改 / 单条
# 库位改 / 任何走 _log_change 的写入）。它没有正式 snapshot 关闭窗口，所以
# 在不引入这个虚拟 batch 之前，这些改动会从最近改动 tab 完全消失。
_OPEN_BATCH_ID = -1


def _last_import_taken_at(session) -> str | None:
    return session.execute(
        select(StockpileSnapshot.taken_at)
        .where(StockpileSnapshot.trigger == "import")
        .order_by(StockpileSnapshot.taken_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _batch_window(session, batch_id: int) -> tuple[str, str]:
    """返回 (window_start, window_end) 字符串。

    window_end = snapshot[batch_id].taken_at
    window_start = 上一个 trigger='import' snapshot 的 taken_at；不存在时取 _EPOCH

    特殊 batch_id == _OPEN_BATCH_ID（-1）：开放批次，
        window_start = 最近一次 import snapshot 之后
        window_end   = _FAR_FUTURE（永远把"现在以后写入的"也算上）
    """
    if batch_id == _OPEN_BATCH_ID:
        last = _last_import_taken_at(session)
        return (last or _EPOCH, _FAR_FUTURE)

    current = session.execute(
        select(StockpileSnapshot.taken_at).where(StockpileSnapshot.id == batch_id)
    ).scalar_one()

    prev = session.execute(
        select(StockpileSnapshot.taken_at)
        .where(
            and_(
                StockpileSnapshot.trigger == "import",
                StockpileSnapshot.taken_at < current,
            )
        )
        .order_by(StockpileSnapshot.taken_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    return (prev or _EPOCH, current)


def list_recent_imports(limit: int = _RECENT_IMPORTS_LIMIT) -> list[dict]:
    """返回最近 N 次 import snapshot 概览，最前面可能含一个"开放批次"。

    每条 dict 字段：batch_id / taken_at / total_local / change_count / affected_barcodes
                  / is_open（仅开放批次为 True）

    开放批次：上次 import snapshot 之后的零散变更（标签修改 / 单条修正等
    都走 _log_change 写 stockpile_changes 但没新 snapshot 闭合窗口，旧逻辑
    下完全看不到）。
    """
    with stockpile_db._session() as session:
        result: list[dict] = []

        # === 开放批次：仅当上次 import 之后有 changes 才显示 ===
        last_at = _last_import_taken_at(session) or _EPOCH
        open_stats = session.execute(
            select(
                func.count().label("n"),
                func.count(func.distinct(StockpileChange.product_barcode)).label("bc"),
                func.max(StockpileChange.created_at).label("max_at"),
            ).where(StockpileChange.created_at > last_at)
        ).one()
        if open_stats.n:
            result.append(
                {
                    "batch_id": _OPEN_BATCH_ID,
                    "taken_at": open_stats.max_at,  # 用最后一条 change 时间
                    "total_local": None,
                    "change_count": open_stats.n,
                    "affected_barcodes": open_stats.bc,
                    "is_open": True,
                }
            )

        # === 已闭合的 import 批次（按 id desc，最新在前） ===
        snapshots = (
            session.execute(
                select(StockpileSnapshot)
                .where(StockpileSnapshot.trigger == "import")
                .order_by(StockpileSnapshot.id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

        for snap in snapshots:
            start, end = _batch_window(session, snap.id)
            stats = session.execute(
                select(
                    func.count().label("n"),
                    func.count(func.distinct(StockpileChange.product_barcode)).label("bc"),
                ).where(
                    and_(
                        StockpileChange.created_at > start,
                        StockpileChange.created_at <= end,
                    )
                )
            ).one()
            result.append(
                {
                    "batch_id": snap.id,
                    "taken_at": snap.taken_at,
                    "total_local": snap.total_local,
                    "change_count": stats.n,
                    "affected_barcodes": stats.bc,
                    "is_open": False,
                }
            )
        return result


def get_batch_summary(batch_id: int) -> dict:
    """返回该批次 5 个统计 + roundtrip count。

    全部按 (barcode, field_name) 维度去重；同 barcode+field 多次变更
    若终态==起始态则计入 roundtrip_count，不进 5 个数字。
    """
    with stockpile_db._session() as session:
        start, end = _batch_window(session, batch_id)
        rows = session.execute(
            select(
                StockpileChange.product_barcode,
                StockpileChange.field_name,
                StockpileChange.old_value,
                StockpileChange.new_value,
                StockpileChange.change_type,
                StockpileChange.created_at,
            )
            .where(
                and_(
                    StockpileChange.created_at > start,
                    StockpileChange.created_at <= end,
                )
            )
            .order_by(StockpileChange.created_at)
        ).all()

    return _summarize(rows)


def get_batch_changes(
    batch_id: int,
    mode: Literal["collapsed", "raw"] = "collapsed",
    filter_field: str | None = None,
    filter_change_type: str | None = None,
) -> list[dict]:
    """返回批次明细。

    collapsed：按 (barcode, field) 折叠，roundtrip 剔除，多字段同 barcode 拆多行
    raw：原 stockpile_changes 行
    filter_field / filter_change_type：可选过滤
    """
    with stockpile_db._session() as session:
        start, end = _batch_window(session, batch_id)
        conds = [
            StockpileChange.created_at > start,
            StockpileChange.created_at <= end,
        ]
        if filter_field:
            conds.append(StockpileChange.field_name == filter_field)
        if filter_change_type:
            conds.append(StockpileChange.change_type == filter_change_type)

        rows = session.execute(
            select(
                StockpileChange.product_barcode,
                StockpileChange.field_name,
                StockpileChange.old_value,
                StockpileChange.new_value,
                StockpileChange.change_type,
                StockpileChange.created_at,
            )
            .where(and_(*conds))
            .order_by(StockpileChange.created_at)
        ).all()

        # 关联 model（一次查询，避免 N+1）
        barcodes = {r.product_barcode for r in rows}
        models: dict[str, str] = {}
        if barcodes:
            for bc, m in session.execute(
                select(Stockpile.product_barcode, Stockpile.product_model).where(
                    Stockpile.product_barcode.in_(barcodes)
                )
            ).all():
                models[bc] = m

    if mode == "raw":
        return [
            {
                "barcode": r.product_barcode,
                "model": models.get(r.product_barcode, ""),
                "field": r.field_name,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "change_type": r.change_type,
                "created_at": r.created_at,
            }
            for r in reversed(rows)
        ]

    # collapsed
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r.product_barcode, r.field_name), []).append(r)

    result = []
    for (barcode, field), group in grouped.items():
        first_old = group[0].old_value
        last_new = group[-1].new_value
        last_type = group[-1].change_type
        if first_old == last_new and last_type == "update":
            continue
        result.append(
            {
                "barcode": barcode,
                "model": models.get(barcode, ""),
                "field": field,
                "from_value": first_old,
                "to_value": last_new,
                "change_type": last_type,
                "latest_at": group[-1].created_at,
            }
        )
    result.sort(key=lambda r: r["latest_at"], reverse=True)
    return result


def _summarize(rows: list) -> dict:
    """把原始 changes 行折叠为 5 个统计 + roundtrip。"""
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r.product_barcode, r.field_name), []).append(r)

    counts = {
        "location_changes": 0,
        "model_changes": 0,
        "inserts": 0,
        "deactivates": 0,
        "reactivates": 0,
        "roundtrip_count": 0,
    }
    for (_barcode, field), group in grouped.items():
        first_old = group[0].old_value
        last_new = group[-1].new_value
        last_type = group[-1].change_type
        # roundtrip：终态==起始态（仅 update 类型有意义）
        if first_old == last_new and last_type == "update":
            counts["roundtrip_count"] += 1
            continue
        if last_type == "insert":
            counts["inserts"] += 1
        elif last_type == "deactivate":
            counts["deactivates"] += 1
        elif last_type == "reactivate":
            counts["reactivates"] += 1
        elif field == "stockpile_location":
            counts["location_changes"] += 1
        elif field == "product_model":
            counts["model_changes"] += 1
    return counts
