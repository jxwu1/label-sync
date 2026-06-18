# 货号历史 Vue Phase 2b 实施 Plan（深度 extras + 热力图 + 补货快照）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `/ui/history` 命中态补上旧版「完整分析」剩余的深度 extras + 月度热力图 + 补货决策快照两个面板，数据走新建独立渐进端点 `GET /api/history/<barcode>/analytics/extras`。

**Architecture:** additive 迁移（旧 SPA 货号历史页不动）。后端瘦端点只调 6 个现成函数 + 显式投影 restock 子集 + strict pydantic 校验；前端独立 `useSkuExtrasStore`（2b 整体一个错误边界，与 P1/2a 隔离）+ P1/2a/2b 三 store 单调 request-id 防 A→B 竞态。

**Tech Stack:** Flask + pydantic（`extra="forbid"` strict schema）+ Vue 3 + Pinia + TypeScript + vitest + pytest。

**Spec:** `docs/superpowers/specs/2026-06-18-history-vue-phase2b-design.md`（HC-B1~B7 硬约束，两轮审查 APPROVE）。

**前置说明（coder 必读）：**
- 分支已在 `feat/history-vue-phase2b`。
- 后端测试：`pytest tests/test_history_extras_api.py -v`（默认 tmp sqlite）。
- 前端测试：`cd frontend && npx vitest run <file>`；类型检查 `cd frontend && npm run typecheck`。
- TS 类型同步：`python tools/gen_ts_types.py`（改 schemas_api.py 后必跑），`--check` 守护漂移。
- 三 store 的 seq 一律定义在 `defineStore` setup 闭包内（**非模块级**），保证 vitest 用例隔离。

---

## Task 1: 后端 pydantic schema + 注册 + TS 类型同步

**Files:**
- Modify: `app/schemas_api.py:11`（import 加 `field_validator`）
- Modify: `app/schemas_api.py:227`（在 `SkuAnalyticsData` 之后追加新模型）
- Modify: `app/schemas_api.py:230-236`（`API_MODELS` 追加 `SkuExtrasResponse`）
- Generated: `frontend/src/api/types.gen.ts`（gen_ts_types 产出，勿手改）

- [ ] **Step 1: 改 import 加 field_validator**

`app/schemas_api.py:11` 原：
```python
from pydantic import BaseModel, ConfigDict
```
改为：
```python
from pydantic import BaseModel, ConfigDict, field_validator
```

- [ ] **Step 2: 追加 schema 模型**

在 `app/schemas_api.py` 的 `SkuAnalyticsData` 类定义结束后（第 227 行 `customer_split: SkuCustomerSplit` 之后空行），追加：

```python
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
    qty_total: int
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
```

- [ ] **Step 3: 注册进 API_MODELS**

`app/schemas_api.py:230-236` 改为：
```python
API_MODELS: list[type[BaseModel]] = [
    BriefingData,
    MeData,
    ForecastEvalData,
    HistorySearchData,
    SkuAnalyticsData,
    SkuExtrasResponse,
]
```

- [ ] **Step 4: 生成 TS 类型并验证导入存在**

Run: `python tools/gen_ts_types.py`
然后 Run: `python tools/gen_ts_types.py --check`
Expected: 第二条退出码 0（无漂移）。

Run: `grep -c "SkuExtrasResponse\|RestockSnapshot\|HeatmapData\|ForecastBrief" frontend/src/api/types.gen.ts`
Expected: 输出 ≥ 4（嵌套模型经 $defs 已进 TS）。

- [ ] **Step 5: 跑 ruff 确保格式干净**

Run: `ruff format app/schemas_api.py && ruff check app/schemas_api.py`
Expected: 无错误。

- [ ] **Step 6: Commit**

```bash
git add app/schemas_api.py frontend/src/api/types.gen.ts
git commit -m "feat(history): Phase 2b extras 端点 pydantic schema + TS 类型"
```

---

## Task 2: 后端 restock 投影 helper + 端点（TDD）

**Files:**
- Modify: `app/routes/history.py`（加 `_project_restock` helper + `analytics_extras` 路由）
- Test: `tests/test_history_extras_api.py`（新建）

- [ ] **Step 1: 写失败测试（端点骨架 + key 集合 + 投影 key）**

新建 `tests/test_history_extras_api.py`。参照 `tests/test_history_analytics_api.py` 的 app fixture / seed 套路（`create_app(seed_auth=False, prewarm=False)` + `app.test_client()`，`/api/*` 带 `X-Upload-Token` 或登录 session；seed 走 `import_from_dataframe` 填 stockpile_locations 子表 + events 插入；forecast_output seed 复用 `tests/test_forecast_eval_dashboard.py` 的 helper，含 NOT NULL 列 model_used/mu/sigma/p50/p98/n_weeks_history）。

```python
def test_extras_unauth_returns_401(app):
    client = app.test_client()
    resp = client.get("/api/history/12345/analytics/extras")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "unauthenticated"


def test_extras_hit_response_key_set(app, seed_sku_with_events):
    # seed_sku_with_events: 一个有 sale+purchase events 的 barcode（fixture 自建）
    bc = seed_sku_with_events
    client = logged_in_client(app)
    resp = client.get(f"/api/history/{bc}/analytics/extras")
    assert resp.status_code == 200
    body = resp.get_json()
    # HC-B2: key 恰好这 6 个, 不含 2a 的 sales/purchase/customer_split
    assert set(body.keys()) == {"ok", "extras", "holding", "heatmap", "forecast", "restock"}
    assert "sales" not in body and "purchase" not in body and "customer_split" not in body


def test_restock_projection_key_set(app, seed_sku_with_events):
    # HC-B6: restock 投影后只含 RestockSnapshot 字段, 不透传 sku_summary 整行
    bc = seed_sku_with_events
    client = logged_in_client(app)
    body = client.get(f"/api/history/{bc}/analytics/extras").get_json()
    if body["restock"] is not None:
        leaked = {"supplier_id", "cn_qty", "fo_qty", "weekly_qty_12w", "barcode", "model"}
        assert leaked.isdisjoint(body["restock"].keys())
        assert "urgency_breakdown" in body["restock"]
```

