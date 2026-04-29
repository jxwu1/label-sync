"""数据质量分析 service（阶段 1.5 PR3）。

只读，**不删除任何数据**。设计原则：观察 ≠ 修改。
新系统列出异常给用户看，用户去老系统修，下次月度 import 自动同步过来。

四类异常：
1. multi_same_kind     —— 同维度多库位（schema 表达不了的情形，~134 条）
2. flippers            —— location 翻转 ≥4 次的 barcode（~Top 50）
3. whitespace_anomalies —— stockpile_location 含 strip 后变化的字符（空格等）
4. unknown_prefix      —— 子表里 kind="unknown" 的货号（异常前缀）

每个返回固定结构 {"count": int, "samples": list[dict]}，前端按相同模板渲染。
"""
from sqlalchemy import func, select

import stockpile_db
from models import Stockpile, StockpileChange, StockpileLocation

_FLIPPER_THRESHOLD = 4    # location 变更次数 ≥ 该值才算 flipper
_FLIPPER_TOP_N = 50       # 最多返回 Top N
_WHITESPACE_TOP_N = 100
_MULTI_SAME_KIND_TOP_N = 200


def _multi_same_kind(session) -> dict:
    """同 stockpile 下同 kind 的库位 ≥2 个。"""
    sub = (
        select(
            StockpileLocation.stockpile_id,
            StockpileLocation.kind,
            func.count().label("n"),
        )
        .group_by(StockpileLocation.stockpile_id, StockpileLocation.kind)
        .having(func.count() >= 2)
        .subquery()
    )
    rows = session.execute(
        select(
            Stockpile.product_barcode,
            Stockpile.product_model,
            Stockpile.stockpile_location,
            sub.c.kind,
            sub.c.n,
        )
        .join(sub, sub.c.stockpile_id == Stockpile.id)
        .where(Stockpile.is_active == 1)
        .order_by(sub.c.n.desc(), Stockpile.product_barcode)
        .limit(_MULTI_SAME_KIND_TOP_N)
    ).all()
    samples = [
        {
            "barcode": r[0],
            "model": r[1],
            "raw_location": r[2],
            "duplicated_kind": r[3],   # store / warehouse
            "count": r[4],
        }
        for r in rows
    ]
    # 总计单独算（不限 limit）
    total = session.execute(
        select(func.count())
        .select_from(sub)
    ).scalar() or 0
    return {"count": total, "samples": samples}


def _flippers(session) -> dict:
    """location 字段变更次数 ≥ 阈值的 barcode。"""
    sub = (
        select(
            StockpileChange.product_barcode.label("barcode"),
            func.count().label("n"),
        )
        .where(StockpileChange.field_name == "stockpile_location")
        .group_by(StockpileChange.product_barcode)
        .having(func.count() >= _FLIPPER_THRESHOLD)
        .subquery()
    )
    rows = session.execute(
        select(sub.c.barcode, sub.c.n, Stockpile.product_model, Stockpile.stockpile_location)
        .join(Stockpile, Stockpile.product_barcode == sub.c.barcode, isouter=True)
        .order_by(sub.c.n.desc())
        .limit(_FLIPPER_TOP_N)
    ).all()
    samples = [
        {
            "barcode": r[0],
            "change_count": r[1],
            "model": r[2],
            "current_location": r[3],
        }
        for r in rows
    ]
    total = session.execute(
        select(func.count()).select_from(sub)
    ).scalar() or 0
    return {"count": total, "samples": samples}


def _whitespace_anomalies(session) -> dict:
    """raw stockpile_location 含 strip 后变化的字符（前后空格、段间空格等）。

    Python 端逐条比对，不拼 SQL 复杂判断（量级在 43k，可接受）。
    """
    rows = session.execute(
        select(
            Stockpile.product_barcode,
            Stockpile.product_model,
            Stockpile.stockpile_location,
        ).where(Stockpile.is_active == 1)
    ).all()

    samples = []
    total = 0
    for barcode, model, raw in rows:
        if not raw:
            continue
        # 规范化：每段独立 strip 后用 / 拼回
        normalized = "/".join(p.strip() for p in raw.split("/") if p.strip())
        if raw != normalized:
            total += 1
            if len(samples) < _WHITESPACE_TOP_N:
                samples.append({
                    "barcode": barcode,
                    "model": model,
                    "raw_location": raw,
                    "normalized": normalized,
                })
    return {"count": total, "samples": samples}


def _unknown_prefix(session) -> dict:
    """stockpile_locations.kind = 'unknown' 的货号（A/B/C/X/Z 之外的前缀）。"""
    rows = session.execute(
        select(
            Stockpile.product_barcode,
            Stockpile.product_model,
            Stockpile.stockpile_location,
            StockpileLocation.location,
        )
        .join(StockpileLocation, StockpileLocation.stockpile_id == Stockpile.id)
        .where(StockpileLocation.kind == "unknown")
        .order_by(Stockpile.product_barcode)
    ).all()
    samples = [
        {
            "barcode": r[0],
            "model": r[1],
            "raw_location": r[2],
            "anomalous_segment": r[3],
        }
        for r in rows
    ]
    return {"count": len(samples), "samples": samples}


def build_report() -> dict:
    """顶层入口：返回 4 类异常的汇总。供 routes_data_quality jsonify。"""
    with stockpile_db._session() as session:
        return {
            "multi_same_kind": _multi_same_kind(session),
            "flippers": _flippers(session),
            "whitespace_anomalies": _whitespace_anomalies(session),
            "unknown_prefix": _unknown_prefix(session),
        }
