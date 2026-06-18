# 货号历史页迁移 Vue —— Phase 2b（深度 extras + 月度热力图 + 补货决策快照）设计

**状态：** 设计待批（2026-06-18）。两轮审查 REQUEST_CHANGES 全部处置写入（第一轮 #1-6：forecast 红线/失败边界/块数/并发/热力图/restock 投影；第二轮 #7-10：P1 store 竞态根因 + reset 作废 pending + heatmap validator + fetch_event_rows 原子失败）。待用户审阅后落 plan。

## 目标

在 Phase 1（核心查询 + 变更溯源）、Phase 2a（销售分析 SLA + 采购面 PUR + 客户拆分）基础上，给 `/ui/history` 命中态补上旧版「完整分析」的剩余深度块：**深度 extras**（退货率+价格波动、零售汇总、客户 TOP10 CN/老外、月度热力图、持仓+下季度预测+数据范围）+ **补货决策快照**（财务/库存/累计盈亏/销售26周/紧迫分 5 段）。数据走**新建独立渐进端点** `GET /api/history/<barcode>/analytics/extras`。仍 **additive**，不退役旧页。

这是货号历史 4 阶段迁移里 Phase 2 的后半（2b）。SVG 销售/进价时间线（`/timeline`）= Phase 3；批次记录 tab = Phase 4，均不在本期。

## 范围

### 做（Phase 2b）—— 两个渲染面板，一个 2b 错误边界
命中 SKU 后，在 2a 分析块之后、历史时间线之前，加载并渲染**两个面板**（共享同一个 2b loading/error 边界，见 HC-B3）：

1. **Extras 面板**（旧 `renderExtras` 1:1 复刻，子段顺序固定）：
   - 退货率 + 价格波动（return_rate_pct / price_stats）
   - 零售汇总（MB700 + ID=0：qty/revenue/n_transactions/avg_ticket_qty/last_at）
   - 客户 TOP10 拆 CN / 老外两张 mini-table
   - 🌡 月度热力图（4 年 × 12 月 HTML 表，见 HC-B4）
   - 持仓 / 下季度预测 / 数据范围（holding + forecast + first/last_event_at + 截断警告）
2. **补货决策快照面板**（旧 `renderRestockSnapshot` 1:1 复刻）：💰财务 / 📦库存 / 💵累计盈亏（带回本 badge）/ 📊销售 26 周 / 🎯紧迫分 五段 grid。

数据源：**仅新建** `GET /api/history/<barcode>/analytics/extras`。

### 不做（硬约束 HC-B2）
- SVG 销售/进价时间线（`/timeline`）→ Phase 3
- 批次记录 tab（recent-changes + scan-history）→ Phase 4
- 等级对照（qty_percentile / manual_grade vs 销量）→ 旧页 2026-05-23 已移除，不迁
- **预测可信度分层 confidence（high/medium/low）→ 不做**（用户 2026-06-18 决策 YAGNI）：红线未要求；`confidence_tier` 需 backtest 的 mase/coverage join，`compute_forecast_snapshot` 不取；旧 UI 从未展示。要做须单列新功能。
- 手工分类下拉（`renderManualDropdown`）→ 旧页已无用，不迁
- 不为 Phase 3/4 预建 passthrough / 占位字段

---

## 硬约束（写死，coder 不得自行发挥）

**HC-B1（additive 延续）：** 不退役旧 SPA 货号历史页（store.js / `_page_history.html` / `history.js` 全保留）；P1 的「查看完整分析（旧版）→」深链 `/?page=history` 保留不动。旧 SPA 继续用胖 `/analytics/sku/<barcode>`。2a 端点 `GET /api/history/<barcode>/analytics` **完全冻结不动**（其 strict key 集合 `{ok,sales,purchase,customer_split}` 与 HC-A5 断言保持）。

