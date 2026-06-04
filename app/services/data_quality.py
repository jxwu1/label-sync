"""数据质量分析 service（阶段 1.5 PR3）。

只读，**不删除任何数据**。设计原则：观察 ≠ 修改。
新系统列出异常给用户看，用户去老系统修，下次月度 import 自动同步过来。

五类异常：
1. multi_same_kind     —— 同维度多库位（schema 表达不了的情形，~134 条）
2. flippers            —— location 翻转 ≥4 次的 barcode（~Top 50）
3. whitespace_anomalies —— stockpile_location 含 strip 后变化的字符（空格等）
4. unknown_prefix      —— 子表里 kind="unknown" 的货号（异常前缀）
5. duplicate_segments  —— raw 字符串里同一 location 段重复出现（解析器静默去重，UI 展示原始重复）

每个返回固定结构 {"count": int, "samples": list[dict]}，前端按相同模板渲染。
"""

import pandas as pd
from sqlalchemy import func, select

from app.repositories import stockpile_db
from app.models import (
    Stockpile,
    StockpileChange,
    StockpileInventorySnapshot,
    StockpileLocation,
)

_FLIPPER_THRESHOLD = 4  # location 变更次数 ≥ 该值才算 flipper
_FLIPPER_TOP_N = 50  # 最多返回 Top N
_WHITESPACE_TOP_N = 100
_MULTI_SAME_KIND_TOP_N = 200
_DUPLICATE_SEGMENTS_TOP_N = 100
_EMPTY_LOCATION_TOP_N = 200
_NEGATIVE_STOCK_TOP_N = 3000  # 线上 ~2249 行, 留余量


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
            "duplicated_kind": r[3],  # store / warehouse
            "count": r[4],
        }
        for r in rows
    ]
    # 总计单独算（不限 limit）
    total = session.execute(select(func.count()).select_from(sub)).scalar() or 0
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
    total = session.execute(select(func.count()).select_from(sub)).scalar() or 0
    return {"count": total, "samples": samples}


def _normalize_location_str(raw: str) -> str:
    """每段独立 strip 后用 / 拼回，空段忽略。空白修复的规范形式。"""
    return "/".join(p.strip() for p in raw.split("/") if p.strip())


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
        normalized = _normalize_location_str(raw)
        if raw != normalized:
            total += 1
            if len(samples) < _WHITESPACE_TOP_N:
                samples.append(
                    {
                        "barcode": barcode,
                        "model": model,
                        "raw_location": raw,
                        "normalized": normalized,
                    }
                )
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


