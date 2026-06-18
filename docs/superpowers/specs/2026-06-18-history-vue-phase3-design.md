# 货号历史页迁移 Vue —— Phase 3（SVG 销售/进价时间线）设计

**状态：** 设计待批（2026-06-18）。审查 REQUEST_CHANGES（守卫假保护 + 数据语义 BLOCKER + 契约）已处置写入，待用户审阅后落 plan。

## 目标

在 Phase 1（核心查询+溯源）/ 2a（SLA+PUR+客户）/ 2b（extras+热力图+补货）基础上，给 `/ui/history` 命中态加一张**销售/进价走势图**：36 月销量柱 + 156 周进价阶梯折线（dot 标真实进货周）。数据走**新建瘦端点** `GET /api/history/<barcode>/timeline`。仍 **additive**，不退役旧页/旧端点。

放置位置（用户定）：`hero → 概况 → 【走势图】→ 销售分析 SLA → 客户 → 采购面 → 2b extras → 补货 → 变更时间线`。

这是货号历史 4 阶段迁移的 Phase 3。批次记录 tab（recent-changes + scan-history）= Phase 4，不在本期。**「查看完整分析（旧版）→」深链本期保留**（要等 Phase 4 也迁完才删）。

## 范围

### 做（Phase 3）
- 命中后加载并渲染**走势图**（独立 `TimelineChart.vue` 组件）：月销量柱 + 周进价阶梯折线 + 双 Y 轴 + X 月份标签 + tooltip。
- 数据源：**仅新建** `GET /api/history/<barcode>/timeline`。
- no-analytics 守卫修正（见 HC-P3-5）。

### 不做（YAGNI / 留后续）
- 批次记录 tab → Phase 4。
- 不删「旧版」深链（Phase 4 完再删）。
- 不动旧 SPA / 旧 `/analytics/sku/<bc>/timeline` 端点（旧页继续用）。
- 不引图表库（手写 SVG）。
- CN tooltip 不重算/不硬编码汇率公式（payload 无 rate 字段，只展示 ¥raw → €landed）。

---

## 硬约束（写死，coder 不得自行发挥）

**HC-P3-1（additive 延续）：** 不退役旧 SPA 货号历史页（store.js / `_page_history.html` / `history.js` 全保留）；旧端点 `/analytics/sku/<bc>/timeline` 不动；「查看完整分析（旧版）→」深链 `/?page=history` 保留。

**HC-P3-2（独立瘦端点）：** 新建 `GET /api/history/<barcode>/timeline`，**只调** `compute_weekly_timeline(bc)` + `compute_monthly_sales(bc)`，响应 key **恰好** `{ok, timeline, monthly_sales}`（后端测试断言此 key 集合）。**不复用**旧胖 `/analytics/sku/<bc>/timeline`。

**HC-P3-3（失败隔离，2b 同款）：** 走势图用**独立 store** `useSkuTimelineStore`（独立 loading/error）。其失败（500/网络/schema 漂移）只影响图块（块内错误态），**不影响** P1（hero/概况/events）、2a（SLA/PUR/客户）、2b（extras/补货）。端点串调 2 个 compute，任一抛错 → 整请求 500（原子）。401 沿用全局语义：`apiGet` 命中 401 → `location.assign('/login')` + 抛 `UnauthenticatedError`，store **吞掉**不写块内 error。

**HC-P3-4（并发 stale 防护，HC-B7 同款）：** `useSkuTimelineStore` 加闭包级单调 request-id：`load` 开头 `const my = ++seq`，所有写入分支（成功/失败/finally）判 `if (my !== seq) return`；`reset()` `seq++` 作废 pending。runSearch 沿用 P1 `fresh` 门控：命中且 fresh 才并列 `timelineStore.load(bc)`，非命中/重置 `timelineStore.reset()`。

