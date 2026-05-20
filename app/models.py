"""SQLAlchemy 声明式 ORM 模型层（schema 单源）。

阶段 1.3 起：本模块的 Base.metadata 是 schema 唯一来源。
- stockpile_db._SCHEMA / _ensure_schema / _migrate_schema 已删除
- ensure_db() 通过 Base.metadata.create_all(engine) 建表，幂等
- 新增字段直接改 ORM 类 + alembic revision --autogenerate

使用方式：
    from app.models import Stockpile, StockpileChange, get_session
    with get_session() as session:
        rows = session.query(Stockpile).limit(10).all()
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from app.config import CONFIG

# DATABASE_URL 环境变量优先（PG 迁移用），回退 SQLite 文件
DB_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{CONFIG.stockpile_db}"

_engine: Engine = create_engine(DB_URL, future=True)


@event.listens_for(_engine, "connect")
def _enable_wal(dbapi_conn, _) -> None:
    # WAL 是 SQLite 专属；PG 不需要这个 PRAGMA
    if _engine.dialect.name != "sqlite":
        return
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


class Base(DeclarativeBase):
    pass


class Stockpile(Base):
    __tablename__ = "stockpile"
    __table_args__ = (
        Index("idx_stockpile_barcode", "product_barcode"),
        Index("idx_stockpile_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_barcode: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    product_model: Mapped[str] = mapped_column(Text, nullable=False)
    stockpile_location: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    extra: Mapped[str | None] = mapped_column(Text, server_default=text("'{}'"))
    source: Mapped[str | None] = mapped_column(Text, server_default=text("'system_export'"))
    created_at: Mapped[str | None] = mapped_column(
        Text, server_default=func.current_timestamp()
    )
    updated_at: Mapped[str | None] = mapped_column(
        Text, server_default=func.current_timestamp()
    )

    # 阶段 4 新增（2026-05-05）
    # 产品名（区别于 product_model 那个数字 SKU 码）
    product_name_zh: Mapped[str | None] = mapped_column(Text)
    product_name_local: Mapped[str | None] = mapped_column(Text)
    # ERP 分类（产品种类列拆出来的 code 和原字符串）
    erp_category_raw: Mapped[str | None] = mapped_column(Text)
    erp_category_code: Mapped[str | None] = mapped_column(Text)
    # 人工等级 1-10，0=停用，仅作展示和验证不进算法
    manual_grade: Mapped[int | None] = mapped_column(Integer)
    # 用户手填的分类标签（覆盖自动分类）
    manual_category: Mapped[str | None] = mapped_column(Text)
    # 系统自动判定的分类（每天后台重算）
    auto_category: Mapped[str | None] = mapped_column(Text)
    auto_category_computed_at: Mapped[str | None] = mapped_column(Text)
    # 产品总档（product.csv）的档案价格 — 与 inventory_events 的实际成交价不同
    stock_price: Mapped[float | None] = mapped_column()  # 进价档案
    sale_price: Mapped[float | None] = mapped_column()  # 售价档案
    # 极高置信「真停用」: 库存=0 AND PG 完全无销售/采购事件. dashboard toggle 用.
    is_truly_discontinued: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )

    locations: Mapped[list[StockpileLocation]] = relationship(
        "StockpileLocation",
        back_populates="stockpile",
        cascade="all, delete-orphan",
        order_by="StockpileLocation.position",
    )


class StockpileLocation(Base):
    """多库位子表（阶段 1.5 起）。

    派生自 stockpile.stockpile_location 字符串，每段一行。
    主表那个字符串永久保留作为月度比对的字节级源；本表只做分析视图。
    """

    __tablename__ = "stockpile_locations"
    __table_args__ = (
        UniqueConstraint("stockpile_id", "location", name="uq_stockpile_locations"),
        Index("idx_stockpile_locations_location", "location"),
        Index("idx_stockpile_locations_stockpile", "stockpile_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stockpile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("stockpile.id", ondelete="CASCADE"),
        nullable=False,
    )
    location: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # store / warehouse / unknown
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[str | None] = mapped_column(
        Text, server_default=func.current_timestamp()
    )

    stockpile: Mapped[Stockpile] = relationship("Stockpile", back_populates="locations")


class StockpileChange(Base):
    __tablename__ = "stockpile_changes"
    __table_args__ = (Index("idx_changes_barcode", "product_barcode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_barcode: Mapped[str] = mapped_column(Text, nullable=False)
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(
        Text, server_default=func.current_timestamp()
    )


class SchemaMeta(Base):
    __tablename__ = "schema_meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class StockpileSnapshot(Base):
    """每次 import / compare 时留一份计数快照，用于趋势分析。

    阶段 1.5 PR4 起：cosmetic / substantive 不一致随时间的曲线
    是判断"老系统清理进度"和"实质漂移"的关键观测。
    """

    __tablename__ = "stockpile_snapshots"
    __table_args__ = (Index("idx_stockpile_snapshots_taken_at", "taken_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    taken_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp()
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)  # 'import' / 'compare'
    total_local: Mapped[int] = mapped_column(Integer, nullable=False)
    # 以下字段仅 trigger='compare' 时填，import 时 NULL
    total_export: Mapped[int | None] = mapped_column(Integer)
    consistent: Mapped[int | None] = mapped_column(Integer)
    cosmetic_count: Mapped[int | None] = mapped_column(Integer)
    substantive_count: Mapped[int | None] = mapped_column(Integer)
    only_in_local_count: Mapped[int | None] = mapped_column(Integer)
    only_in_export_count: Mapped[int | None] = mapped_column(Integer)


class Customer(Base):
    """客户主档（dedupe 自销售交易行）。

    customer_type 由 customer_classifier.classify_customer 算出来：
    'foreign'（希腊语名=老外）/ 'chinese'（中文名）/ 'mixed' / 'unknown'。
    """

    __tablename__ = "customers"
    __table_args__ = (Index("idx_customers_type", "customer_type"),)

    customer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    customer_type: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class Supplier(Base):
    """供应商主档（dedupe 自采购交易行）。"""

    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(Text, primary_key=True)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[str | None] = mapped_column(Text)


class InventoryEvent(Base):
    """进销存事件（采购 + 销售统一一张表，event_type 区分）。

    去重键：(event_type, document_no, shipping_doc, product_barcode, event_at, qty,
    unit_price)，重复 import 同一份 CSV 不会重复落库。
    """

    __tablename__ = "inventory_events"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "document_no",
            "shipping_doc",
            "product_barcode",
            "event_at",
            "qty",
            "unit_price",
            name="uq_inventory_events",
        ),
        Index("idx_events_barcode_at", "product_barcode", "event_at"),
        Index("idx_events_customer", "customer_id"),
        Index("idx_events_supplier", "supplier_id"),
        Index("idx_events_type_at", "event_type", "event_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_at: Mapped[str] = mapped_column(Text, nullable=False)  # YYYY-MM-DD
    event_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'purchase' / 'sale'
    product_barcode: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float | None] = mapped_column()
    discount_pct: Mapped[float | None] = mapped_column()
    document_no: Mapped[str | None] = mapped_column(Text)
    shipping_doc: Mapped[str | None] = mapped_column(Text)
    customer_id: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[str | None] = mapped_column(Text)
    warehouse: Mapped[str | None] = mapped_column(Text)
    erp_category_raw: Mapped[str | None] = mapped_column(Text)
    erp_category_code: Mapped[str | None] = mapped_column(Text)
    manual_grade: Mapped[int | None] = mapped_column(Integer)
    imported_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp()
    )


class InventoryImport(Base):
    """每次 inventory_events import 的 audit 行（PR-FE-5b）。

    给「最近导入」表格用：时间 / 类型 / 文件 / 总行 / OK / 重复 / 错误 / 操作员。
    """

    __tablename__ = "inventory_imports"
    __table_args__ = (Index("idx_inventory_imports_at", "imported_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    imported_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp()
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'purchase' / 'sale'
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    ok_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dup_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    operator: Mapped[str] = mapped_column(Text, nullable=False, server_default="admin")


class ForeignCustomerRecord(Base):
    """老外客人月度记录（独立模块）。

    每月每客户一条，记欠款 / 税号 / 付款 / 托运。与 customers 表通过
    customer_id 关联；customer 由销售交易自动 dedupe 出来，记录由用户手动填。
    """

    __tablename__ = "foreign_customer_records"
    __table_args__ = (
        UniqueConstraint("customer_id", "record_month", name="uq_foreign_customer_records"),
        Index("idx_fcr_month", "record_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    record_month: Mapped[str] = mapped_column(Text, nullable=False)  # YYYY-MM
    amount_due: Mapped[float | None] = mapped_column()
    tax_number: Mapped[str | None] = mapped_column(Text)
    payment_date: Mapped[str | None] = mapped_column(Text)
    shipping_date: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(
        Text, server_default=func.current_timestamp()
    )


class ImportProfile(Base):
    """导入向导配置：列名 → 内部字段的映射。

    profile_name 'purchase' / 'sales'，每种文件类型一行。column_mapping_json
    存 dict {erp 列名: 内部字段名 or 'ignore'}。
    """

    __tablename__ = "import_profiles"

    profile_name: Mapped[str] = mapped_column(Text, primary_key=True)
    column_mapping_json: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(Text)


class BacktestRun(Base):
    """阶段 2 回测一次跑的元信息 (plan §2.5)."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str | None] = mapped_column(
        Text, server_default=func.current_timestamp()
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    view: Mapped[str] = mapped_column(Text, nullable=False)  # 'all' / 'base_demand'
    window_train: Mapped[int] = mapped_column(Integer, nullable=False)
    window_test: Mapped[int] = mapped_column(Integer, nullable=False)
    min_weeks: Mapped[int] = mapped_column(Integer, nullable=False)
    n_skus_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    n_skus_scored: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)


