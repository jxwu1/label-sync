"""API 响应 pydantic schema（前端独立化 spec §6）。

与 app/schemas.py（dataclass，进程内结构）分开：本模块只描述 HTTP API
契约，是 tools/gen_ts_types.py 的输入。新增 API 端点必须在此声明响应模型。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


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


# gen_ts_types.py 的导出清单：新增模型加进来即自动进 types.gen.ts
API_MODELS: list[type[BaseModel]] = [
    BriefingData,
    MeData,
    ForecastEvalData,
    HistorySearchData,
    SkuAnalyticsData,
]