**HC-B2（独立渐进瘦端点）：** 新建 `GET /api/history/<barcode>/analytics/extras`，**只调** `fetch_event_rows` + `compute_sku_extras` + `compute_avg_holding_days` + `compute_monthly_heatmap` + `compute_forecast_snapshot` + `compute_restock_snapshot`，响应 key **恰好** `{ok, extras, holding, heatmap, forecast, restock}`（后端测试断言此 key 集合，**不含** 2a 的 sales/purchase/customer_split）。**不复用**胖 `/analytics/sku`。

**HC-B3（失败边界 = Phase 2b 原子，与 P1/2a 隔离）：** 端点串行调 5 个 compute 函数，任一抛错 → 整个请求 500 → 整个 2b（Extras + 补货）一起进错误态。这是**原子失败**，不在路由里逐项吞异常返回半成功。隔离粒度 = 「2b 整体 ↔ P1/2a」：2b 用**独立 store** `useSkuExtrasStore`（独立 loading/error），其失败**不影响** P1 的 hero/概况/events（`useHistoryStore`）和 2a 的 SLA/PUR/客户（`useSkuAnalyticsStore`）。401 沿用全局语义：`apiGet` 命中 401 → `location.assign('/login')` + 抛 `UnauthenticatedError`，store **吞掉**不写块内 error（与 P1/2a/briefing 一致）。

**HC-B4（热力图 HTML 表，三补充）：** 月度热力图用 HTML `<table>` + 单元格背景 intensity，不引 SVG。
- **每年严格 12 个值**：后端 `HeatmapData` 加 pydantic `field_validator`（或 model_validator）强制 `matrix` 每个 year 的 list 长度 == 12。这是**输出** schema 校验，不满足时端点 `model_validate` 抛 `ValidationError` → 与系统级异常一致冒泡 Flask 通用 **500**（非 422——422 是请求体校验语义，本端点无请求体）。`compute_monthly_heatmap` 已保证 `[0]*12`，validator 是契约硬守护；前端 normalize 补齐到 12 仅作纵深防御。
- **max_qty == 0 时 intensity 恒为 0**：防除零（`q / max_qty`）。全零年份所有格显 `—`。
- **单元格保留数值文本**：`q > 0` 显数字，`q == 0` 显 `—`；颜色只是辅助，不靠颜色单独表达数值（可访问性）。

**HC-B5（forecast 消费红线，replenishment-redlines.md:156）：** 本端点经 `compute_forecast_snapshot` 是 `forecast_output` 的新消费端，**必须**处理 `computed_at` 过期（RL-9）与 `stockout_weeks_excluded`（RL-3）。`ForecastBrief` 含 `is_stale`（端点用 `forecast_eval.forecast_is_stale(computed_at, today)` 派生，14 天阈值）+ `stockout_weeks_excluded`；UI forecast 段显「⚠ 预测过期」徽标（is_stale=true）+ 缺货周剔除数提示（stockout_weeks_excluded>0）。**这补上了旧 history.js 缺的红线合规**（旧页只显 quarter_mu/p98，早于红线）。

**HC-B6（restock 显式投影，不整行透传）：** `compute_restock_snapshot` 返回 `list_sku_summary` 整行（50+ 字段）。端点**显式构造**只含旧 `renderRestockSnapshot` 消费字段的子 dict，再过 `extra="forbid"` 的 `RestockSnapshot` schema。**禁止**把整行喂 schema（会被 forbid 拒）。投影 key 集合由后端测试精确断言。

**HC-B7（并发 stale 防护，覆盖 P1 + 2a + 2b 三 store + runSearch 门控）：** 三个 store（`useHistoryStore` P1 / `useSkuAnalyticsStore` 2a / `useSkuExtrasStore` 2b）都加**单调 request-id**，seq 定义在各 store 的 `defineStore` setup 闭包内（**非模块级**，保证测试隔离 + 每 store 实例独占计数）：
- `load` 开头 `const my = ++seq`；await 返回后**所有写入分支**（成功写 result/vm、失败写 error、finally 落 loading）都先判 `if (my !== seq) return`，stale 响应一律丢弃。
- **`reset()` 也递增 `++seq`**（BLOCKER：否则 reset 后 pending 请求 resolve 时 `my === seq` 仍成立 → 旧请求回写已重置的 store）。
- **P1 `load` 返回「本次是否最新」布尔**（`return my === seq`），供 runSearch 门控：**只有最新搜索才触发下游 analytics/extras 加载**。stale 搜索（被更晚搜索超越）的 runSearch 提前 return，绝不触碰下游。