**HC-P3-5（no-analytics 守卫修正——消除假保护）：** 现 `no-analytics.test.ts` 禁 `["/analytics/sku", "/timeline"]`，**只扫** `pages/history/*` + `stores/history.ts`——从未扫过 `stores/skuAnalytics.ts` / `stores/skuExtras.ts`，2a/2b「不调旧端点」一直是假保护；且裸 `/timeline` 会误伤新端点（旧 timeline 端点 `/analytics/sku/<bc>/timeline` 已被 `/analytics/sku` 覆盖）。本期修正：
- `FORBIDDEN` 改为 `["/analytics/sku"]`（去裸 `/timeline`）。
- 扫描集**纳入** `stores/skuTimeline.ts` + `stores/skuAnalytics.ts` + `stores/skuExtras.ts`（连同原 `pages/history/*` + `stores/history.ts`）。
- 测试名改「货号历史新栈不调用 legacy analytics 端点」，注释更新（P1-era 的 timeline 限制随 Phase 3 放开，新 timeline 走瘦端点）。
- 校验：四个新栈 store 的 URL（`/api/history/<bc>` `/analytics` `/analytics/extras` `/timeline`）均**不含** `/analytics/sku` 子串 → 仍通过；任何回引旧 `/analytics/sku` 会被新扫描抓出。

**HC-P3-6（hasData 契约）：** 走势图是否「有数据」：
```
hasData = (任一月 sale_qty + retail_qty != 0) || (任一周 purchase_unit_price != null)
```
`hasData === false` 才显「无数据」占位；否则正常渲染（只有采购无销售 → 仍画折线；只有销售无采购 → 仅画柱）。

**HC-P3-7（负净销量不产生负高度——修旧 bug）：** 月度 `sale_qty` 含退货可为负，净 = `sale_qty + retail_qty` 可为负。柱高 **`max(0, 净)`**，**绝不**把负值喂 `<rect height>`（旧版 `renderTmlSvg` 负高度是 bug）。净为负的月：柱高 0 + tooltip 标「净退货 {|净|} 件」。Y 轴销量刻度 maxQ 用 `max(1, 各月 max(0,净))`，避免除零。

**HC-P3-8（折线/坐标/tooltip 契约）：**
- **真阶梯折线**：水平保持 + 采购周垂直跳变的 step path（`H`→`V` 或显式 `L` 拐点构造直角），**不得**像旧版用普通 `L` 在两点间画斜线。前向填充（null 沿用上次进价）+ 反向外推（最早进价前段用首值）后，相邻不同价之间走「先水平到跳变点、再垂直到新价」。
- **同价特殊分支**：全程仅一个进价（`maxP == minP`）→ 折线固定图中段（避免贴地/贴顶），右轴只显 1 个对应价格 tick（**非** 0→max 比例）。
- **双 Y 轴**：左=销量（0→maxQ，4 tick），右=进价（0→maxP，多 tick；同价分支例外见上）。SVG 内 `<text>` 画轴（正常 viewBox + 默认 preserveAspectRatio，**不**用 HTML overlay）。
- **tooltip 用 SVG 原生 `<title>`**（无 JS，可访问）。柱：`{month_start} 月：{净} 件`（负净加「净退货」）；进价 dot：`{week_start}：€{landed}`，CN 货（`currency_local==='RMB'` 且 `raw != null`）追加 `← ¥{raw}（落地含汇率+可用海运分摊）`——**只展示 ¥raw→€landed，不硬编码 /7.8 或公式数字**（payload 无 rate 字段）。
- **dot 仅打真实进货周**（`raw_unit_price_local != null` 的周），非前向填充周不打点。

---

## 后端

### 端点（`app/routes/history.py` 的 `api_bp` 加路由）
```python
@api_bp.get("/<barcode>/timeline")
def timeline(barcode: str):
    from app.schemas_api import SkuTimelineResponse
    from app.services import analytics as analytics_service

    bc = barcode.strip()
    payload = {
        "ok": True,
        "timeline": analytics_service.compute_weekly_timeline(bc),
        "monthly_sales": analytics_service.compute_monthly_sales(bc),
    }
    return jsonify(SkuTimelineResponse.model_validate(payload).model_dump())
```
- 路由 `/api/history/<barcode>/timeline`（不与 P1 `GET ""` / 2a `/<bc>/analytics` / 2b `/<bc>/analytics/extras` 冲突）。
- 无 404（只命中后调；空数据=合法零值/None）。异常冒泡 Flask 通用 500（HC-P3-3 原子）。`/api/*` 未登录 → JSON 401。

