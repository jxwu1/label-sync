# 货号历史页迁移 Vue —— Phase 2a（销售分析 SLA + 采购面 PUR）设计

**状态：** 待审批（边界 + 硬约束已与用户对齐，2026-06-17）

## 目标

在 Phase 1（核心查询 + 变更溯源）基础上，给 `/ui/history` 命中态补上**基础销售/采购判断**：销售分析（SLA）+ 采购面（PUR）+ CN/老外客户拆分卡。数据走**新建瘦端点** `GET /api/history/<barcode>/analytics`。仍 **additive**，不退役旧页。

这是货号历史 4 阶段迁移里 Phase 2 的前半（2a）；深度 extras / 月度热力图 / 补货决策快照是 Phase 2b。

## 范围

### 做（Phase 2a）
- 命中 SKU 后加载并渲染：销售分析 SLA（总销量/总营收/独立客户/寿命/12周趋势）+ 采购面 PUR（库存推算/毛利率/365天采购/上次采购）+ 客户拆分卡（CN / 老外，各：销量/客户数/单笔最大/月频/上次）
- 数据源：**仅新建** `GET /api/history/<barcode>/analytics`

### 不做（Phase 2b+，硬约束 HC-A2/A5）
- 深度 extras（退货率/价格波动/零售汇总/客户 TOP10）→ Phase 2b
- 月度热力图 → Phase 2b
- 补货决策快照 → Phase 2b
- SVG 销售/进价时间线（`/timeline`）→ Phase 3
- 批次记录 tab → Phase 4
- 等级对照（qty_percentile / manual_grade vs 销量）→ 旧页 renderSLA 已于 2026-05-23 移除自动分类行，本期不迁

---

## 硬约束（写死，coder 不得自行发挥）

**HC-A1（additive 延续）：** 不退役旧 SPA 货号历史页（store.js / `_page_history.html` / `history.js` 全保留）；P1 已有的「查看完整分析（旧版）→」深链 `/?page=history` 保留不动。旧 SPA 继续用胖 `/analytics/sku/<barcode>`。

**HC-A2（瘦端点，唯一与 strict+只建2a 兼容的形状）：** 新建 `GET /api/history/<barcode>/analytics`，**只调** `compute_sales_metrics` + `compute_purchase_metrics` + `compute_customer_split`，**只返回** `{ok, sales, purchase, customer_split}`。**不复用**胖 `/analytics/sku/<barcode>` 的完整 response；**不计算、不返回** extras / heatmap / restock_snapshot / forecast / timeline / qty_percentile / auto_category。

**HC-A3（strict schema 逐字段对齐真实输出）：** `SkuAnalyticsData` 及嵌套模型 `extra="forbid"`，字段/类型逐字段对齐下方（已核 `app/services/analytics/metrics.py` + `_shared.py` 的真实 return）。**所有时间戳是 Text 字符串**（`last_at` 来自 event_at，无 datetime 对象）。

**HC-A4（analytics 失败隔离）：** 分析块用**独立 store**（`useSkuAnalyticsStore`），独立 loading/error。analytics 加载失败 / 401 **只**影响分析块（显该块错误态），**不影响** P1 的 hero / 概况 / 历史时间线（它们由 `useHistoryStore` 渲染，两者互不依赖）。

**HC-A5（2a 不消费 2b 字段）：** 前端 VM / normalize 只含 sales / purchase / customerSplit；后端 thin endpoint 响应 key **恰好** `{ok, sales, purchase, customer_split}`（后端测试断言 key 集合）。P1 的 `no-analytics.test.ts`（禁 `/analytics/sku`、`/timeline`）**继续有效**——本期新端点是 `/api/history/<barcode>/analytics`，不含 `/analytics/sku` 子串，守护不破。

**canonical contract（写进 spec）：** `sales + purchase + customer_split` 是 Phase 2a 的 canonical 契约。任何新增 2b key（extras/heatmap/restock_snapshot/forecast…）**必须**等 Phase 2b 修改 schema + 测试，不得本期偷接。

