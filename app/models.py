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

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
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
)


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
    created_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())
    updated_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())

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
    # ERP 产品总档里的供应商关系. 来源: product_master.py importer 写入.
    # analytics 端取 supplier_id 时优先这个, fallback 到 last_purchase event 的 supplier_id.
    supplier_id: Mapped[str | None] = mapped_column(Text)
    # 最近一次有效采购的折后净价 (unit_price * (1-discount/100)).
    # 来源: parquet_importer 每次导入 purchase event 后回填 (filter qty>0 + unit_price>0).
    # 给毛利近似计算用: (sale_price - last_purchase_unit_price) / sale_price.
    last_purchase_unit_price: Mapped[float | None] = mapped_column()
    # ERP 产品总档 (product_master.stock_price) 折算后的 EUR 兜底进价.
    # FOREIGN 货 stock_price 直接是 EUR (已验), CN/HZ 一律 NULL (海运费混在里面).
    # 仅当 last_purchase_unit_price 为 NULL 时给 margin 兜底用.
    master_stock_price_eur: Mapped[float | None] = mapped_column()

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
    created_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())

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
    created_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())


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


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("idx_po_supplier", "supplier_id"),
        Index("idx_po_order_date", "order_date"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[str | None] = mapped_column(Text, ForeignKey("suppliers.supplier_id"))
    order_date: Mapped[str] = mapped_column(Text, nullable=False)
    arrival_date: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="placed")
    source_file: Mapped[str | None] = mapped_column(Text)
    total_qty: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[float | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))

    lines = relationship("PurchaseOrderLine", back_populates="order", cascade="all, delete-orphan")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        Index("idx_pol_order", "order_id"),
        Index("idx_pol_barcode", "product_barcode"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    product_barcode: Mapped[str] = mapped_column(Text, nullable=False)
    qty_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_arrived: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[float | None] = mapped_column()

    order = relationship("PurchaseOrder", back_populates="lines")


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
    created_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())


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
    created_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())
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


class StockpileInventorySnapshot(Base):
    """库存快照表 (plan §2.3 服务器侧).

    每次抓取 (周一 cron) 写一份 snapshot_date 全量, 保留历史. product_barcode
    不在快照里 (ERP 库存页不导出条码), 通过 product_model JOIN stockpile 反查.
    """

    __tablename__ = "stockpile_inventory_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "product_model",
            name="uq_inventory_snapshot_date_model",
        ),
        Index("idx_inventory_snapshot_date", "snapshot_date"),
        Index("idx_inventory_snapshot_model", "product_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[str] = mapped_column(Text, nullable=False)
    product_model: Mapped[str] = mapped_column(Text, nullable=False)
    product_name_zh: Mapped[str | None] = mapped_column(Text)
    erp_category_code: Mapped[str | None] = mapped_column(Text)
    erp_category_raw: Mapped[str | None] = mapped_column(Text)
    last_purchase_at: Mapped[str | None] = mapped_column(Text)
    last_arrival_at: Mapped[str | None] = mapped_column(Text)
    qty_store: Mapped[int | None] = mapped_column(Integer)
    qty_total: Mapped[int] = mapped_column(Integer, nullable=False)
    reorder_min: Mapped[int | None] = mapped_column(Integer)
    reorder_max: Mapped[int | None] = mapped_column(Integer)
    is_discontinued_in_erp: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    imported_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp()
    )


class ForecastOutput(Base):
    """阶段 3.7 per-SKU 最新预测快照 (dashboard 用).

    每 SKU 一行, 刷新时 upsert. 不保留历史快照 (历史回测分数在 backtest_results).
    """

    __tablename__ = "forecast_output"
    __table_args__ = (Index("idx_forecast_output_computed_at", "computed_at"),)

    product_barcode: Mapped[str] = mapped_column(Text, primary_key=True)
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    sku_type: Mapped[str] = mapped_column(Text, nullable=False)
    n_weeks_history: Mapped[int] = mapped_column(Integer, nullable=False)
    # 置信度分层输入: nonzero_weeks=>0 的周数; zero_weeks_last8=最近 8 周 <=0 的周数;
    # stockout_zero_weeks_last8=其中因缺货(周一快照 qty<=0)导致的零销周数。
    nonzero_weeks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    zero_weeks_last8: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # stockout_zero_weeks_last8 (spec 2026-06-09): 近 8 周里"缺货(周一 qty<=0)且零销"
    # 的周数; 置信度降级减掉它(只看有货零销), 补货页据此标记"疑因缺货"。
    stockout_zero_weeks_last8: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    mu: Mapped[float] = mapped_column(nullable=False)
    sigma: Mapped[float] = mapped_column(nullable=False)
    p50: Mapped[float] = mapped_column(nullable=False)
    p98: Mapped[float] = mapped_column(nullable=False)
    # ADR-0001: 保护期 H = R + L 的 horizon 分位数（bootstrap，RL-1 修复）。
    # 消费端用这两列，不得再用 周分位 × N。p98_13w = 季度展示口径。
    horizon_weeks: Mapped[int | None] = mapped_column(Integer)
    p50_h: Mapped[float | None] = mapped_column()
    p98_h: Mapped[float | None] = mapped_column()
    p98_13w: Mapped[float | None] = mapped_column()
    # RL-3: 本次训练序列里被剔除的缺货周数（置信分层/可解释性消费）。
    stockout_weeks_excluded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    computed_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp()
    )


