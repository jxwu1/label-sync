"""补货决策反馈服务 (P3 数据收集 + 算法体检用).

POST /restock/decisions → record_decision()
GET  /restock/decisions/recent → list_recent()
GET  /restock/decisions/stats → aggregate_stats()
GET  /restock/decisions/stale → list_stale_high_score() (现算, 不入库)

决策类型 (decision 列):
  - 'ordered'         : 用户点「✓ 标已下单」, 当前 urgency >= 50
  - 'overridden'      : 用户点「✓ 标已下单」, 当前 urgency < 50
                       (低分但你硬要进 → 隐式信号: 算法没看到的维度)
  - 'skipped'         : 用户点「✗ 不进」 + reason (出现在 top 但不进)
  - 'stale_high_score': urgency>=70 持续 >=14 天且 14 天内无 ordered 决策
                       (按需扫出, list_stale_high_score 返回, 不入库)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import RestockDecision

OVERRIDDEN_URGENCY_THRESHOLD = 50.0
STALE_HIGH_SCORE_DAYS = 14


def _snapshot_fields(item: dict[str, Any]) -> dict[str, Any]:
    """前端 item dict → 快照字段, 兼容 breakdown=None."""
    bd = item.get("urgency_breakdown") or {}
    return {
        "urgency_score": item.get("urgency_score"),
        "velocity_pctile": bd.get("velocity_pctile"),
        "margin_pctile": bd.get("margin_pctile"),
        "breakdown_velocity": bd.get("velocity"),
        "breakdown_cover": bd.get("cover"),
        "breakdown_recency": bd.get("recency"),
        "breakdown_margin": bd.get("margin"),
        "margin_source": item.get("margin_source"),
        "weekly_revenue": item.get("weekly_revenue"),
        "weekly_velocity": item.get("weekly_velocity"),
        "margin_pct": item.get("margin_pct"),
        "weeks_of_cover": item.get("weeks_of_cover"),
        "origin": item.get("origin"),
        "supplier_id": item.get("supplier_id"),
    }


def record_decision(
    session: Session,
    barcode: str,
    decision: str,
    item: dict[str, Any],
    reason: str | None = None,
) -> RestockDecision:
    """记录一条决策快照."""
    row = RestockDecision(
        barcode=barcode,
        decision=decision,
        reason=reason,
        **_snapshot_fields(item),
    )
    session.add(row)
    return row


def classify_ordered(item: dict[str, Any]) -> str:
    """根据当前 urgency_score 判 ordered vs overridden."""
    score = item.get("urgency_score")
    if score is None or score < OVERRIDDEN_URGENCY_THRESHOLD:
        return "overridden"
    return "ordered"


def list_recent(session: Session, limit: int = 200, decision: str | None = None) -> list[dict[str, Any]]:
    stmt = select(RestockDecision).order_by(desc(RestockDecision.decided_at)).limit(limit)
    if decision:
        stmt = select(RestockDecision).where(
            RestockDecision.decision == decision
        ).order_by(desc(RestockDecision.decided_at)).limit(limit)
    rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r) for r in rows]


def aggregate_stats(session: Session, days: int = 30) -> dict[str, Any]:
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = session.execute(
        select(RestockDecision).where(RestockDecision.decided_at >= cutoff)
    ).scalars().all()
    by_decision: dict[str, int] = {}
    by_origin_skipped: dict[str, int] = {}
    by_origin_ordered: dict[str, int] = {}
    avg_urgency: dict[str, list[float]] = {}
    for r in rows:
        by_decision[r.decision] = by_decision.get(r.decision, 0) + 1
        if r.decision == "skipped" and r.origin:
            by_origin_skipped[r.origin] = by_origin_skipped.get(r.origin, 0) + 1
        if r.decision == "ordered" and r.origin:
            by_origin_ordered[r.origin] = by_origin_ordered.get(r.origin, 0) + 1
        if r.urgency_score is not None:
            avg_urgency.setdefault(r.decision, []).append(r.urgency_score)
    return {
        "window_days": days,
        "total": len(rows),
        "by_decision": by_decision,
        "by_origin_skipped": by_origin_skipped,
        "by_origin_ordered": by_origin_ordered,
        "avg_urgency_by_decision": {
            k: round(sum(v) / len(v), 1) for k, v in avg_urgency.items()
        },
    }


def list_stale_high_score(session: Session, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从当前 items 筛出 urgency>=70 且 14 天内无 ordered/overridden 决策的 SKU. 不入库."""
    cutoff = (datetime.now(UTC) - timedelta(days=STALE_HIGH_SCORE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    recent_ordered_barcodes = set(
        session.execute(
            select(RestockDecision.barcode).where(
                (RestockDecision.decision.in_(("ordered", "overridden")))
                & (RestockDecision.decided_at >= cutoff)
            )
        ).scalars().all()
    )
    return [
        it for it in items
        if (it.get("urgency_score") or 0) >= 70
        and it["barcode"] not in recent_ordered_barcodes
    ]


def _row_to_dict(r: RestockDecision) -> dict[str, Any]:
    return {
        "id": r.id,
        "barcode": r.barcode,
        "decision": r.decision,
        "decided_at": r.decided_at,
        "urgency_score": r.urgency_score,
        "velocity_pctile": r.velocity_pctile,
        "margin_pctile": r.margin_pctile,
        "breakdown_velocity": r.breakdown_velocity,
        "breakdown_cover": r.breakdown_cover,
        "breakdown_recency": r.breakdown_recency,
        "breakdown_margin": r.breakdown_margin,
        "margin_source": r.margin_source,
        "weekly_revenue": r.weekly_revenue,
        "weekly_velocity": r.weekly_velocity,
        "margin_pct": r.margin_pct,
        "weeks_of_cover": r.weeks_of_cover,
        "origin": r.origin,
        "supplier_id": r.supplier_id,
        "reason": r.reason,
    }