### pydantic schema（`app/schemas_api.py`，逐字段对齐 metrics.py:213-371）
```python
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
```
`API_MODELS` 追加 `SkuTimelineResponse`，`python tools/gen_ts_types.py` 同步。

---

## 前端

### VM（`frontend/src/pages/history/timeline-types.ts`）
```typescript
export interface TimelineWeekVM {
  weekStart: string; saleQty: number;
  purchaseUnitPrice: number | null;
  rawUnitPriceLocal: number | null;
  currencyLocal: string;
}
export interface MonthlySaleVM {
  monthStart: string; saleQty: number; retailQty: number;
}
export interface TimelineVM {
  weeks: TimelineWeekVM[];
  monthlySales: MonthlySaleVM[];
}
```

### normalize（`frontend/src/pages/history/timeline-normalize.ts`，单点收窄）
入 `SkuTimelineResponse` → 出 `TimelineVM`，snake→camel，null 透传（价格字段保 null，SVG 计算据此判前向填充/dot）。数值 helper 仅对非空整数字段兜底。

### store（`frontend/src/stores/skuTimeline.ts`，HC-P3-3/4）
独立 pinia setup store：`vm: TimelineVM | null`、`loading`、`error`、`load(barcode)`、`reset()`、闭包级 `let seq = 0`。`load` URL = `/api/history/${encodeURIComponent(barcode)}/timeline`；HC-B7 守卫（`my=++seq` + 三写入分支 `if (my!==seq) return` + finally `if(my===seq)`）；`reset()` `seq++`；401 吞 `UnauthenticatedError`；`load` 开头清 vm。与其它 store 完全独立。

### 组件（`frontend/src/pages/history/TimelineChart.vue`）
Props：`weeks: TimelineWeekVM[]`、`monthlySales: MonthlySaleVM[]`。**封装全部 SVG 计算与渲染**（HistoryPage 只管状态+位置）。computed 产出：
- `hasData`（HC-P3-6）；false → 渲染「无数据」占位，return。
- 月柱：`barHeight = max(0, saleQty + retailQty)`（HC-P3-7）；`maxQ = max(1, ...各月 barHeight)`；柱宽按 36 桶均分；`<title>` tooltip（负净标「净退货」）。
- 进价序列：前向填充 + 反向外推 → 每周有效 price；`sameValue = maxP===minP`。
- 折线：**真 step path**（HC-P3-8）；`sameValue` → 中段水平线。
- dot：仅 `rawUnitPriceLocal != null` 的周；`<title>`（CN 货拆 ¥→€）。
- 双 Y 轴 + X 月份标签：SVG 内 `<text>`，正常 viewBox + 默认 preserveAspectRatio。
- 颜色仅用 token 变量（`var(--accent)` / `var(--accent-dim)` / `var(--warn)` / `var(--line-soft)` 等），无硬编码色。

### HistoryPage 接线（`frontend/src/pages/history/HistoryPage.vue`）
- import + `timelineStore = useSkuTimelineStore()`。
- runSearch 命中分支（`fresh && !store.error && kind==='hit'`）并列 `timelineStore.load(bc)`；非命中/失败 `timelineStore.reset()`。doReset 加 `timelineStore.reset()`。
- 模板：在「概况」之后、「销售分析 SLA」之前插入图块（仅命中显）：
  - `timelineStore.loading` → 「走势图加载中…」；`timelineStore.error` → 图块错误条（**不影响** P1/2a/2b，HC-P3-3）。
  - `timelineStore.vm` 就绪 → `<TimelineChart :weeks="vm.weeks" :monthly-sales="vm.monthlySales" />`。

### 不动 router / nav（P1 已翻 routeName）。

---

## 测试 / 验收

