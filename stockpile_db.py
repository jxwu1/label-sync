"""stockpile DB 数据访问层（ORM 全链路）。

阶段 1.3 起：schema 由 models.py 的 Base.metadata 单源管理；本文件不再持有
DDL 字符串。新增字段 → 改 ORM 类 → `alembic revision --autogenerate`。
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from config import CONFIG
from location_parser import parse_to_locations
from models import (
    Base,
    SchemaMeta,
    Stockpile,
    StockpileChange,
    StockpileLocation,
    StockpileSnapshot,
)

DB_PATH = CONFIG.stockpile_db
SCHEMA_VERSION = 2


_KNOWN_COLS = frozenset({"product_barcode", "product_model", "stockpile_location"})

_STOCKPILE_DICT_COLS = (
    "id",
    "product_barcode",
    "product_model",
    "stockpile_location",
    "is_active",
    "extra",
    "source",
    "created_at",
    "updated_at",
)
_CHANGE_DICT_COLS = (
    "id",
    "product_barcode",
    "field_name",
    "old_value",
    "new_value",
    "change_type",
    "created_at",
)

_ACTIVE = 1
_INACTIVE = 0

# substantive 不一致超过此阈值前端高亮告警；cosmetic 数量再多也不告警
SUBSTANTIVE_ALERT_THRESHOLD = 3


class Source:
    SYSTEM_EXPORT = "system_export"
    USER_CORRECTION = "user_correction"
    SCAN_IMPORT = "scan_import"


# === Engine / session / schema bootstrap ===

_engine_cache: dict[str, Engine] = {}


def _build_engine(db_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", future=True, poolclass=NullPool)

    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def _engine() -> Engine:
    key = str(DB_PATH)
    cached = _engine_cache.get(key)
    if cached is not None:
        return cached
    engine = _build_engine(key)
    Base.metadata.create_all(engine)
    _bootstrap_schema_version(engine)
    _engine_cache[key] = engine
    return engine


def _bootstrap_schema_version(engine: Engine) -> None:
    with Session(engine) as session:
        meta = session.execute(
            select(SchemaMeta).where(SchemaMeta.key == "schema_version")
        ).scalar_one_or_none()
        if meta is None:
            session.add(SchemaMeta(key="schema_version", value=str(SCHEMA_VERSION)))
        elif meta.value != str(SCHEMA_VERSION):
            meta.value = str(SCHEMA_VERSION)
        session.commit()


def ensure_db() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    _bootstrap_schema_version(engine)


def _connect() -> sqlite3.Connection:
    """raw sqlite3 连接，仅供需要绕过 ORM 的旧测试 / 维护脚本使用。

    自动先调 ensure_db()（幂等）确保 schema 存在，调用方无需关心。
    """
    ensure_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_schema_version() -> int:
    ensure_db()
    with _session() as session:
        meta = session.execute(
            select(SchemaMeta).where(SchemaMeta.key == "schema_version")
        ).scalar_one_or_none()
    if meta is None:
        return 0
    try:
        return int(meta.value)
    except (TypeError, ValueError):
        return 0


@contextmanager
def _session() -> Iterator[Session]:
    session = Session(_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _stockpile_to_dict(obj) -> dict:
    return {col: getattr(obj, col) for col in _STOCKPILE_DICT_COLS}


def _change_to_dict(obj) -> dict:
    return {col: getattr(obj, col) for col in _CHANGE_DICT_COLS}


# === Pure helpers ===


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    return "" if s == "nan" else s


def _extra_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in (str(c).strip() for c in df.columns) if c not in _KNOWN_COLS]


def _normalize_row(row, extra_cols: list[str]) -> tuple[str, str, str, dict] | None:
    barcode = _clean(row.get("product_barcode", ""))
    if not barcode:
        return None
    model = _clean(row.get("product_model", ""))
    location = _clean(row.get("stockpile_location", ""))
    extra = {c: _clean(row.get(c, "")) for c in extra_cols}
    return barcode, model, location, extra


# === Write path (ORM) ===


def _log_change(
    session: Session,
    barcode: str,
    field: str,
    old_val: str | None,
    new_val: str | None,
    change_type: str,
) -> None:
    session.add(
        StockpileChange(
            product_barcode=barcode,
            field_name=field,
            old_value=old_val,
            new_value=new_val,
            change_type=change_type,
        )
    )


def _sync_locations(session: Session, stockpile_obj: Stockpile, raw_location: str) -> None:
    """重建 stockpile_obj 在 stockpile_locations 子表中的行，从 raw 字符串解析。

    raw 字符串本身仍存主表 stockpile.stockpile_location，是月度比对源；
    本子表是它的派生分析视图。

    实现：显式 DELETE 旧行 + flush 之后再 INSERT 新行。不用 cascade 替换是因为
    重新导入相同 location 时新旧 (stockpile_id, location) 撞 UNIQUE，autoflush
    顺序无保证。
    """
    parsed = parse_to_locations(raw_location)

    if stockpile_obj.id is None:
        # 新插入的主记录：flush 拿到自增 id
        session.flush()
    else:
        # 已有主记录：先删旧子行，让 ORM 忘掉缓存的 .locations 关系
        session.execute(
            delete(StockpileLocation).where(StockpileLocation.stockpile_id == stockpile_obj.id)
        )
        session.expire(stockpile_obj, ["locations"])

    for entry in parsed:
        session.add(
            StockpileLocation(
                stockpile_id=stockpile_obj.id,
                location=entry["location"],
                kind=entry["kind"],
                position=entry["position"],
            )
        )


def _upsert(
    session: Session,
    barcode: str,
    model: str,
    location: str,
    extra: dict,
    source: str,
    log_changes: bool = True,
    *,
    is_active: int | None = None,
    product_name_zh: str | None = None,
    product_name_local: str | None = None,
    erp_category_raw: str | None = None,
    erp_category_code: str | None = None,
    manual_grade: int | None = None,
    stock_price: float | None = None,
    sale_price: float | None = None,
) -> None:
    """所有 stockpile 写入路径的统一入口。

    历史调用方（标签流程 / 月度 import）只传前 6 个位置参数 + log_changes。
    is_active 默认 None → 保持现有行为（即遇到的都标 _ACTIVE，是为了兼容老语义）。
    新调用方（product master）传 kwargs 写入名字 / 分类 / 价格等扩展字段。

    每个 kwarg 默认 None = "不更新此字段"。Truthy 值或显式 0 才更新。
    """
    # 默认 is_active 行为：历史语义是"扫到/导到的都算 active"，保留这个语义
    effective_is_active = _ACTIVE if is_active is None else is_active

    existing = session.execute(
        select(Stockpile).where(Stockpile.product_barcode == barcode)
    ).scalar_one_or_none()
    extra_json = json.dumps(extra, ensure_ascii=False)
    if existing is not None:
        if log_changes:
            if existing.product_model != model:
                _log_change(
                    session, barcode, "product_model", existing.product_model, model, "update"
                )
            if existing.stockpile_location != location:
                _log_change(
                    session,
                    barcode,
                    "stockpile_location",
                    existing.stockpile_location,
                    location,
                    "update",
                )
            if existing.is_active != effective_is_active:
                change_type = "reactivate" if effective_is_active == _ACTIVE else "deactivate"
                _log_change(
                    session,
                    barcode,
                    "is_active",
                    str(existing.is_active),
                    str(effective_is_active),
                    change_type,
                )
            # 扩展字段的变更记录（仅在显式传入且不同时记）
            for field_name, new_val in (
                ("product_name_zh", product_name_zh),
                ("product_name_local", product_name_local),
                ("erp_category_code", erp_category_code),
                ("stock_price", stock_price),
                ("sale_price", sale_price),
                ("manual_grade", manual_grade),
            ):
                if new_val is None:
                    continue
                old_val = getattr(existing, field_name)
                if old_val != new_val:
                    _log_change(
                        session,
                        barcode,
                        field_name,
                        None if old_val is None else str(old_val),
                        str(new_val),
                        "update",
                    )
        existing.product_model = model
        existing.stockpile_location = location
        existing.is_active = effective_is_active
        existing.source = source
        existing.extra = extra_json
        existing.updated_at = func.datetime("now", "localtime")
        # 扩展字段：仅当传入时更新（None = 保留旧值）
        if product_name_zh is not None:
            existing.product_name_zh = product_name_zh
        if product_name_local is not None:
            existing.product_name_local = product_name_local
        if erp_category_raw is not None:
            existing.erp_category_raw = erp_category_raw
        if erp_category_code is not None:
            existing.erp_category_code = erp_category_code
        if manual_grade is not None:
            existing.manual_grade = manual_grade
        if stock_price is not None:
            existing.stock_price = stock_price
        if sale_price is not None:
            existing.sale_price = sale_price
        _sync_locations(session, existing, location)
        return

    new_obj = Stockpile(
        product_barcode=barcode,
        product_model=model,
        stockpile_location=location,
        is_active=effective_is_active,
        extra=extra_json,
        source=source,
        product_name_zh=product_name_zh,
        product_name_local=product_name_local,
        erp_category_raw=erp_category_raw,
        erp_category_code=erp_category_code,
        manual_grade=manual_grade,
        stock_price=stock_price,
        sale_price=sale_price,
    )
    session.add(new_obj)
    _sync_locations(session, new_obj, location)
    if log_changes:
        _log_change(session, barcode, "product_barcode", None, barcode, "insert")


def _deactivate_missing_records(session: Session, active_barcodes: set[str]) -> None:
    rows = session.execute(select(Stockpile).where(Stockpile.is_active == _ACTIVE)).scalars().all()
    for row in rows:
        if row.product_barcode in active_barcodes:
            continue
        _log_change(
            session,
            row.product_barcode,
            "is_active",
            str(_ACTIVE),
            str(_INACTIVE),
            "deactivate",
        )
        row.is_active = _INACTIVE
        row.updated_at = func.datetime("now", "localtime")


def _sync_export_dataframe(df: pd.DataFrame) -> int:
    extra_cols = _extra_cols(df)
    synced = 0
    active_barcodes: set[str] = set()
    with _session() as session:
        for _, row in df.iterrows():
            normalized = _normalize_row(row, extra_cols)
            if not normalized:
                continue
            barcode, model, location, extra = normalized
            active_barcodes.add(barcode)
            _upsert(
                session, barcode, model, location, extra, Source.SYSTEM_EXPORT, log_changes=True
            )
            synced += 1
        _deactivate_missing_records(session, active_barcodes)
        _take_snapshot(session, trigger="import", total_local=len(active_barcodes))
    return synced


def _normalize_location(raw: str | None) -> str:
    """段独立 strip + 过滤空段 + 保留顺序。

    "B04-22-04 /Z202-01"  → "B04-22-04/Z202-01"
    "  A22 / X11  "       → "A22/X11"
    "/A22/"               → "A22"
    顺序保留：" X11/A22 " → "X11/A22"（不重排，店面在前 / 仓库在后由聚合脚本保证）
    """
    if not raw:
        return ""
    return "/".join(p.strip() for p in str(raw).split("/") if p.strip())


def _take_snapshot(
    session: Session,
    *,
    trigger: str,
    total_local: int,
    total_export: int | None = None,
    consistent: int | None = None,
    cosmetic_count: int | None = None,
    substantive_count: int | None = None,
    only_in_local_count: int | None = None,
    only_in_export_count: int | None = None,
) -> None:
    session.add(
        StockpileSnapshot(
            trigger=trigger,
            total_local=total_local,
            total_export=total_export,
            consistent=consistent,
            cosmetic_count=cosmetic_count,
            substantive_count=substantive_count,
            only_in_local_count=only_in_local_count,
            only_in_export_count=only_in_export_count,
        )
    )


# === Read path (ORM) ===


def is_initialized() -> bool:
    return count_records() > 0


def count_records() -> int:
    with _session() as session:
        result = session.execute(
            select(func.count()).select_from(Stockpile).where(Stockpile.is_active == _ACTIVE)
        ).scalar()
    return result or 0


def query_by_barcode(barcode: str) -> dict | None:
    with _session() as session:
        obj = session.execute(
            select(Stockpile).where(Stockpile.product_barcode == barcode)
        ).scalar_one_or_none()
        return _stockpile_to_dict(obj) if obj else None


def query_all_as_system_records() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    with _session() as session:
        rows = session.execute(
            select(
                Stockpile.product_barcode,
                Stockpile.product_model,
                Stockpile.stockpile_location,
            ).where(Stockpile.is_active == _ACTIVE)
        ).all()
    barcode_model_map: dict[str, str] = {}
    system_records: dict[str, dict[str, str]] = {}
    for barcode, model, location in rows:
        barcode_model_map[barcode] = model
        system_records[barcode] = {"model": model, "stockpile_location": location}
    return barcode_model_map, system_records


def query_all_barcodes_set() -> set[str]:
    with _session() as session:
        rows = session.execute(
            select(Stockpile.product_barcode).where(Stockpile.is_active == _ACTIVE)
        ).all()
    return {row[0] for row in rows}


def list_inactive_records(limit: int = 100) -> list[dict]:
    with _session() as session:
        objs = (
            session.execute(
                select(Stockpile)
                .where(Stockpile.is_active == _INACTIVE)
                .order_by(Stockpile.updated_at.desc(), Stockpile.id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [_stockpile_to_dict(o) for o in objs]


def list_changes(limit: int = 100) -> list[dict]:
    with _session() as session:
        objs = (
            session.execute(
                select(StockpileChange).order_by(StockpileChange.id.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        return [_change_to_dict(o) for o in objs]


def search_stockpile(keyword: str, limit: int = 50) -> list[dict]:
    pattern = f"%{keyword}%"
    with _session() as session:
        rows = session.execute(
            select(
                Stockpile.product_barcode,
                Stockpile.product_model,
                Stockpile.stockpile_location,
                Stockpile.is_active,
                Stockpile.source,
                Stockpile.updated_at,
            )
            .where(Stockpile.is_active == _ACTIVE)
            .where(Stockpile.product_barcode.like(pattern) | Stockpile.product_model.like(pattern))
            .order_by(Stockpile.product_barcode)
            .limit(limit)
        ).all()
    return [
        {
            "product_barcode": r[0],
            "product_model": r[1],
            "stockpile_location": r[2],
            "is_active": r[3],
            "source": r[4],
            "updated_at": r[5],
        }
        for r in rows
    ]


# === Public API ===


def insert_or_update(
    barcode: str,
    model: str,
    location: str,
    source: str = Source.USER_CORRECTION,
    extra: dict | None = None,
) -> None:
    with _session() as session:
        _upsert(session, barcode, model, location, extra or {}, source, log_changes=True)


def import_from_dataframe(df: pd.DataFrame) -> int:
    return _sync_export_dataframe(df)


def apply_export_updates(df: pd.DataFrame) -> int:
    return _sync_export_dataframe(df)


def compare_with_dataframe(df: pd.DataFrame) -> dict:
    """双轴比对：把不一致拆 cosmetic vs substantive。

    - cosmetic_mismatches：raw 字符串不同，但 _normalize_location 后相同
      （例：老系统正在清理空格 / 顺序差异）
    - substantive_mismatches：normalize 后仍不同（model 差异或 location 实质改动）

    `mismatches` 字段保留为 cosmetic + substantive 的并集，向后兼容。

    每次比对在 stockpile_snapshots 留一行 trigger='compare' 的快照，便于趋势分析。
    """
    extra_cols: list[str] = []
    export_records: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        normalized = _normalize_row(row, extra_cols)
        if not normalized:
            continue
        barcode, model, location, _ = normalized
        export_records[barcode] = {"product_model": model, "stockpile_location": location}

    _, local_records = query_all_as_system_records()
    local_barcodes = set(local_records.keys())
    export_barcodes = set(export_records.keys())

    only_local = sorted(local_barcodes - export_barcodes)
    only_export = sorted(export_barcodes - local_barcodes)

    cosmetic_mismatches: list[dict] = []
    substantive_mismatches: list[dict] = []
    for barcode in local_barcodes & export_barcodes:
        local = local_records[barcode]
        export = export_records[barcode]
        model_diff = local["model"] != export["product_model"]
        loc_diff_raw = local["stockpile_location"] != export["stockpile_location"]
        if not model_diff and not loc_diff_raw:
            continue

        entry = {
            "barcode": barcode,
            "local_model": local["model"],
            "export_model": export["product_model"],
            "local_location": local["stockpile_location"],
            "export_location": export["stockpile_location"],
        }
        if model_diff:
            substantive_mismatches.append(entry)
            continue
        # 仅 location 不同：看 normalize 后是否相同
        if _normalize_location(local["stockpile_location"]) == _normalize_location(
            export["stockpile_location"]
        ):
            cosmetic_mismatches.append(entry)
        else:
            substantive_mismatches.append(entry)

    consistent = (
        len(local_barcodes & export_barcodes)
        - len(cosmetic_mismatches)
        - len(substantive_mismatches)
    )

    with _session() as session:
        _take_snapshot(
            session,
            trigger="compare",
            total_local=len(local_barcodes),
            total_export=len(export_barcodes),
            consistent=consistent,
            cosmetic_count=len(cosmetic_mismatches),
            substantive_count=len(substantive_mismatches),
            only_in_local_count=len(only_local),
            only_in_export_count=len(only_export),
        )

    return {
        "total_local": len(local_barcodes),
        "total_export": len(export_barcodes),
        "only_in_local": only_local,
        "only_in_export": only_export,
        "cosmetic_mismatches": cosmetic_mismatches,
        "substantive_mismatches": substantive_mismatches,
        "mismatches": cosmetic_mismatches + substantive_mismatches,  # 向后兼容
        "consistent": consistent,
        "alert": len(substantive_mismatches) >= SUBSTANTIVE_ALERT_THRESHOLD,
    }


def list_snapshots(limit: int = 50, trigger: str | None = None) -> list[dict]:
    """供前端趋势图的接口：返回最近 N 个快照。"""
    with _session() as session:
        stmt = (
            select(
                StockpileSnapshot.id,
                StockpileSnapshot.taken_at,
                StockpileSnapshot.trigger,
                StockpileSnapshot.total_local,
                StockpileSnapshot.total_export,
                StockpileSnapshot.consistent,
                StockpileSnapshot.cosmetic_count,
                StockpileSnapshot.substantive_count,
                StockpileSnapshot.only_in_local_count,
                StockpileSnapshot.only_in_export_count,
            )
            .order_by(StockpileSnapshot.id.desc())
            .limit(limit)
        )
        if trigger:
            stmt = stmt.where(StockpileSnapshot.trigger == trigger)
        rows = session.execute(stmt).all()
    return [
        {
            "id": r[0],
            "taken_at": r[1],
            "trigger": r[2],
            "total_local": r[3],
            "total_export": r[4],
            "consistent": r[5],
            "cosmetic_count": r[6],
            "substantive_count": r[7],
            "only_in_local_count": r[8],
            "only_in_export_count": r[9],
        }
        for r in rows
    ]
