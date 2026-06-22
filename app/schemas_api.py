"""API 响应 pydantic schema（前端独立化 spec §6）。

与 app/schemas.py（dataclass，进程内结构）分开：本模块只描述 HTTP API
契约，是 tools/gen_ts_types.py 的输入。新增 API 端点必须在此声明响应模型。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class BriefingCards(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_health: dict[str, Any]
    restock_risk: dict[str, Any]
    stockout_impact: dict[str, Any]
    overstock_risk: dict[str, Any]
    data_health: dict[str, Any]


class BriefingActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restock: dict[str, Any]
    follow_up: dict[str, Any]
    review_anomalies: dict[str, Any]


class BriefingData(BaseModel):
    """GET /api/briefing/data 响应。card/action 内层形状多态，v1 透传；
    前端组件消费到哪层，类型就加深到哪层（progressive typing）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    generated_at: str
    data_week: str | None
    data_week_complete: bool
    cards: BriefingCards
    actions: BriefingActions


class MeData(BaseModel):
    display_name: str
    is_admin: bool


class ForecastEvalMetrics(BaseModel):
    """headline / by_sku_type / models 共享的聚合指标块（_aggregate_metrics 输出）。"""

    model_config = ConfigDict(extra="forbid")

    n: int
    median_mase: float | None
    beats_naive_pct: float | None
    avg_coverage_p98: float | None


class ForecastEvalByType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_type: str
    n: int
    median_mase: float | None
    beats_naive_pct: float | None
    avg_coverage_p98: float | None


class ForecastEvalModelRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str
    run_id: int
    created_at: str | None
    is_production: bool
    n: int
    median_mase: float | None
    beats_naive_pct: float | None
    avg_coverage_p98: float | None


class ForecastEvalTiers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: int
    medium: int
    low: int


class ForecastEvalData(BaseModel):
    """GET /api/forecast-eval/data 响应。形状对齐
    forecast_eval.build_forecast_eval_dashboard + 路由加的 ok。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    run_id: int | None
    backtest_date: str | None
    forecast_skus: int
    scored_skus: int
    tiers: ForecastEvalTiers
    headline: ForecastEvalMetrics
    by_sku_type: list[ForecastEvalByType]
    models: list[ForecastEvalModelRow]


class HistoryLocSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stores: list[str]
    warehouses: list[str]
    unknown: list[str]


class HistoryChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    old: str | None
    new: str | None
    old_split: HistoryLocSplit | None = None
    new_split: HistoryLocSplit | None = None


class HistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str
    change_type: str | None
    source: str | None
    summary: str | None = None
    changes: list[HistoryChange]


class HistoryCurrent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    model: str
    location: str
    is_active: bool
    source: str | None
    created_at: str | None
    updated_at: str | None
    product_name_zh: str | None
    product_name_local: str | None
    erp_category_raw: str | None
    erp_category_code: str | None
    manual_grade: int | None
    stock_price: float | None
    sale_price: float | None
    is_truly_discontinued: bool
    store_locations: list[str]
    warehouse_locations: list[str]
    unknown_locations: list[str]


class HistoryFuzzyMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    model: str
    location: str | None
    is_active: bool


class HistorySearchData(BaseModel):
    """GET /api/history?q= 的 200 响应。命中/模糊/无 三分支，缺省分支字段 Optional 兜。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    found: bool
    current: HistoryCurrent | None = None
    events: list[HistoryEvent] | None = None
    fuzzy_matches: list[HistoryFuzzyMatch] | None = None


class SkuSalesMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_qty: int
    total_revenue: float
    unique_customers: int
    lifespan_days: int
    trend_slope_pct_per_week: float | None


class SkuPurchaseMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_balance: int
    avg_margin_pct: float | None
    purchase_freq_365d: int
    last_purchase_days_ago: int | None


class SkuCustomerEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty: int
    unique_customers: int
    max_single_qty: int
    last_at: str | None
    avg_freq_per_month: float


class SkuCustomerSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cn: SkuCustomerEnd
    fo: SkuCustomerEnd