class SkuSummary(Base):
    """物化的 SKU 汇总快照（货号历史/dashboard 列表提速）。

    每 SKU 一行, payload 存 _list_sku_summary_impl 算出的整个 item dict (JSON)。
    refresh 时整表重写; 读路径查表 + 空表/as_of≠today 回退实时计算。
    不拆字段: 无消费方需按单指标 SQL 过滤, blob 加字段免迁移, PK 单行查快。
    """

    __tablename__ = "sku_summary"
    __table_args__ = (Index("idx_sku_summary_as_of", "as_of"),)

    product_barcode: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp()
    )


class RestockDecision(Base):
    """补货决策反馈快照（P3 数据收集，给算法体检用）。

    每条 = 一次用户决策瞬时快照。analyse 时按 decision 类型聚合:
      - 'ordered' / 'overridden' 区分推荐命中 vs 反向覆盖
      - 'skipped' 含 reason 文本, 找拒绝模式
      - 'stale_high_score' 按需 backfill, 标识算法持续推但未被采纳的 SKU

    存"那一刻"的 urgency_score + breakdown + 原始 dimension 值, 周后回看
    SKU 数据已变, 仍能还原决策上下文.
    """

    __tablename__ = "restock_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    decision: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    decided_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.current_timestamp(), index=True
    )
    urgency_score: Mapped[float | None] = mapped_column()
    velocity_pctile: Mapped[float | None] = mapped_column()
    margin_pctile: Mapped[float | None] = mapped_column()
    breakdown_velocity: Mapped[float | None] = mapped_column()
    breakdown_cover: Mapped[float | None] = mapped_column()
    breakdown_recency: Mapped[float | None] = mapped_column()
    breakdown_margin: Mapped[float | None] = mapped_column()
    margin_source: Mapped[str | None] = mapped_column(Text)
    weekly_revenue: Mapped[float | None] = mapped_column()
    weekly_velocity: Mapped[float | None] = mapped_column()
    margin_pct: Mapped[float | None] = mapped_column()
    weeks_of_cover: Mapped[float | None] = mapped_column()
    origin: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    theme: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'dark'"))
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'admin'"))
    created_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())
    updated_by: Mapped[str | None] = mapped_column(Text)


# ── Attendance ──────────────────────────────────────────────────────


class Employee(Base):
    __tablename__ = "employees"
    employee_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[str | None] = mapped_column(Text)
    active: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text)
    wecom_account: Mapped[str | None] = mapped_column(Text)
    is_scanner: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    attendance_records = relationship(
        "AttendanceRecord", back_populates="employee", cascade="all, delete-orphan"
    )
    leave_records = relationship(
        "LeaveRecord", back_populates="employee", cascade="all, delete-orphan"
    )
    inactive_periods = relationship(
        "InactivePeriod", back_populates="employee", cascade="all, delete-orphan"
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date"),
        Index("idx_attendance_date", "work_date"),
        Index("idx_attendance_emp_month", "employee_id", "work_date"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(
        Text, ForeignKey("employees.employee_id"), nullable=False
    )
    work_date: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[str | None] = mapped_column(Text)
    end_time: Mapped[str | None] = mapped_column(Text)
    work_hours: Mapped[float | None] = mapped_column()
    day_fraction: Mapped[float | None] = mapped_column()
    status: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    employee = relationship("Employee", back_populates="attendance_records")


class LeaveRecord(Base):
    __tablename__ = "leave_records"
    __table_args__ = (
        Index("idx_leave_emp", "employee_id"),
        Index("idx_leave_date", "start_date"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(
        Text, ForeignKey("employees.employee_id"), nullable=False
    )
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    end_date: Mapped[str | None] = mapped_column(Text)
    leave_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="full")
    hours: Mapped[float | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)

    employee = relationship("Employee", back_populates="leave_records")


class InactivePeriod(Base):
    __tablename__ = "inactive_periods"
    __table_args__ = (Index("idx_inactive_emp", "employee_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(
        Text, ForeignKey("employees.employee_id"), nullable=False
    )
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    end_date: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)

    employee = relationship("Employee", back_populates="inactive_periods")


class PublicHoliday(Base):
    __tablename__ = "public_holidays"
    holiday_date: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_paid: Mapped[int] = mapped_column(Integer, default=1)


class SpecialDay(Base):
    __tablename__ = "special_days"
    special_date: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)
    end_time: Mapped[str | None] = mapped_column(Text)


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator_employee_id: Mapped[str] = mapped_column(
        Text, ForeignKey("employees.employee_id"), nullable=False
    )
    operator_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    batch_label: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())
    finalized_at: Mapped[str | None] = mapped_column(Text)

    items = relationship(
        "ScanItem",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ScanItem.seq",
    )


class ScanItem(Base):
    __tablename__ = "scan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_sessions.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    scanned_at: Mapped[str | None] = mapped_column(Text, server_default=func.current_timestamp())

    session = relationship("ScanSession", back_populates="items")

    __table_args__ = (Index("idx_scan_items_session", "session_id", "seq"),)


# engine/session 真源在 app.db；以下为兼容 wrapper(函数内 lazy import 避免循环：
# app.db 顶层 from app.models import Base, SchemaMeta，models 顶层不得 import app.db)。


@contextmanager
def get_session() -> Iterator[Session]:
    from app.db import get_session as _db_get_session

    with _db_get_session() as session:
        yield session


def get_engine() -> Engine:
    from app.db import get_engine as _db_get_engine

    return _db_get_engine()