> coder：fixture（`app` / `seed_sku_with_events` / `logged_in_client`）按 `tests/test_history_analytics_api.py` 现有写法照搬，不重复发明。若该文件用模块级 helper，import 复用。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_history_extras_api.py -v`
Expected: FAIL（路由 404 / 端点不存在）。

- [ ] **Step 3: 实现投影 helper + 端点**

在 `app/routes/history.py` 顶部 import 区补（按现有风格，放函数内 import 亦可）。在 `api_bp` 蓝图上加：

```python
# Phase 2b: restock 显式投影字段集（HC-B6, 逐字段对齐 summary.py 行）
_RESTOCK_PROJECTION_KEYS = (
    "master_sale_price_eur", "sale_net_avg", "retail_price_observed",
    "retail_price_estimate", "retail_qty_26w", "last_purchase_unit_price",
    "master_stock_price_eur", "margin_pct", "qty_total",
    "inventory_sale_value_eur", "inventory_cost_value_eur", "weeks_of_cover",
    "lifetime_invested_eur", "lifetime_purchase_qty", "lifetime_sale_revenue_eur",
    "lifetime_sale_qty", "realized_profit_eur", "net_cashflow_eur",
    "inventory_imbalance_pct", "weekly_velocity", "weekly_revenue",
    "n_active_weeks_26w", "last_purchase_days_ago", "urgency_score",
    "urgency_breakdown",
)


def _project_restock(row: dict) -> dict:
    """HC-B6: 从 list_sku_summary 整行投影出 RestockSnapshot 字段子集。"""
    return {k: row.get(k) for k in _RESTOCK_PROJECTION_KEYS}


@api_bp.get("/<barcode>/analytics/extras")
def analytics_extras(barcode: str):
    from app.schemas_api import SkuExtrasResponse
    from app.services import analytics as analytics_service
    from app.services.analytics._shared import _today
    from app.services.forecast_eval import forecast_is_stale

    bc = barcode.strip()
    rows = analytics_service.fetch_event_rows(bc)  # HC-B2: 取一次喂 extras/holding/heatmap
    extras = analytics_service.compute_sku_extras(bc, rows=rows)
    holding = analytics_service.compute_avg_holding_days(bc, rows=rows)
    heatmap = analytics_service.compute_monthly_heatmap(bc, rows=rows)
    fc = analytics_service.compute_forecast_snapshot(bc)
    restock_full = analytics_service.compute_restock_snapshot(bc)

    forecast_brief = None
    if fc is not None:
        forecast_brief = {
            "quarter_mu": fc["quarter_mu"],
            "quarter_p98": fc["quarter_p98"],
            "computed_at": fc["computed_at"],
            "is_stale": forecast_is_stale(fc["computed_at"], _today()),  # HC-B5 / RL-9
            "stockout_weeks_excluded": fc["stockout_weeks_excluded"],    # HC-B5 / RL-3
        }

    restock_brief = _project_restock(restock_full) if restock_full is not None else None

    payload = {
        "ok": True,
        "extras": extras,
        "holding": holding,
        "heatmap": heatmap,
        "forecast": forecast_brief,
        "restock": restock_brief,
    }
    return jsonify(SkuExtrasResponse.model_validate(payload).model_dump())
```

> coder：确认 `api_bp` 已 import `jsonify`（P1 端点已用）。`fetch_event_rows` 经 `analytics_service` 导出（analytics.py 现有 `analytics_service.fetch_event_rows` 用法）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_history_extras_api.py -v`
Expected: 3 个测试 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/routes/history.py tests/test_history_extras_api.py
git commit -m "feat(history): Phase 2b extras 端点 + restock 显式投影"
```

---

## Task 3: 后端端点补全测试（forecast/restock 分支 + 原子失败 + heatmap validator + fetch 次数）

**Files:**
- Modify: `tests/test_history_extras_api.py`

- [ ] **Step 1: 加分支与边界测试**

```python
def test_forecast_none_when_no_output(app, seed_sku_without_forecast):
    bc = seed_sku_without_forecast  # seed stockpile + events 但不 seed forecast_output
    body = logged_in_client(app).get(f"/api/history/{bc}/analytics/extras").get_json()
    assert body["forecast"] is None


def test_forecast_is_stale_flag(app, seed_sku_stale_forecast):
    # seed forecast_output.computed_at 距今 > 14 天
    bc = seed_sku_stale_forecast
    body = logged_in_client(app).get(f"/api/history/{bc}/analytics/extras").get_json()
    assert body["forecast"]["is_stale"] is True


def test_forecast_fresh_flag(app, seed_sku_fresh_forecast):
    # seed forecast_output.computed_at 距今 <= 14 天
    bc = seed_sku_fresh_forecast
    body = logged_in_client(app).get(f"/api/history/{bc}/analytics/extras").get_json()
    assert body["forecast"]["is_stale"] is False


def test_heatmap_12_months_each_year(app, seed_sku_with_events):
    bc = seed_sku_with_events
    body = logged_in_client(app).get(f"/api/history/{bc}/analytics/extras").get_json()
    for year, months in body["heatmap"]["matrix"].items():
        assert len(months) == 12, year