class SkuAnalyticsData(BaseModel):
    """GET /api/history/<barcode>/analytics 200 响应（Phase 2a canonical 契约）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    sales: SkuSalesMetrics
    purchase: SkuPurchaseMetrics
    customer_split: SkuCustomerSplit


class PriceStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mean: float | None
    std: float | None
    min: float | None
    max: float | None
    n: int


class TopCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str | None
    customer_type: str
    customer_name: str | None
    qty: int
    last_at: str | None


class RetailSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty: int
    revenue: float
    n_transactions: int
    last_at: str | None
    avg_ticket_qty: float | None


class SkuExtras(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_qty: int
    total_sale_qty_gross: int
    return_rate_pct: float | None
    price_stats: PriceStats
    top_customers_cn: list[TopCustomer]
    top_customers_foreign: list[TopCustomer]
    retail_summary: RetailSummary
    first_event_at: str | None
    last_event_at: str | None
    is_history_truncated: bool


class HoldingData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avg_days: float | None
    n_pairs: int
    oldest_held_days: int | None


class HeatmapData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    years: list[str]
    matrix: dict[str, list[int]]
    max_qty: int

    @field_validator("matrix")
    @classmethod
    def _matrix_12_months(cls, v: dict[str, list[int]]) -> dict[str, list[int]]:
        # HC-B4: 每年严格 12 项, 契约硬守护; 不满足 → ValidationError → 端点 500
        for year, months in v.items():
            if len(months) != 12:
                raise ValueError(f"heatmap matrix[{year}] 必须 12 项, 实际 {len(months)}")
        return v


class ForecastBrief(BaseModel):
    """HC-B5: forecast_output 新消费端, 必带过期 + 缺货剔除信号。"""

    model_config = ConfigDict(extra="forbid")

    quarter_mu: float
    quarter_p98: float
    computed_at: str | None
    is_stale: bool
    stockout_weeks_excluded: int


class UrgencyBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cover: float
    recency: float
    velocity: float
    margin: float
    demand_validity: float | None


class RestockSnapshot(BaseModel):
    """HC-B6: 旧 renderRestockSnapshot 消费字段的显式投影 (非整行透传)。"""

    model_config = ConfigDict(extra="forbid")

    # 财务
    master_sale_price_eur: float | None
    sale_net_avg: float | None
    retail_price_observed: float | None
    retail_price_estimate: float | None
    retail_qty_26w: int
    last_purchase_unit_price: float | None
    master_stock_price_eur: float | None
    margin_pct: float | None
    # 库存
    qty_total: int | None
    inventory_sale_value_eur: float | None
    inventory_cost_value_eur: float | None
    weeks_of_cover: float | None
    # 累计盈亏
    lifetime_invested_eur: float | None
    lifetime_purchase_qty: int
    lifetime_sale_revenue_eur: float
    lifetime_sale_qty: int
    realized_profit_eur: float | None
    net_cashflow_eur: float | None
    inventory_imbalance_pct: float | None
    # 销售 26 周
    weekly_velocity: float
    weekly_revenue: float
    n_active_weeks_26w: int
    last_purchase_days_ago: int | None
    # 紧迫分
    urgency_score: float | None
    urgency_breakdown: UrgencyBreakdown | None


class SkuExtrasResponse(BaseModel):
    """GET /api/history/<barcode>/analytics/extras 200 响应（Phase 2b canonical 契约）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    extras: SkuExtras
    holding: HoldingData
    heatmap: HeatmapData
    forecast: ForecastBrief | None
    restock: RestockSnapshot | None


class TimelineWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: str
    sale_qty: int
    purchase_unit_price: float | None
    raw_unit_price_local: float | None
    currency_local: str


class MonthlySale(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month_start: str
    sale_qty: int
    retail_qty: int


class SkuTimelineResponse(BaseModel):
    """GET /api/history/<barcode>/timeline 200 响应（Phase 3 canonical 契约）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    timeline: list[TimelineWeek]
    monthly_sales: list[MonthlySale]


class RecentChangeBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: int
    taken_at: str | None
    total_local: int | None
    change_count: int
    affected_barcodes: int
    is_open: bool


class RecentChangesBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    batches: list[RecentChangeBatch]


class RecentChangeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_changes: int
    model_changes: int
    inserts: int
    deactivates: int
    reactivates: int
    roundtrip_count: int


class ChangeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barcode: str
    model: str
    field: str
    from_value: str | None
    to_value: str | None
    change_type: str
    at: str


class RecentChangesDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    summary: RecentChangeSummary
    changes: list[ChangeRow]
    total_count: int


class ScanXlsxFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    size_bytes: int


class ScanBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    employee: str
    scanned_at: str
    csv_filename: str | None
    csv_rows: int | None
    csv_size_bytes: int | None
    xlsx_files: list[ScanXlsxFile]


class ScanBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    batches: list[ScanBatch]


class RestockSuppressedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skipped_at: str
    reason: str | None
    days_left: int


class RestockSuppressedList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    items: dict[str, RestockSuppressedEntry]


class RestockItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    model: str | None
    name_zh: str | None
    origin: Literal["FOREIGN", "CN", "unknown"]
    supplier_id: str | None
    is_truly_discontinued: bool
    is_new_item: bool
    qty_total: int | None
    weeks_of_cover: float | None
    weekly_velocity: float
    weekly_revenue: float
    margin_pct: float | None
    margin_source: str | None
    margin_price_source: str | None
    master_stock_price_eur: float | None
    master_sale_price_eur: float | None
    last_purchase_unit_price: float | None
    sale_net_avg: float | None
    weekly_qty_12w: list[int]
    trend_slope_pct_per_week: float | None
    realized_profit_eur: float | None
    inventory_cost_value_eur: float | None
    last_purchase_days_ago: int | None
    last_purchase_at: str | None
    restock_qty_p50: int | None
    restock_qty_p98: int | None
    restock_source: str | None
    last_purchase_qty: int | None
    urgency_score: float | None  # 真实数据为浮点（69.5「次紧迫」），小数位有排序/显示语义
    stockout_zero_weeks_last8: int


class RestockItemList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    total: int
    items: list[RestockItem]


# gen_ts_types.py 的导出清单：新增模型加进来即自动进 types.gen.ts
API_MODELS: list[type[BaseModel]] = [
    BriefingData,
    MeData,
    ForecastEvalData,
    HistorySearchData,
    SkuAnalyticsData,
    SkuExtrasResponse,
    SkuTimelineResponse,
    RecentChangesBatchList,
    RecentChangesDetail,
    ScanBatchList,
    RestockSuppressedList,
    RestockItemList,
]