def _duplicate_segments(session) -> dict:
    """raw stockpile_location 里同一 location 段重复出现（strip 后比较）。

    解析器 parse_to_locations 静默去重，子表已是干净的；本段把原始 raw 里的重复
    暴露给用户，用户去老系统改干净，下次 import 自动同步。
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
        if not raw or "/" not in raw:
            continue
        parts = [p.strip() for p in raw.split("/") if p.strip()]
        if len(parts) == len(set(parts)):
            continue
        total += 1
        if len(samples) < _DUPLICATE_SEGMENTS_TOP_N:
            seen: set[str] = set()
            duplicates: list[str] = []
            for p in parts:
                if p in seen and p not in duplicates:
                    duplicates.append(p)
                seen.add(p)
            samples.append(
                {
                    "barcode": barcode,
                    "model": model,
                    "raw_location": raw,
                    "duplicates": duplicates,
                }
            )
    return {"count": total, "samples": samples}


def build_whitespace_fix_dataframe() -> pd.DataFrame:
    """生成「产品信息导入模板」DataFrame，全量含所有 whitespace 异常货号。

    用于一键下载修复模板：每行 = 一个 whitespace 异常货号 + normalize 后的 location。
    复用 update_location.build_output_dataframe 与 find_template_path，模板列结构
    与写死值（货区/仓库ID/仓库名称）单一来源，update_location 那边演进时这边自动跟上。

    raises FileNotFoundError 若找不到产品信息导入模板.csv（部署故障）。
    """
    from app.utils.file_io import read_csv
    from phase_scripts.update_location import build_output_dataframe, find_template_path

    template_path = find_template_path()
    if template_path is None:
        raise FileNotFoundError("产品信息导入模板.csv 缺失，无法生成修复模板")
    template_df = read_csv(template_path).iloc[0:0]

    with stockpile_db._session() as session:
        rows = session.execute(
            select(Stockpile.product_model, Stockpile.stockpile_location).where(
                Stockpile.is_active == 1
            )
        ).all()

    results: list[dict[str, str]] = []
    for model, raw in rows:
        if not raw:
            continue
        normalized = _normalize_location_str(raw)
        if raw == normalized:
            continue
        results.append({"model": model, "location": normalized})

    return build_output_dataframe(template_df, results)


def _empty_locations(session) -> dict:
    """active SKU 但 stockpile_location 为空字符串或 NULL。

    业务含义：货还在系统里活跃，但没有对应的库位记录。可能场景：
    - 新进货号忘了贴位
    - 标签扫描时位置漏录
    - 老系统数据迁移残留
    inactive SKU（已下架）有空 location 是正常的，不计入。
    """
    base_filter = (Stockpile.is_active == 1) & (
        (Stockpile.stockpile_location == "") | Stockpile.stockpile_location.is_(None)
    )
    rows = session.execute(
        select(
            Stockpile.product_barcode,
            Stockpile.product_model,
            Stockpile.product_name_zh,
            Stockpile.updated_at,
        )
        .where(base_filter)
        .order_by(Stockpile.updated_at.desc())
        .limit(_EMPTY_LOCATION_TOP_N)
    ).all()
    samples = [
        {
            "barcode": r[0],
            "model": r[1] or "",
            "product_name": r[2] or "",
            "updated_at": r[3] or "",
        }
        for r in rows
    ]
    total = (
        session.execute(select(func.count()).select_from(Stockpile).where(base_filter)).scalar()
        or 0
    )
    return {"count": total, "samples": samples}


def _negative_stock(session) -> dict:
    """最新 snapshot 中 qty_total<0 的 SKU（ERP 超卖待到货 / 入库漏做 / 盘点错）。

    业务含义：负库存几乎肯定是数据错误，需要逐个去 ERP 核对修正。
    JOIN 用 rule A (snap.model == stockpile.model) + rule B
    (13 位 barcode 取倒数第 2-6 位匹配 5 位短码)，跟 v3 stop list 算法保持一致。
    返回最负的在前（qty_total 升序）。
    """
    latest_date = session.execute(
        select(func.max(StockpileInventorySnapshot.snapshot_date))
    ).scalar()
    if not latest_date:
        return {"count": 0, "samples": []}

    snap_rows = session.execute(
        select(
            StockpileInventorySnapshot.product_model,
            StockpileInventorySnapshot.qty_total,
        )
        .where(
            (StockpileInventorySnapshot.snapshot_date == latest_date)
            & (StockpileInventorySnapshot.qty_total < 0)
        )
        .order_by(StockpileInventorySnapshot.qty_total.asc())
        .limit(_NEGATIVE_STOCK_TOP_N)
    ).all()

    # 用 stockpile 反查 barcode/name. 一次性拉所有 stockpile, 内存匹配 rule A + B.
    sp_rows = session.execute(
        select(Stockpile.product_barcode, Stockpile.product_model, Stockpile.product_name_zh)
    ).all()
    by_model: dict[str, tuple[str, str, str | None]] = {}
    by_short5: dict[str, tuple[str, str, str | None]] = {}
    for bc, model, name in sp_rows:
        if model:
            by_model.setdefault(model, (bc, model, name))
        if bc and len(bc) == 13:
            by_short5.setdefault(bc[-6:-1], (bc, model, name))

    samples = []
    for snap_model, qty in snap_rows:
        hit = by_model.get(snap_model) or by_short5.get(snap_model)
        if hit is None:
            samples.append(
                {
                    "barcode": "",
                    "model": snap_model,
                    "product_name": "(未关联到 stockpile)",
                    "qty": int(qty),
                }
            )
        else:
            bc, model, name = hit
            samples.append(
                {
                    "barcode": bc,
                    "model": model or snap_model,
                    "product_name": name or "",
                    "qty": int(qty),
                }
            )

    total = (
        session.execute(
            select(func.count())
            .select_from(StockpileInventorySnapshot)
            .where(
                (StockpileInventorySnapshot.snapshot_date == latest_date)
                & (StockpileInventorySnapshot.qty_total < 0)
            )
        ).scalar()
        or 0
    )
    return {"count": total, "samples": samples, "snapshot_date": latest_date}


def _scanned_count(session) -> int:
    """扫描范围：主档全部行数（active + inactive）。供状态栏「扫描范围 N 条」。"""
    return session.execute(select(func.count()).select_from(Stockpile)).scalar() or 0


def build_report() -> dict:
    """顶层入口：返回 7 类异常的汇总 + 扫描范围。供 routes_data_quality jsonify。"""
    with stockpile_db._session() as session:
        return {
            "scanned_count": _scanned_count(session),
            "multi_same_kind": _multi_same_kind(session),
            "flippers": _flippers(session),
            "whitespace_anomalies": _whitespace_anomalies(session),
            "unknown_prefix": _unknown_prefix(session),
            "duplicate_segments": _duplicate_segments(session),
            "empty_locations": _empty_locations(session),
            "negative_stock": _negative_stock(session),
        }