def test_heatmap_validator_rejects_non_12(app, seed_sku_with_events, monkeypatch):
    # HC-B4: mock compute_monthly_heatmap 返回 11 项 → ValidationError → 500
    from app.services import analytics as analytics_service

    monkeypatch.setattr(
        analytics_service, "compute_monthly_heatmap",
        lambda *a, **k: {"years": ["2026"], "matrix": {"2026": [0] * 11}, "max_qty": 0},
    )
    bc = seed_sku_with_events
    resp = logged_in_client(app).get(f"/api/history/{bc}/analytics/extras")
    assert resp.status_code == 500


def test_fetch_event_rows_called_once(app, seed_sku_with_events, monkeypatch):
    # HC-B2: extras/holding/heatmap 复用同一 rows
    from app.services import analytics as analytics_service

    calls = {"n": 0}
    orig = analytics_service.fetch_event_rows

    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(analytics_service, "fetch_event_rows", counting)
    bc = seed_sku_with_events
    logged_in_client(app).get(f"/api/history/{bc}/analytics/extras")
    assert calls["n"] == 1


import pytest


@pytest.mark.parametrize(
    "fn_name",
    [
        "fetch_event_rows", "compute_sku_extras", "compute_avg_holding_days",
        "compute_monthly_heatmap", "compute_forecast_snapshot", "compute_restock_snapshot",
    ],
)
def test_atomic_failure_any_function_raises_500(app, seed_sku_with_events, monkeypatch, fn_name):
    # HC-B3: 六个数据函数任一抛错 → 整请求 500（2b 原子失败）
    from app.services import analytics as analytics_service

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(analytics_service, fn_name, boom)
    bc = seed_sku_with_events
    resp = logged_in_client(app).get(f"/api/history/{bc}/analytics/extras")
    assert resp.status_code == 500
```

> coder：`monkeypatch.setattr(analytics_service, name, ...)` 要 patch 到端点实际调用的命名空间。端点用 `analytics_service.compute_*`，故 patch `app.services.analytics` 包的属性即可（确认这些函数在包 `__init__` re-export；若端点从子模块直接 import 则 patch 对应子模块）。若 patch 不生效，改 patch `app.routes.history` 内引用名。

- [ ] **Step 2: 跑测试确认通过**

Run: `pytest tests/test_history_extras_api.py -v`
Expected: 全部 PASS（含 6 个 parametrize 原子失败用例）。

- [ ] **Step 3: 跑全后端确认无回归**

Run: `pytest tests/ -q`
Expected: 全绿（2a 的 `test_history_analytics_api.py` 不受影响）。

- [ ] **Step 4: Commit**

```bash
git add tests/test_history_extras_api.py
git commit -m "test(history): Phase 2b 端点分支/原子失败/validator/fetch 次数覆盖"
```

---

## Task 4: 前端 VM 类型 + normalize（TDD）

**Files:**
- Create: `frontend/src/pages/history/extras-types.ts`
- Create: `frontend/src/pages/history/extras-normalize.ts`
- Test: `frontend/src/pages/history/extras-normalize.test.ts`

- [ ] **Step 1: 写 VM 类型**

`frontend/src/pages/history/extras-types.ts`：
```typescript
export interface PriceStatsVM {
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  n: number;
}
export interface TopCustomerVM {
  customerId: string | null;
  customerType: string;
  customerName: string | null;
  qty: number;
  lastAt: string | null;
}
export interface RetailSummaryVM {
  qty: number;
  revenue: number;
  nTransactions: number;
  lastAt: string | null;
  avgTicketQty: number | null;
}
export interface ExtrasVM {
  returnQty: number;
  totalSaleQtyGross: number;
  returnRatePct: number | null;
  priceStats: PriceStatsVM;
  topCustomersCn: TopCustomerVM[];
  topCustomersForeign: TopCustomerVM[];
  retailSummary: RetailSummaryVM;
  firstEventAt: string | null;
  lastEventAt: string | null;
  isHistoryTruncated: boolean;
}
export interface HoldingVM {
  avgDays: number | null;
  nPairs: number;
  oldestHeldDays: number | null;
}
export interface HeatmapVM {
  years: string[];
  matrix: Record<string, number[]>; // 每年恰 12 项
  maxQty: number;
}
export interface ForecastBriefVM {
  quarterMu: number;
  quarterP98: number;
  computedAt: string | null;
  isStale: boolean;
  stockoutWeeksExcluded: number;
}
export interface UrgencyBreakdownVM {
  cover: number;
  recency: number;
  velocity: number;
  margin: number;
  demandValidity: number | null;
}
export interface RestockVM {
  masterSalePriceEur: number | null;
  saleNetAvg: number | null;
  retailPriceObserved: number | null;
  retailPriceEstimate: number | null;
  retailQty26w: number;
  lastPurchaseUnitPrice: number | null;
  masterStockPriceEur: number | null;
  marginPct: number | null;
  qtyTotal: number;
  inventorySaleValueEur: number | null;
  inventoryCostValueEur: number | null;
  weeksOfCover: number | null;
  lifetimeInvestedEur: number | null;
  lifetimePurchaseQty: number;
  lifetimeSaleRevenueEur: number;
  lifetimeSaleQty: number;
  realizedProfitEur: number | null;
  netCashflowEur: number | null;
  inventoryImbalancePct: number | null;
  weeklyVelocity: number;
  weeklyRevenue: number;
  nActiveWeeks26w: number;
  lastPurchaseDaysAgo: number | null;
  urgencyScore: number | null;
  urgencyBreakdown: UrgencyBreakdownVM | null;
}
export interface ExtrasPageVM {
  extras: ExtrasVM;
  holding: HoldingVM;
  heatmap: HeatmapVM;
  forecast: ForecastBriefVM | null;
  restock: RestockVM | null;
}
```

- [ ] **Step 2: 写失败测试**

`frontend/src/pages/history/extras-normalize.test.ts`（参照现有 `analytics-normalize.test.ts` 结构）：
```typescript
import { describe, it, expect } from "vitest";
import { normalizeExtras } from "./extras-normalize";
import type { SkuExtrasResponse } from "../../api/types.gen";