---

## 后端

### 端点
在 `app/routes/history.py` 现有 `api_bp`（P1 建的 `/api/history` 蓝图）上**加一个路由**：

```python
@api_bp.get("/<barcode>/analytics")
def analytics(barcode: str):
    from app.schemas_api import SkuAnalyticsData
    from app.services import analytics as analytics_service

    bc = barcode.strip()
    payload = {
        "ok": True,
        "sales": analytics_service.compute_sales_metrics(bc),
        "purchase": analytics_service.compute_purchase_metrics(bc),
        "customer_split": analytics_service.compute_customer_split(bc),
    }
    return jsonify(SkuAnalyticsData.model_validate(payload).model_dump())
```

- 路由 = `/api/history/<barcode>/analytics`（不与 P1 的 `GET ""` 即 `/api/history` 冲突）。
- **无存在性 404**：3 个 compute 函数对不存在 barcode 返回零值 shape（sales 全 0、purchase stock_balance=0/None、customer_split 两端空）。本端点**只在 P1 命中后被调**，barcode 必然存在；"无销售"是合法状态（显零值，不是错误），故不 404。
- 系统级异常不在端点吞，冒泡到 Flask 通用 500（对齐 `/api/briefing/data`）。
- `/api/*` 未登录 → 全局 auth 返回 JSON 401（HC-A4 失败隔离含此路径）。

### pydantic schema（`app/schemas_api.py`，已逐字段核实 —— HC-A3）

来源核对：`compute_sales_metrics`（metrics.py:68-74）、`compute_purchase_metrics`（metrics.py:107-112）、`compute_customer_split`（metrics.py:176-179）→ `_customer_end_metrics`（_shared.py:195-216）。

```python
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
    """GET /api/history/<barcode>/analytics 的 200 响应（Phase 2a canonical 契约）。
    只含 sales + purchase + customer_split；2b key 必须等 Phase 2b 扩 schema。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    sales: SkuSalesMetrics
    purchase: SkuPurchaseMetrics
    customer_split: SkuCustomerSplit
```
`API_MODELS` 追加 `SkuAnalyticsData`（嵌套经 `$defs` 自动进 types.gen.ts）。`python tools/gen_ts_types.py` 同步。

> 类型说明：`total_revenue`/`avg_freq_per_month` 是 `round(...)` 浮点；`avg_freq_per_month` 空端返回 `0.0`。pydantic `float` 在 lax 模式接受 int（如 0），不会因整数值 500。`int` 字段（total_qty 等）service 已 `int()` cast。

---

## 前端

### VM（`frontend/src/pages/history/analytics-types.ts`）
```typescript
export interface SalesVM {
  totalQty: number;
  totalRevenue: number;
  uniqueCustomers: number;
  lifespanDays: number;
  trendSlopePctPerWeek: number | null;
}
export interface PurchaseVM {
  stockBalance: number;
  avgMarginPct: number | null;
  purchaseFreq365d: number;
  lastPurchaseDaysAgo: number | null;
}
export interface CustomerEndVM {
  qty: number;
  uniqueCustomers: number;
  maxSingleQty: number;
  lastAt: string | null;
  avgFreqPerMonth: number;
}
export interface AnalyticsVM {
  sales: SalesVM;
  purchase: PurchaseVM;
  cn: CustomerEndVM;
  fo: CustomerEndVM;
}
```

### normalize（`frontend/src/pages/history/analytics-normalize.ts`，单点收窄）
入 `SkuAnalyticsData` → 出 `AnalyticsVM`，snake_case→camelCase，null/缺字段兜底（`num()` helper）。只收 sales/purchase/customer_split.cn/.fo —— **不触碰任何 2b 字段（HC-A5）**。