### 后端（`tests/test_history_timeline_api.py`）
- 未登录 → 401。
- 命中（seed stockpile + sale/purchase events）→ 200，**key 恰好 `{ok, timeline, monthly_sales}`**；`timeline` 长 156、`monthly_sales` 长 36，字段/类型对。
- 空货号（无 events）→ 200，timeline 全零/None、monthly_sales 全零（合法）。
- CN 货（origin CN + purchase event）→ 对应周 `raw_unit_price_local != null` 且 `currency_local=='RMB'`、`purchase_unit_price` 为 EUR 落地。
- `compute_weekly_timeline` / `compute_monthly_sales` 分别 mock 抛错 → 500（HC-P3-3 原子，逐个）。
- seed 走 SQLAlchemy（参照 `tests/test_history_extras_api.py`）。

### 前端（vitest）
- `timeline-normalize.test.ts`：camelCase + null 价格透传 + 长度保持。
- `skuTimeline.test.ts`（store）：load 填 vm / 失败填 error / 401 吞 / 调对端点 / 旧 vm 新 load 失败→null / **HC-B7 stale（A 后到不覆盖 B）** / **reset 作废 pending**。
- `TimelineChart.test.ts`（组件，重点）：
  - **hasData=false**：全桶填充但 sale/retail 全 0 且 price 全 null → 渲染「无数据」，不画柱/线。
  - **只有采购无销售** → 仍画折线（无柱）。
  - **只有销售无采购** → 画柱，无折线/dot。
  - **负净销量月不产生负 height**（断言 rect height >= 0；tooltip 含「净退货」）。
  - **两次不同进价 → path 含阶梯跳变**（断言 path 有垂直段 / 直角，非单纯斜线）。
  - **同价分支** → 折线中段 + 右轴单 tick。
  - dot 仅打真实进货周；CN tooltip 文案含 `¥` 与 `€`。
- `HistoryPage.test.ts` 扩展：命中触发 `timelineStore.load(bc)` 且图渲染在「概况」后「SLA」前；图失败→图块错误但 P1/2a/2b 正常（HC-P3-3）；401 不显图块错误；非命中 `timelineStore.reset()` 被调。

### 守护（HC-P3-5）
- `no-analytics.test.ts` 改造后：FORBIDDEN=`["/analytics/sku"]`；扫描集含 `stores/skuTimeline.ts` + `skuAnalytics.ts` + `skuExtras.ts` + `pages/history/*` + `stores/history.ts`；**断言确实扫到 skuTimeline.ts**（如断言扫描文件数 / 文件列表含该文件）；全通过。

### 最低验收（用户定）
命中后走势图加载且位置正确 ✓ / 图失败不影响 P1·2a·2b ✓ / 负净月不崩、step 折线 ✓ / hasData 空态正确 ✓ / 守卫真扫新栈 store ✓ / 旧页深链仍可访问 ✓

---

## 审查修订记录（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 1 | 调整 | 仅改 FORBIDDEN=`["/analytics/sku"]` 但不扩扫描集 = 假保护（skuTimeline/skuAnalytics/skuExtras 从不被扫） | HC-P3-5：扫描集纳入三个 sku* store + 改名 + 断言扫到 skuTimeline |
| 2 | 确认 | 独立 TimelineChart.vue 组件边界 | 采纳（组件封装 SVG，HistoryPage 管状态+位置） |
| 3 | 确认 | SVG 内 `<text>` 画轴、正常 viewBox、去 HTML overlay | 采纳（HC-P3-8） |
| 4 | BLOCKER | hasData 语义未定义 | HC-P3-6 写死 hasData 公式 + 仅 false 显「无数据」 |
| 5 | BLOCKER | 月净销量含退货可负，旧版负 `<rect height>` bug | HC-P3-7：柱高 `max(0,净)` + 负净 tooltip 标「净退货」+ maxQ 防零 |
| 6 | 契约 | 旧版 `L` 斜线非真阶梯 | HC-P3-8：真 step path（水平保持+垂直跳变） |
| 7 | 契约 | 同价分支非 0→max 比例 | HC-P3-8：折线中段 + 右轴单 tick |
| 8 | 契约 | tooltip 实现 + CN 硬编码 /7.8 | HC-P3-8：SVG `<title>`；CN 仅展示 ¥raw→€landed，不硬编码公式 |