const base: SkuExtrasResponse = {
  ok: true,
  extras: {
    return_qty: 2, total_sale_qty_gross: 100, return_rate_pct: 1.96,
    price_stats: { mean: 5.5, std: 0.2, min: 5, max: 6, n: 10 },
    top_customers_cn: [{ customer_id: "c1", customer_type: "chinese", customer_name: "张三", qty: 50, last_at: "2025-01-01" }],
    top_customers_foreign: [],
    retail_summary: { qty: 3, revenue: 30, n_transactions: 2, last_at: "2025-02-01", avg_ticket_qty: 1.5 },
    first_event_at: "2021-01-01", last_event_at: "2025-02-01", is_history_truncated: true,
  },
  holding: { avg_days: 30.5, n_pairs: 40, oldest_held_days: 90 },
  heatmap: { years: ["2025", "2026"], matrix: { "2025": Array(12).fill(0), "2026": Array(12).fill(0) }, max_qty: 0 },
  forecast: { quarter_mu: 13, quarter_p98: 26, computed_at: "2026-06-01", is_stale: false, stockout_weeks_excluded: 1 },
  restock: null,
};

describe("normalizeExtras", () => {
  it("maps snake_case to camelCase", () => {
    const vm = normalizeExtras(base);
    expect(vm.extras.returnRatePct).toBe(1.96);
    expect(vm.extras.topCustomersCn[0].customerName).toBe("张三");
    expect(vm.forecast?.stockoutWeeksExcluded).toBe(1);
    expect(vm.restock).toBeNull();
  });

  it("pads each heatmap year to exactly 12 months", () => {
    const raw = { ...base, heatmap: { years: ["2026"], matrix: { "2026": [1, 2, 3] }, max_qty: 3 } } as unknown as SkuExtrasResponse;
    const vm = normalizeExtras(raw);
    expect(vm.heatmap.matrix["2026"]).toHaveLength(12);
    expect(vm.heatmap.matrix["2026"].slice(3)).toEqual(Array(9).fill(0));
  });

  it("defaults maxQty to 0 when missing", () => {
    const raw = { ...base, heatmap: { years: [], matrix: {}, max_qty: undefined } } as unknown as SkuExtrasResponse;
    const vm = normalizeExtras(raw);
    expect(vm.heatmap.maxQty).toBe(0);
  });

  it("maps restock projection when present", () => {
    const raw = { ...base, restock: {
      master_sale_price_eur: 10, sale_net_avg: null, retail_price_observed: null,
      retail_price_estimate: null, retail_qty_26w: 0, last_purchase_unit_price: 5,
      master_stock_price_eur: null, margin_pct: 50, qty_total: 100,
      inventory_sale_value_eur: 1000, inventory_cost_value_eur: 500, weeks_of_cover: 8.5,
      lifetime_invested_eur: 500, lifetime_purchase_qty: 100, lifetime_sale_revenue_eur: 900,
      lifetime_sale_qty: 90, realized_profit_eur: 400, net_cashflow_eur: 400,
      inventory_imbalance_pct: 10, weekly_velocity: 2, weekly_revenue: 20,
      n_active_weeks_26w: 12, last_purchase_days_ago: 30, urgency_score: 75,
      urgency_breakdown: { cover: 20, recency: 5, velocity: 25, margin: 25, demand_validity: 1 },
    } } as SkuExtrasResponse;
    const vm = normalizeExtras(raw);
    expect(vm.restock?.weeksOfCover).toBe(8.5);
    expect(vm.restock?.urgencyBreakdown?.demandValidity).toBe(1);
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/history/extras-normalize.test.ts`
Expected: FAIL（normalizeExtras 不存在）。

- [ ] **Step 4: 实现 normalize**

`frontend/src/pages/history/extras-normalize.ts`：
```typescript
import type { SkuExtrasResponse } from "../../api/types.gen";
import type {
  ExtrasPageVM, TopCustomerVM, ForecastBriefVM, RestockVM,
} from "./extras-types";

function num(v: number | null | undefined): number {
  return typeof v === "number" ? v : 0;
}

function topCustomers(rows: SkuExtrasResponse["extras"]["top_customers_cn"]): TopCustomerVM[] {
  return (rows ?? []).map((c) => ({
    customerId: c.customer_id ?? null,
    customerType: c.customer_type,
    customerName: c.customer_name ?? null,
    qty: num(c.qty),
    lastAt: c.last_at ?? null,
  }));
}

export function normalizeExtras(raw: SkuExtrasResponse): ExtrasPageVM {
  const e = raw.extras;
  const ps = e.price_stats;
  const rs = e.retail_summary;
  const h = raw.holding;
  const hm = raw.heatmap;

  // HC-B4 纵深防御: 每年恰 12 项
  const matrix: Record<string, number[]> = {};
  for (const [year, months] of Object.entries(hm?.matrix ?? {})) {
    matrix[year] = Array.from({ length: 12 }, (_, i) => num((months as number[])[i]));
  }

  const fc: ForecastBriefVM | null = raw.forecast
    ? {
        quarterMu: num(raw.forecast.quarter_mu),
        quarterP98: num(raw.forecast.quarter_p98),
        computedAt: raw.forecast.computed_at ?? null,
        isStale: raw.forecast.is_stale,
        stockoutWeeksExcluded: num(raw.forecast.stockout_weeks_excluded),
      }
    : null;

  const r = raw.restock;
  const restock: RestockVM | null = r
    ? {
        masterSalePriceEur: r.master_sale_price_eur ?? null,
        saleNetAvg: r.sale_net_avg ?? null,
        retailPriceObserved: r.retail_price_observed ?? null,
        retailPriceEstimate: r.retail_price_estimate ?? null,
        retailQty26w: num(r.retail_qty_26w),
        lastPurchaseUnitPrice: r.last_purchase_unit_price ?? null,
        masterStockPriceEur: r.master_stock_price_eur ?? null,
        marginPct: r.margin_pct ?? null,
        qtyTotal: num(r.qty_total),
        inventorySaleValueEur: r.inventory_sale_value_eur ?? null,
        inventoryCostValueEur: r.inventory_cost_value_eur ?? null,
        weeksOfCover: r.weeks_of_cover ?? null,
        lifetimeInvestedEur: r.lifetime_invested_eur ?? null,
        lifetimePurchaseQty: num(r.lifetime_purchase_qty),
        lifetimeSaleRevenueEur: num(r.lifetime_sale_revenue_eur),
        lifetimeSaleQty: num(r.lifetime_sale_qty),
        realizedProfitEur: r.realized_profit_eur ?? null,
        netCashflowEur: r.net_cashflow_eur ?? null,
        inventoryImbalancePct: r.inventory_imbalance_pct ?? null,
        weeklyVelocity: num(r.weekly_velocity),
        weeklyRevenue: num(r.weekly_revenue),
        nActiveWeeks26w: num(r.n_active_weeks_26w),
        lastPurchaseDaysAgo: r.last_purchase_days_ago ?? null,
        urgencyScore: r.urgency_score ?? null,
        urgencyBreakdown: r.urgency_breakdown
          ? {
              cover: num(r.urgency_breakdown.cover),
              recency: num(r.urgency_breakdown.recency),
              velocity: num(r.urgency_breakdown.velocity),
              margin: num(r.urgency_breakdown.margin),
              demandValidity: r.urgency_breakdown.demand_validity ?? null,
            }
          : null,
      }
    : null;

  return {
    extras: {
      returnQty: num(e.return_qty),
      totalSaleQtyGross: num(e.total_sale_qty_gross),
      returnRatePct: e.return_rate_pct ?? null,
      priceStats: {
        mean: ps.mean ?? null, std: ps.std ?? null,
        min: ps.min ?? null, max: ps.max ?? null, n: num(ps.n),
      },
      topCustomersCn: topCustomers(e.top_customers_cn),
      topCustomersForeign: topCustomers(e.top_customers_foreign),
      retailSummary: {
        qty: num(rs.qty), revenue: num(rs.revenue),
        nTransactions: num(rs.n_transactions),
        lastAt: rs.last_at ?? null, avgTicketQty: rs.avg_ticket_qty ?? null,
      },
      firstEventAt: e.first_event_at ?? null,
      lastEventAt: e.last_event_at ?? null,
      isHistoryTruncated: e.is_history_truncated,
    },
    holding: { avgDays: h.avg_days ?? null, nPairs: num(h.n_pairs), oldestHeldDays: h.oldest_held_days ?? null },
    heatmap: { years: hm?.years ?? [], matrix, maxQty: num(hm?.max_qty) },
    forecast: fc,
    restock,
  };
}
```

- [ ] **Step 5: 跑测试 + 类型检查确认通过**

Run: `cd frontend && npx vitest run src/pages/history/extras-normalize.test.ts && npm run typecheck`
Expected: 测试 PASS + typecheck 0 错误。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/history/extras-types.ts frontend/src/pages/history/extras-normalize.ts frontend/src/pages/history/extras-normalize.test.ts
git commit -m "feat(history): Phase 2b extras VM 类型 + normalize"
```

---

## Task 5: 前端 useSkuExtrasStore（TDD，含 HC-B7 stale/reset 防护）

**Files:**
- Create: `frontend/src/stores/skuExtras.ts`
- Test: `frontend/src/stores/skuExtras.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/stores/skuExtras.test.ts`（参照 `skuAnalytics.test.ts`，用 `setActivePinia(createPinia())`，mock `apiGet`）：
```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";

const apiGet = vi.fn();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiGet: (...a: unknown[]) => apiGet(...a) };
});

import { useSkuExtrasStore } from "./skuExtras";
import { UnauthenticatedError } from "../api/client";

const okPayload = {
  ok: true,
  extras: { return_qty: 0, total_sale_qty_gross: 0, return_rate_pct: null,
    price_stats: { mean: null, std: null, min: null, max: null, n: 0 },
    top_customers_cn: [], top_customers_foreign: [],
    retail_summary: { qty: 0, revenue: 0, n_transactions: 0, last_at: null, avg_ticket_qty: null },
    first_event_at: null, last_event_at: null, is_history_truncated: false },
  holding: { avg_days: null, n_pairs: 0, oldest_held_days: null },
  heatmap: { years: [], matrix: {}, max_qty: 0 },
  forecast: null, restock: null,
};

beforeEach(() => { setActivePinia(createPinia()); apiGet.mockReset(); });

describe("useSkuExtrasStore", () => {
  it("load fills vm and calls right endpoint", async () => {
    apiGet.mockResolvedValueOnce(okPayload);
    const s = useSkuExtrasStore();
    await s.load("12345");
    expect(apiGet).toHaveBeenCalledWith("/api/history/12345/analytics/extras");
    expect(s.vm).not.toBeNull();
  });

  it("load failure fills error", async () => {
    apiGet.mockRejectedValueOnce(new Error("boom"));
    const s = useSkuExtrasStore();
    await s.load("12345");
    expect(s.error).toBe("boom");
    expect(s.vm).toBeNull();
  });

  it("swallows UnauthenticatedError (error stays null)", async () => {
    apiGet.mockRejectedValueOnce(new UnauthenticatedError());
    const s = useSkuExtrasStore();
    await s.load("12345");
    expect(s.error).toBeNull();
  });

  it("old vm cleared when new load fails", async () => {
    apiGet.mockResolvedValueOnce(okPayload);
    const s = useSkuExtrasStore();
    await s.load("A");
    expect(s.vm).not.toBeNull();
    apiGet.mockRejectedValueOnce(new Error("x"));
    await s.load("B");
    expect(s.vm).toBeNull();
  });

  it("HC-B7 stale: A resolves after B, B wins (A does not write)", async () => {
    let resolveA: (v: unknown) => void = () => {};
    apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; })); // A pending
    apiGet.mockResolvedValueOnce({ ...okPayload, extras: { ...okPayload.extras, return_qty: 999 } }); // B
    const s = useSkuExtrasStore();
    const pA = s.load("A");
    const pB = s.load("B");
    await pB;                       // B resolves first
    resolveA(okPayload);           // A resolves late
    await pA;
    expect(s.vm?.extras.returnQty).toBe(999); // B's data, not A
  });

  it("HC-B7 reset cancels pending (resolve after reset does not write)", async () => {
    let resolveA: (v: unknown) => void = () => {};
    apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
    const s = useSkuExtrasStore();
    const pA = s.load("A");
    s.reset();
    resolveA(okPayload);
    await pA;
    expect(s.vm).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/skuExtras.test.ts`
Expected: FAIL（skuExtras 不存在）。

- [ ] **Step 3: 实现 store**

`frontend/src/stores/skuExtras.ts`（seq 在闭包内）：
```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { SkuExtrasResponse } from "../api/types.gen";
import { normalizeExtras } from "../pages/history/extras-normalize";
import type { ExtrasPageVM } from "../pages/history/extras-types";

export const useSkuExtrasStore = defineStore("skuExtras", () => {
  const vm = ref<ExtrasPageVM | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  let seq = 0; // HC-B7 单调 request-id（闭包级，测试隔离）

  async function load(barcode: string) {
    const my = ++seq;
    loading.value = true;
    error.value = null;
    vm.value = null;
    try {
      const raw = await apiGet<SkuExtrasResponse>(
        `/api/history/${encodeURIComponent(barcode)}/analytics/extras`,
      );
      if (my !== seq) return; // stale 成功：更晚 load/reset 已发起
      vm.value = normalizeExtras(raw);
    } catch (e) {
      if (my !== seq) return; // stale 失败
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === seq) loading.value = false;
    }
  }

  function reset() {
    seq++; // HC-B7: 作废 pending，reset 后旧响应不回写
    vm.value = null;
    error.value = null;
    loading.value = false;
  }

  return { vm, loading, error, load, reset };
});
```

- [ ] **Step 4: 跑测试 + typecheck 确认通过**

Run: `cd frontend && npx vitest run src/stores/skuExtras.test.ts && npm run typecheck`
Expected: 全 PASS + typecheck 0 错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/skuExtras.ts frontend/src/stores/skuExtras.test.ts
git commit -m "feat(history): Phase 2b useSkuExtrasStore（含 stale/reset 并发防护）"
```

---

## Task 6: 回填 useSkuAnalyticsStore 并发守卫（HC-B7，TDD）

**Files:**
- Modify: `frontend/src/stores/skuAnalytics.ts`
- Modify: `frontend/src/stores/skuAnalytics.test.ts`

- [ ] **Step 1: 加失败测试**

在 `skuAnalytics.test.ts` 追加（沿用该文件现有 mock 套路）：
```typescript
it("HC-B7 stale: A resolves after B, B wins", async () => {
  let resolveA: (v: unknown) => void = () => {};
  apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
  apiGet.mockResolvedValueOnce(/* B payload, 与 A 可辨 */);
  const s = useSkuAnalyticsStore();
  const pA = s.load("A");
  const pB = s.load("B");
  await pB;
  resolveA(/* A payload */);
  await pA;
  // 断言 vm 是 B 的数据（按该文件 payload 形状选一个可辨字段）
});

it("HC-B7 reset cancels pending", async () => {
  let resolveA: (v: unknown) => void = () => {};
  apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
  const s = useSkuAnalyticsStore();
  const pA = s.load("A");
  s.reset();
  resolveA(/* A payload */);
  await pA;
  expect(s.vm).toBeNull();
});
```
> coder：A/B payload 用该文件已有的 fixture 形状（`SkuAnalyticsData`），选 `sales.total_qty` 之类可辨字段断言 B 赢。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/skuAnalytics.test.ts`
Expected: 新增两用例 FAIL（当前无 seq 守卫，A 会覆盖 B / reset 后回写）。

- [ ] **Step 3: 改 store 加 seq 守卫**

`frontend/src/stores/skuAnalytics.ts`：在 setup 闭包加 `let seq = 0;`；`load` 开头 `const my = ++seq;`；三处写入分支前加 `if (my !== seq) return;`（成功写 vm 前、catch 写 error 前、finally 落 loading 改 `if (my === seq) loading.value = false;`）；`reset()` 开头加 `seq++;`。**不改其它行为**。

- [ ] **Step 4: 跑测试 + typecheck 确认通过**

Run: `cd frontend && npx vitest run src/stores/skuAnalytics.test.ts && npm run typecheck`
Expected: 全 PASS（含原有用例无回归）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/skuAnalytics.ts frontend/src/stores/skuAnalytics.test.ts
git commit -m "fix(history): 2a useSkuAnalyticsStore 回填 stale/reset 并发守卫（HC-B7）"
```

---

## Task 7: 回填 useHistoryStore 竞态根因修复（HC-B7 BLOCKER，TDD）

**Files:**
- Modify: `frontend/src/stores/history.ts`
- Modify: `frontend/src/stores/history.test.ts`

- [ ] **Step 1: 加失败测试**

在 `history.test.ts` 追加（沿用现有 mock）：
```typescript
it("HC-B7: A resolves after B, result stays B", async () => {
  let resolveA: (v: unknown) => void = () => {};
  apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; })); // A pending
  apiGet.mockResolvedValueOnce(/* B 命中 payload */);                          // B
  const s = useHistoryStore();
  const pA = s.load("A");
  const pB = s.load("B");
  await pB;
  resolveA(/* A 命中 payload，barcode 与 B 不同 */);
  await pA;
  // 断言 result 是 B（按 normalize 后 current.barcode 辨）
});

it("load returns true for latest, false for superseded", async () => {
  let resolveA: (v: unknown) => void = () => {};
  apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
  apiGet.mockResolvedValueOnce(/* B payload */);
  const s = useHistoryStore();
  const pA = s.load("A");
  const freshB = await s.load("B");
  resolveA(/* A payload */);
  const freshA = await pA;
  expect(freshB).toBe(true);
  expect(freshA).toBe(false);
});

it("HC-B7 reset cancels pending (resolve after reset does not write)", async () => {
  let resolveA: (v: unknown) => void = () => {};
  apiGet.mockImplementationOnce(() => new Promise((r) => { resolveA = r; }));
  const s = useHistoryStore();
  const pA = s.load("A");
  s.reset();
  resolveA(/* A payload */);
  await pA;
  expect(s.result).toBeNull();
});
```
> coder：payload 用 `history.test.ts` 现有 fixture（`HistorySearchData` 命中形状），A/B 用不同 barcode 辨别。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/history.test.ts`
Expected: 新增用例 FAIL。

- [ ] **Step 3: 改 store**

`frontend/src/stores/history.ts` 改 `load` + `reset`（见 spec「P1 store 回填」段，逐字落地）：
- setup 闭包加 `let seq = 0;`
- `load` 签名改 `async function load(q: string): Promise<boolean>`；开头 `const my = ++seq;`；成功写 result 前 `if (my !== seq) return false;`；catch 两分支 `if (my !== seq) return false;` / `if (e instanceof UnauthenticatedError) return false;`；finally `if (my === seq) loading.value = false;`；函数末 `return my === seq;`
- `reset()` 开头加 `seq++;`

- [ ] **Step 4: 跑测试 + typecheck 确认通过**

Run: `cd frontend && npx vitest run src/stores/history.test.ts && npm run typecheck`
Expected: 全 PASS（原有用例无回归）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/history.ts frontend/src/stores/history.test.ts
git commit -m "fix(history): P1 useHistoryStore 竞态根因修复（seq 守卫 + load 返回最新 + reset 作废）"
```

---

## Task 8: HistoryPage 渲染两面板 + runSearch 门控（TDD）

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue`
- Modify: `frontend/src/pages/history/HistoryPage.test.ts`

- [ ] **Step 1: 加失败测试**

在 `HistoryPage.test.ts` 追加（沿用现有 mock store 套路 = plain object，非真 pinia；参照 2a 扩展用例）：
```typescript
it("hit triggers extrasStore.load and renders both panels", async () => {
  // mock useHistoryStore.load 返回 true + result.kind='hit'
  // mock extrasStore.vm = 完整 ExtrasPageVM
  // 断言 extrasStore.load 被调 + 退货率/热力图/补货面板文案出现
});

it("extras failure shows 2b error but P1+2a still render", async () => {
  // extrasStore.error 置位, extrasStore.vm=null
  // 断言 2b 错误条出现, 且 hero/概况/历史时间线 + SLA/PUR 仍渲染（HC-B3）
});

it("extras 401 shows no block error", async () => {
  // extrasStore.error=null（store 已吞）→ 断言无 2b 错误条
});

it("forecast null shows 未训出; isStale shows 过期徽标", async () => {
  // 两个子用例或参数化
});

it("restock null hides restock panel", async () => {});

it("heatmap renders 12 cells per row; maxQty=0 all dash", async () => {});

it("non-hit calls extrasStore.reset and hides panels", async () => {});

it("HC-B7 gating: stale search (load returns false) does NOT call downstream loads", async () => {
  // mock store.load 返回 false → 断言 analyticsStore.load / extrasStore.load 未被调
});
```
> coder：HistoryPage 既有测试 mock store 为 plain object（见现文件 + memory 范式）。新用例延续。断言文案用旧版可辨字符串（如「退货率」「月度热力图」「补货决策」「预测过期」「序列太短未训出」）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts`
Expected: 新增用例 FAIL。

- [ ] **Step 3: 改 HistoryPage.vue**

1. `<script setup>` import `useSkuExtrasStore` + `extrasStore = useSkuExtrasStore()`。
2. runSearch 门控（替换现有命中触发段，HC-B7）：
```typescript
const fresh = await store.load(query);
if (!fresh) return; // HC-B7: 本次搜索已被超越，不写下游
if (!store.error && store.result?.kind === "hit") {
  pushRecent(query);
  const bc = store.result.current.barcode;
  analyticsStore.load(bc);
  extrasStore.load(bc);
} else {
  analyticsStore.reset();
  extrasStore.reset();
}
```
3. `doReset()` 并列 `extrasStore.reset();`
4. 模板：在 2a 分析块之后、历史时间线之前，加 **两个面板**（仅 `store.result?.kind === "hit"` 时容器显示）：
   - 子状态：`extrasStore.loading` → 「深度分析加载中…」；`extrasStore.error` → 2b 错误条（不裹 P1/2a）。
   - `extrasStore.vm` 就绪时渲染：
     - **Extras 面板**子段顺序（1:1 复刻旧 `renderExtras`）：退货率+价格波动 → 零售汇总 → CN 客户 TOP（mini-table）→ 老外客户 TOP → 🌡 月度热力图（HTML `<table>`）→ 持仓/下季度预测/数据范围。
       - 热力图：表头空格 + 1..12 月；每行 = 年份 + 12 格；格 `q>0` 显数字、`q===0` 显 `—`；背景 intensity = `maxQty>0 ? max(0.12, q/maxQty) : 0`（HC-B4：maxQty=0 不除零、全 `—`）。
       - forecast 段：`vm.forecast===null` → 「序列太短未训出」；否则显「下季度预测 {quarterMu}（p98 {quarterP98}）」+ `forecast.isStale` → 「⚠ 预测过期」徽标 + `forecast.stockoutWeeksExcluded>0` → 「缺货周剔除 {n}」提示（HC-B5）。
       - 数据范围：`firstEventAt ~ lastEventAt` + `isHistoryTruncated` → 「⚠ 不全」。
     - **补货快照面板**（1:1 复刻旧 `renderRestockSnapshot`）：`vm.restock===null` → 面板不显示；否则 5 段 grid（💰财务 / 📦库存 / 💵累计盈亏 + 回本 badge / 📊销售26周 / 🎯紧迫分）。回本 badge 逻辑沿用旧版（realizedProfitEur 正/压货中/账面亏损三态）。
   - 复用 tokens.css 既有类名（参照旧 `_page_history.html` 的 `.rst-*` / `.ext-*` / `.heat-mini` / `.hc` 样式；若 Vue 栈缺这些类，在组件 `<style scoped>` 或共享样式补，颜色只用 token 变量，不硬编码）。
5. 切到 notfound/fuzzy/初始态：两面板容器不显示。

- [ ] **Step 4: 跑测试 + typecheck 确认通过**

Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts && npm run typecheck`
Expected: 全 PASS。

- [ ] **Step 5: 跑守护测试 + 全前端**

Run: `cd frontend && npx vitest run src/pages/history/no-analytics.test.ts`
Expected: PASS（新端点 `/api/history/<bc>/analytics/extras` 不含 `/analytics/sku`、`/timeline` 子串）。
> coder：**先实读 `no-analytics.test.ts` 断言的禁用串**。若它禁 `/analytics/sku` + `/timeline` → 安全。若意外更宽（禁纯 `/analytics`）→ STOP，向用户报告，不擅改守护。

Run: `cd frontend && npm run test:unit`
Expected: 全前端 jsdom 套件全绿。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.vue frontend/src/pages/history/HistoryPage.test.ts
git commit -m "feat(history): Phase 2b HistoryPage 渲染 extras+补货两面板 + runSearch 门控"
```

---

## Task 9: 全量验证 + 收尾

**Files:** 无（验证 only）

- [ ] **Step 1: 后端全量**

Run: `pytest tests/ -q`
Expected: 全绿。

- [ ] **Step 2: TS 类型漂移守护**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0。

- [ ] **Step 3: 前端全量 + 构建**

Run: `cd frontend && npm run test:unit && npm run typecheck && npm run build`
Expected: 测试全绿 + typecheck 0 + build 成功。

- [ ] **Step 4: ruff 全量**

Run: `ruff check app/ tests/`
Expected: 无错误。

- [ ] **Step 5: 本地浏览器人工验收（用户做）**

`./dev.ps1 -Frontend`（:5173），开 `/ui/history` 查一个有完整数据的 barcode（如截图 12345）：
- 命中后 SLA/PUR/客户（2a）下方出现 Extras 面板 + 补货快照面板。
- 热力图 4 年 × 12 月，数字 + 颜色都在。
- 若该 SKU 预测过期，forecast 段显「⚠ 预测过期」。
- 快速连查 A→B，B 的财务/补货不被 A 覆盖。
- 「查看完整分析（旧版）→」深链仍可访问旧页。

---

## Self-Review 记录

**Spec 覆盖：** HC-B1（additive，旧页不动 = Task 全程不碰旧 SPA）/ B2（瘦端点 6 函数 + key 集合 = Task 2,3）/ B3（原子失败 + 独立 store = Task 3,5,8）/ B4（heatmap validator + 12 项 = Task 1,3,4,8）/ B5（forecast 红线 is_stale + stockout = Task 1,2,3,8）/ B6（restock 显式投影 = Task 1,2,3）/ B7（三 store 并发 = Task 5,6,7 + runSearch 门控 Task 8）。confidence 不做（不出现于任何 task）。全部有 task 落点。

**类型一致：** `SkuExtrasResponse`/`RestockSnapshot`/`HeatmapData`/`ForecastBrief`（后端）↔ `ExtrasPageVM`/`RestockVM`/`HeatmapVM`/`ForecastBriefVM`（前端 VM）↔ `normalizeExtras`/`useSkuExtrasStore` 命名贯穿一致。`load` 返回 `Promise<boolean>`（P1）在 store 与 runSearch 门控两处签名一致。

**无占位符：** schema / normalize / store 代码完整；HistoryPage 模板因复刻旧版量大，给出子段顺序 + 关键逻辑 + 旧类名引用（非伪代码占位，coder 对照旧 `renderExtras`/`renderRestockSnapshot` 落地）。