### store（`frontend/src/stores/skuAnalytics.ts`，HC-A4 独立失败）
独立 pinia store：`vm: AnalyticsVM | null`、`loading`、`error`、`load(barcode)`。`load` 调 `apiGet<SkuAnalyticsData>('/api/history/' + encodeURIComponent(barcode) + '/analytics')` → normalize；`UnauthenticatedError` 吞；其它 error 填 `error`。与 `useHistoryStore` 完全独立。

### 组件（`frontend/src/pages/history/HistoryPage.vue` 扩展）
- P1 命中渲染后（`store.result.kind === "hit"`），在「概况」之后、「历史时间线」之前插入分析块：
  - **触发点（写死）**：在 `runSearch` 的命中分支里调 `analyticsStore.load(result.current.barcode)`——与 `pushRecent` 同一处（`if (!store.error && store.result?.kind === "hit") { pushRecent(query); analyticsStore.load(store.result.current.barcode); }`）。doSearch / pickFuzzy / pickRecent 都经 runSearch，故只此一个触发点。不另用 watch。
  - **销售分析 SLA**：总销量/总营收/独立客户/寿命/日均件数（total_qty/lifespan_days 算）/12周趋势
  - **客户拆分**：CN / 老外 两张卡（销量/客户数/单笔最大/月频/上次）
  - **采购面 PUR**：库存推算/毛利率/365天采购/上次采购
  - 分析块自己的子状态：`analyticsStore.loading` → "分析加载中…"；`analyticsStore.error` → 该块错误条（**不影响** hero/概况/events，HC-A4）
- 切换到 notfound/fuzzy/初始态时，分析块不显示（仅 hit 态显示）

### 不新建路由 / nav
Phase 2a 不动 router / nav-items（P1 已把 history 翻 routeName）。纯在 HistoryPage 命中态内扩展。

---

## 测试 / 验收

### 后端（`tests/test_history_analytics_api.py`）
- 未登录 → 401 `{error:"unauthenticated"}`
- 命中（seed stockpile + sale/purchase events）→ 200，sales/purchase/customer_split 三块字段齐、类型对
- 无销售 SKU（只 seed stockpile）→ 200，sales 全 0 / customer_split 两端 0（合法零值，非错误）
- **响应 key 恰好 `{ok, sales, purchase, customer_split}`**（HC-A5：断言无 extras/heatmap/restock/forecast key）
- seed 走 SQLAlchemy（参照 `tests/test_history_api.py` 的 `import_from_dataframe` + events 插入）

### 前端（vitest）
- `analytics-normalize.test.ts`：命中数据 camelCase 映射 + 空值兜底（trend/avg_margin/last_at 为 null 的分支）
- `skuAnalytics.test.ts`（store）：load 填 vm、load 失败填 error、unauth 吞、调对端点 `/api/history/<bc>/analytics`
- `HistoryPage.test.ts` 扩展：
  - hit 态触发 `analyticsStore.load(barcode)` 且渲染 SLA/PUR/客户卡（mock analytics store 返回数据）
  - **analytics 失败时**：分析块显错误，但 hero/概况/历史时间线（P1 部分）**仍正常渲染**（HC-A4 回归）
  - analytics loading 时显"分析加载中"，P1 部分不受影响

### 守护（HC-A5 + 延续 HC-2）
- `no-analytics.test.ts`（P1 已有）继续通过：pages/history + stores 不含 `/analytics/sku`、`/timeline`（本期端点是 `/api/history/<bc>/analytics`，不命中）
- 后端 key 断言（上面）即 "2a 不返回 2b" 的硬守护

### 最低验收（用户定）
命中 SKU 后分析块可加载 ✓ / analytics 失败不影响 P1 hero·概况·events ✓ / 测试断言 2a 不渲染·不消费 2b 字段 ✓ / 旧页完整分析仍可访问 ✓

---

## 不做（YAGNI）
不为 2b 预建 passthrough / 占位字段；不重排成两列（沿用 P1 单列）；不迁等级对照；不动 router/nav。