class BacktestResult(Base):
    """单 SKU 在一次 run 内的回测分数 (plan §2.5)."""

    __tablename__ = "backtest_results"
    __table_args__ = (
        Index("idx_backtest_results_run_id", "run_id"),
        Index("idx_backtest_results_barcode", "product_barcode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("backtest_runs.id"), nullable=False)
    product_barcode: Mapped[str] = mapped_column(Text, nullable=False)
    sku_type: Mapped[str] = mapped_column(Text, nullable=False)
    n_weeks_train: Mapped[int] = mapped_column(Integer, nullable=False)
    n_weeks_test: Mapped[int] = mapped_column(Integer, nullable=False)
    mape: Mapped[float | None] = mapped_column()
    mase: Mapped[float | None] = mapped_column()
    bias: Mapped[float] = mapped_column(nullable=False)
    coverage_p98: Mapped[float] = mapped_column(nullable=False)
    mean_actual: Mapped[float] = mapped_column(nullable=False)
    mean_predicted: Mapped[float] = mapped_column(nullable=False)


class ForecastOutput(Base):
    """阶段 3.7 per-SKU 最新预测快照 (dashboard 用).

    每 SKU 一行, 刷新时 upsert. 不保留历史快照 (历史回测分数在 backtest_results).
    """

    __tablename__ = "forecast_output"
    __table_args__ = (
        Index("idx_forecast_output_computed_at", "computed_at"),
    )

    product_barcode: Mapped[str] = mapped_column(Text, primary_key=True)
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    sku_type: Mapped[str] = mapped_column(Text, nullable=False)
    n_weeks_history: Mapped[int] = mapped_column(Integer, nullable=False)
    mu: Mapped[float] = mapped_column(nullable=False)
    sigma: Mapped[float] = mapped_column(nullable=False)
    p50: Mapped[float] = mapped_column(nullable=False)
    p98: Mapped[float] = mapped_column(nullable=False)
    computed_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp()
    )


_SessionFactory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine() -> Engine:
    return _engine