竞态根因（红队可稳定复现）：A→B 快切，B 的 P1 先返回→展示 B + 加载下游 B；A 的 P1 后返回，**无守卫时覆盖回 A** 且 A 的 runSearch 接着发下游 A → 最终全 A。修法 = P1 seq 守卫（stale A 不覆盖 result）+ runSearch 用 P1 load 返回值门控（stale A 的 runSearch 不发下游）+ 三 store reset 递增 seq。2a spec 当初把「fast A/B request-id」记为「Phase 2b/backlog」，此即兑现点。

---

## 后端

### 端点（`app/routes/history.py` 的 `api_bp` 上加路由）

```python
@api_bp.get("/<barcode>/analytics/extras")
def analytics_extras(barcode: str):
    from app.schemas_api import SkuExtrasResponse
    from app.services import analytics as analytics_service
    from app.services.analytics._shared import _today
    from app.services.forecast_eval import forecast_is_stale

    bc = barcode.strip()
    rows = analytics_service.fetch_event_rows(bc)   # HC-B2: 取一次喂 extras/holding/heatmap
    extras = analytics_service.compute_sku_extras(bc, rows=rows)
    holding = analytics_service.compute_avg_holding_days(bc, rows=rows)
    heatmap = analytics_service.compute_monthly_heatmap(bc, rows=rows)
    fc = analytics_service.compute_forecast_snapshot(bc)        # dict | None
    restock_full = analytics_service.compute_restock_snapshot(bc)  # dict | None

    forecast_brief = None
    if fc is not None:
        forecast_brief = {
            "quarter_mu": fc["quarter_mu"],
            "quarter_p98": fc["quarter_p98"],
            "computed_at": fc["computed_at"],
            "is_stale": forecast_is_stale(fc["computed_at"], _today()),   # HC-B5 / RL-9
            "stockout_weeks_excluded": fc["stockout_weeks_excluded"],     # HC-B5 / RL-3
        }

    restock_brief = None
    if restock_full is not None:
        restock_brief = _project_restock(restock_full)   # HC-B6 显式投影, 见下

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

- 路由 = `/api/history/<barcode>/analytics/extras`（不与 P1 `GET ""` / 2a `GET "/<barcode>/analytics"` 冲突）。
- **无存在性 404**：本端点只在 P1 命中后被调，barcode 必然存在。无销售 / 无预测 / 不在补货汇总都是合法零值/None 状态，非错误。`fetch_event_rows` 对不存在 barcode 返回空 list → extras 全零、holding None、heatmap 全零矩阵。
- 系统级异常不在端点吞，冒泡 Flask 通用 500（HC-B3 原子失败）。
- `/api/*` 未登录 → 全局 auth JSON 401。
- `_project_restock(row)` 是 `app/routes/history.py`（或 `app/services/analytics`）内的纯投影 helper，显式取下方 schema 列出的字段（含 `urgency_breakdown` 嵌套），其余整行字段丢弃。

### pydantic schema（`app/schemas_api.py`，全 `extra="forbid"`，逐字段对齐真实输出）

> 来源核对：`compute_sku_extras`（metrics.py:374-478）、`compute_avg_holding_days`（metrics.py:545-606）、`compute_monthly_heatmap`（metrics.py:609-643）、`compute_forecast_snapshot`（restock_calc.py:41-82）、`list_sku_summary` 行（summary.py:496-554）+ `_attach_urgency_scores`（restock_calc.py:140-155）。**coder 实施时须再逐字段复核一遍，对不上的 STOP 报告，不自行放宽类型。**

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
    years: list[str]                  # ['2023','2024','2025','2026']
    matrix: dict[str, list[int]]      # {year: [12 个月 int]}
    max_qty: int

    @field_validator("matrix")        # HC-B4: 每年严格 12 项, 契约硬守护
    @classmethod
    def _matrix_12_months(cls, v: dict[str, list[int]]) -> dict[str, list[int]]:
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

`API_MODELS` 追加 `SkuExtrasResponse`（嵌套经 `$defs` 自动进 types.gen.ts）。`python tools/gen_ts_types.py` 同步。

> 类型说明：① `inventory_sale_value_eur` / `inventory_cost_value_eur` 在 summary.py 由 `inventory_sale_value` / `inventory_cost_value` 赋值，nullable 待 coder 复核（旧 JS 用 `?? 0`，暂定 `float | None`）；② `urgency_breakdown` 仅在 `is_truly_discontinued` 时为 None（货号历史页只查 active，实际几乎恒非 None，但 schema 仍 `| None` 防御）；③ pydantic lax 模式 `float` 接受 int（如 0），不会因整数值 500。

---

## 前端

### VM（`frontend/src/pages/history/extras-types.ts`）
镜像 schema 出 camelCase VM：`ExtrasVM`（returnQty/totalSaleQtyGross/returnRatePct/priceStats/topCustomersCn/topCustomersForeign/retailSummary/firstEventAt/lastEventAt/isHistoryTruncated）、`HoldingVM`、`HeatmapVM`（years/matrix/maxQty）、`ForecastBriefVM`（quarterMu/quarterP98/computedAt/isStale/stockoutWeeksExcluded）、`RestockVM`（上列 restock 字段 camelCase + urgencyBreakdown 嵌套）。顶层 `ExtrasPageVM { extras, holding, heatmap, forecast: ForecastBriefVM | null, restock: RestockVM | null }`。

### normalize（`frontend/src/pages/history/extras-normalize.ts`，单点收窄）
入 `SkuExtrasResponse` → 出 `ExtrasPageVM`，snake→camel，null/缺字段兜底。**热力图守 HC-B4**：每年 `matrix[y]` 强制补齐到 12 项（`Array.from({length:12}, (_,i) => row[i] ?? 0)`）；`maxQty` 兜 0。forecast/restock 为 null 时透传 null（UI 各自判空）。

### store（`frontend/src/stores/skuExtras.ts`，HC-B3 独立失败 + HC-B7 stale 防护 + 状态卫生）
`seq` 定义在 `defineStore` setup 闭包内（**非模块级**，测试隔离）：
```typescript
export const useSkuExtrasStore = defineStore("skuExtras", () => {
  const vm = ref<ExtrasPageVM | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  let seq = 0;                                  // HC-B7 单调 request-id（闭包级）

  async function load(barcode: string) {
    const my = ++seq;
    loading.value = true;
    error.value = null;
    vm.value = null;                            // 开查询即清旧 VM
    try {
      const raw = await apiGet<SkuExtrasResponse>(
        `/api/history/${encodeURIComponent(barcode)}/analytics/extras`);
      if (my !== seq) return;                   // stale 成功：更晚的 load/reset 已发起，丢弃
      vm.value = normalizeExtras(raw);
    } catch (e) {
      if (my !== seq) return;                   // stale 失败：不得覆盖更晚请求
      if (e instanceof UnauthenticatedError) return;   // 401 走全局跳转，不写块内 error
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === seq) loading.value = false;    // 只有最新请求收尾才落 loading
    }
  }
  function reset() {
    seq++;                                      // HC-B7 BLOCKER: 作废 pending 请求, reset 后旧响应不回写
    vm.value = null; error.value = null; loading.value = false;
  }
  return { vm, loading, error, load, reset };
});
```
- 与 `useHistoryStore`、`useSkuAnalyticsStore` 完全独立。

### 2a store 回填（`frontend/src/stores/skuAnalytics.ts`，HC-B7）
给 `useSkuAnalyticsStore` 加同款闭包级 `seq`：`load` 开头 `const my = ++seq` + 所有写入分支 `if (my !== seq) return`；`reset()` `seq++`。**仅加并发守卫，不改其它行为**；补 store 测试「旧 A 慢响应不覆盖新 B」+「pending → reset → resolve 不回写」。

### P1 store 回填（`frontend/src/stores/history.ts`，HC-B7 BLOCKER 根因修复）
`useHistoryStore.load` 当前无 seq 守卫（history.ts:13-26），是红队竞态根因。改：
```typescript
let seq = 0;                                  // 闭包内
async function load(q: string): Promise<boolean> {   // 返回「本次是否最新」供 runSearch 门控
  const my = ++seq;
  loading.value = true;
  error.value = null;
  result.value = null;
  try {
    const raw = await apiGet<HistorySearchData>(`/api/history?q=${encodeURIComponent(q)}`);
    if (my !== seq) return false;             // stale：被更晚搜索超越，不写 result
    result.value = normalizeHistory(raw);
  } catch (e) {
    if (my !== seq) return false;
    if (e instanceof UnauthenticatedError) return false;
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    if (my === seq) loading.value = false;
  }
  return my === seq;                          // true = 本次是最新搜索
}
function reset() {
  seq++;                                      // 作废 pending
  result.value = null; error.value = null; loading.value = false;
}
```
**仅加并发守卫 + load 返回值，不改 P1 既有的 result 清理/RECENT/七状态语义**；补测试「pending → reset → resolve 不回写」+「A 慢于 B 返回时 result 仍是 B」。

### 组件（`frontend/src/pages/history/HistoryPage.vue` 扩展）
- 触发点（写死，沿用 2a 单触发点，**HC-B7 门控**）：`runSearch` 用 P1 `store.load` 的返回值门控——stale 搜索（被更晚搜索超越）提前 return，**绝不触碰下游**；只有最新搜索才命中分支触发 analytics/extras：
  ```typescript
  const fresh = await store.load(query);
  if (!fresh) return;   // HC-B7: 本次搜索已被更晚搜索超越，不写下游（防 stale A 覆盖 B）
  if (!store.error && store.result?.kind === "hit") {
    pushRecent(query);
    analyticsStore.load(store.result.current.barcode);
    extrasStore.load(store.result.current.barcode);
  } else {
    analyticsStore.reset();
    extrasStore.reset();
  }
  ```
  （doSearch / pickFuzzy / pickRecent 都经 runSearch，故只此一个门控点。）
- `doReset()` 里并列 `extrasStore.reset()`。
- 渲染位置：2a 分析块之后、历史时间线之前，加**两个面板**（共享 2b 边界）：
  - `extrasStore.loading` → 「深度分析加载中…」；`extrasStore.error` → 2b 错误条（**不影响** P1 + 2a，HC-B3）。
  - 数据就绪渲染 Extras 面板（子段顺序见范围）+ 补货快照面板。
  - forecast 段：`forecast === null` → 「序列太短未训出」；`forecast.isStale` → 「⚠ 预测过期」徽标；`forecast.stockoutWeeksExcluded > 0` → 缺货周剔除提示（HC-B5）。
  - restock 面板：`restock === null` → 该面板不显示（旧版 `if (!it) panel.hidden`）。
  - 热力图：HTML `<table>`，每行严格 12 格，`maxQty===0` 时 intensity 0、全 `—`，格内保留数值（HC-B4）。
- 切到 notfound/fuzzy/初始态 → 两面板不显示。

### 不新建路由 / nav
Phase 2b 不动 router / nav-items（P1 已把 history 翻 routeName）。纯在 HistoryPage 命中态内扩展。

---

## 测试 / 验收

### 后端（`tests/test_history_extras_api.py`）
- 未登录 → 401 `{error:"unauthenticated"}`
- 命中（seed stockpile + sale/purchase events + forecast_output）→ 200，extras/holding/heatmap/forecast/restock 字段齐、类型对
- **响应 key 恰好 `{ok, extras, holding, heatmap, forecast, restock}`**（HC-B2：断言不含 sales/purchase/customer_split）
- **restock 投影 key 精确匹配** `RestockSnapshot` 字段集（HC-B6：断言投影后无 sku_summary 其它字段如 supplier_id/cn_qty/weekly_qty_12w）
- forecast 分支：无 forecast_output 行 → `forecast === None`；computed_at 距今 >14 天 → `is_stale === True`；≤14 天 → False（HC-B5 / RL-9）
- restock 分支：不在补货汇总（停用/无主档）→ `restock === None`
- heatmap：每年恰 12 项；`max_qty == 0` 全零年份；含负数月（退货净负）不崩
- `fetch_event_rows` **每请求恰好调用一次**（HC-B2：mock/spy 断言调用次数 == 1，extras/holding/heatmap 复用同一 rows）
- **六个数据函数分别 mock 抛异常 → 端点返回 500**（HC-B3 原子失败边界，逐个：`fetch_event_rows` + `compute_sku_extras` + `compute_avg_holding_days` + `compute_monthly_heatmap` + `compute_forecast_snapshot` + `compute_restock_snapshot`）
- **heatmap matrix 某年非 12 项 → pydantic 校验失败**（HC-B4 validator：构造 mock compute_monthly_heatmap 返回 11/13 项，断言端点 500 / 校验抛错）
- seed 走 SQLAlchemy（参照 `tests/test_history_analytics_api.py` + `tests/test_forecast_eval_dashboard.py` 的 forecast_output seed helper，含 NOT NULL 列 mu/sigma/p50/p98/n_weeks_history 等）

### 前端（vitest）
- `extras-normalize.test.ts`：camelCase 映射 + 空值兜底（price_stats/forecast/restock 为 null 分支）；**热力图每年补齐 12 项**（喂 <12 / >12 / 缺年 → 输出恒 12）；`maxQty` 兜 0
- `skuExtras.test.ts`（store）：load 填 vm / load 失败填 error / unauth 吞（error 保持 null）/ 调对端点 `/api/history/<bc>/analytics/extras` / 旧 vm 存在时新 load 失败 → vm===null；**HC-B7 stale：先发 A（pending）再发 B，A 后 resolve 不写 vm（B 赢）**；**HC-B7 reset：load A pending → reset() → A resolve 不回写 vm（vm 保持 null）**
- `skuAnalytics.test.ts`（2a 回填）：补 stale 守卫回归「A 慢响应不覆盖 B」+「load pending → reset → resolve 不回写」
- `history.test.ts`（P1 回填，HC-B7 根因）：**「A 慢于 B 返回时 result 仍是 B」**（先发 A pending、再发 B、B 先 resolve、A 后 resolve → result===B 不被 A 覆盖）；**load 返回值：最新搜索返回 true、被超越搜索返回 false**；**「load pending → reset → resolve 不回写 result」**
- `HistoryPage.test.ts` 扩展：
  - hit 态触发 `extrasStore.load(barcode)` 且渲染 Extras 面板 + 补货面板（mock store 返回数据）
  - **extras 普通失败时**：2b 错误条显示，但 hero/概况/历史时间线（P1）+ SLA/PUR/客户（2a）**仍正常渲染**（HC-B3 回归）
  - **401**：不要求块内错误条（store 吞）；P1 + 2a 不受影响
  - forecast=null → 「未训出」；isStale → 过期徽标；restock=null → 补货面板不显示
  - 热力图渲染 4 行 × 12 格，maxQty=0 全 `—`
  - 非命中态（notfound/fuzzy）→ `extrasStore.reset()` 被调（两面板不显示）
  - **HC-B7 门控**：stale 搜索（`store.load` 返回 false）的 runSearch 不调 `analyticsStore.load`/`extrasStore.load`（mock load 返回 false，断言下游 load 未被调用）

### 守护（延续 HC-2 / HC-A5）
- `no-analytics.test.ts`（P1 已有）：coder **先实读该测试断言的禁用串**确认——若禁 `/analytics/sku` 与 `/timeline` 子串，则新端点 `/api/history/<bc>/analytics/extras` 不含 `/analytics/sku`（含 `/analytics/` 但不含 `sku`/`timeline`）→ 安全；2a 端点 `/<bc>/analytics` 已证同样安全。若断言意外更宽（禁纯 `/analytics`）→ STOP 报告，与用户确认豁免方式，不擅自改守护。
- 后端 key 断言（上面）= 「2b 不返回 2a 字段」+「restock 不透传整行」双硬守护

### 最低验收（用户定）
命中 SKU 后两面板可加载 ✓ / 2b 失败不影响 P1 hero·概况·events 与 2a SLA·PUR·客户 ✓ / A→B 快切不串财务数据 ✓ / forecast 过期显徽标 ✓ / restock 投影 key 精确 ✓ / 旧页完整分析仍可访问 ✓

---

## 不做（YAGNI）
不为 Phase 3/4 预建字段；不重排既有 2a/P1 布局；不迁等级对照 / 手工分类下拉；不加 confidence；restock 不整行透传。

---

## 审查修订记录（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 1 | BLOCKER | forecast 只投 quarter_mu/p98 违反 forecast_output 消费红线（replenishment-redlines.md:156，须处理 computed_at 过期 + stockout_weeks_excluded） | HC-B5：ForecastBrief 加 computed_at + is_stale（复用 `forecast_is_stale`，RL-9 14天）+ stockout_weeks_excluded；UI 加过期徽标 + 剔除提示 |
| 1b | BLOCKER 子项 | 审查建议含 confidence 字段 | 推回（用户 2026-06-18 决策不加）：红线未要求；confidence_tier 需 backtest join，snapshot 不取；旧 UI 未展示。YAGNI |
| 2 | BLOCKER | 「三块各自失败隔离」与单端点串调 5 函数矛盾（任一抛错整体 500） | HC-B3：改原子失败，边界 = 「2b 整体 ↔ P1/2a」隔离（独立 store）；文案 + 测试按此改；不拆 restock 端点 |
| 3 | BLOCKER | UI 块数不一致（范围「三块」/ 渲染「两块」/ 测试「三块」） | 定死两个渲染面板（Extras + 补货），共享一个 2b 错误边界；热力图/持仓预测为 Extras 面板内子段；全 spec 措辞统一 |
| 4 | 条件确认 | 并发 A→B 快切，慢 extras 混入 A 财务/补货数据 | HC-B7：extras + 2a analytics 两 store 加单调 request-id stale 守卫；测试覆盖 A 后到不覆盖 B |
| 5 | 确认+补充 | 热力图 HTML 表 | HC-B4：每年严格 12 值 + max_qty==0 intensity 0 防除零 + 单元格保留数值文本 |
| 6 | 确认+要求 | restock 投影 + strict，须列精确字段 | HC-B6：显式投影 helper + RestockSnapshot 逐字段枚举（含类型/nullable）+ 测试精确断言 key 集合 |

### 第二轮审查（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 7 | BLOCKER | HC-B7 只护 2a/2b，未护 P1 `useHistoryStore`；A→B 时 B 先返回、A 后返回 → P1 覆盖回 A 且 A 的 runSearch 再发下游 A → 最终全 A（红队可稳定复现） | HC-B7 扩到三 store：P1 加 seq 守卫 + `load` 返回「是否最新」布尔；runSearch 用该返回值门控，stale 搜索不发下游 |
| 8 | BLOCKER | `reset()` 不递增 seq → reset 后 pending 请求 resolve 仍回写 | 三 store `reset()` 全 `seq++`；补「pending → reset → resolve 不回写」测试 |
| 9 | 建议 | 后端 `HeatmapData.matrix` 未限长度，与「每年严格 12」声明脱节 | HC-B4：加 pydantic `field_validator` 强制每年 12 项；前端补齐仅纵深防御 |
| 10 | 建议 | 原子失败测试漏 `fetch_event_rows` 抛错 | 改「六个数据函数逐个 mock 抛错 → 500」（含 fetch_event_rows） |
