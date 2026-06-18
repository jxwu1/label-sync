# 货号历史页迁移 Vue —— Phase 3（SVG 销售/进价时间线）设计

**状态：** 设计待批（2026-06-18）。三轮审查 REQUEST_CHANGES 已处置（#1-8 守卫/hasData/负净高度/step/同价/tooltip；#9-12 退货可命中标记+X 日期域+措辞+窄容器；#13-16 锁定三角规格/进价点周中点/data-kind 选择器/标签 anchor）。待用户审阅后落 plan。

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

**HC-P3-7（负净销量不产生负高度 + 可命中退货标记——修旧 bug + 修 tooltip 不可达）：** 月度 `sale_qty` 含退货可为负，净 = `sale_qty + retail_qty` 可为负。柱高 **`max(0, 净)`**，**绝不**把负值喂 `<rect height>`（旧版 `renderTmlSvg` 负高度是 bug）。Y 轴销量刻度 maxQ 用 `max(1, 各月 max(0,净))`，避免除零。
- **负净月（净 < 0）**：柱高 0 → 没有可悬停区域，故画一个**可命中的 warn 色小三角**：定位在**该月区间中心、baseline 上方**，**固定实际宽高**（如底 8px、高 6px，token warn 色），带稳定选择器 `data-kind="net-return"`，内部 `<title>` =「{month} 月：净退货 {|净|} 件」。解决红队场景（单负净月无采购 → hasData=true 但零高柱无 tooltip）。测试经 `data-kind="net-return"` 选中，不依赖 SVG 标签形状。
- 正净月：柱 `<rect>` 自带 `<title>`。零净月（净==0）：不画柱也不画标记。

**HC-P3-8（折线/坐标/tooltip 契约）：**
- **真阶梯折线**：水平保持 + 采购周垂直跳变的 step path（`H`→`V` 或显式 `L` 拐点构造直角），**不得**像旧版用普通 `L` 在两点间画斜线。前向填充（null 沿用上次进价）+ 反向外推（最早进价前段用首值）后，相邻不同价之间走「先水平到跳变点、再垂直到新价」。
- **同价特殊分支**：全程仅一个进价（`maxP == minP`）→ 折线固定图中段（避免贴地/贴顶），右轴只显 1 个对应价格 tick（**非** 0→max 比例）。
- **双 Y 轴**：左=销量（0→maxQ，4 tick），右=进价（0→maxP，多 tick；同价分支例外见上）。SVG 内 `<text>` 画轴（正常 viewBox + 默认 preserveAspectRatio，**不**用 HTML overlay）。
- **tooltip 用 SVG 原生 `<title>`**（无 JS，可访问）。柱：`{month_start} 月：{净} 件`（负净加「净退货」）；进价 dot：`{week_start}：€{landed}`，CN 货（`currency_local==='RMB'` 且 `raw != null`）追加 `← ¥{raw}（落地含汇率+可用海运分摊）`——**只展示 ¥raw→€landed，不硬编码 /7.8 或公式数字**（payload 无 rate 字段）。
- **dot 仅打真实进货周**（`raw_unit_price_local != null` 的周），非前向填充周不打点。

**HC-P3-9（X 共享日期域——月柱与周进价点时间对齐）：** 36 自然月与 156 自然周长度不等，**不得**各按数组下标均分宽度（旧版那样会让销量柱与进价点时间错位）。两序列统一映射到**同一日期域**：
- `t0 = min(首周 weekStart, 首月 monthStart)`；`t1 = max(末周 weekStart + 7d, 末月 monthStart 的下月 1 号)`（覆盖两序列全跨度）。
- `x(date) = padL + (date - t0)/(t1 - t0) * innerW`（日期解析用 `weekStart`/`monthStart` 的 `YYYY-MM-DD`）。
- 月柱：左沿 `x(monthStart)`，宽 `x(下月1号) - x(monthStart) - gap`（按当月真实时长，宽度随月长自然变化）；负净标记同样定位在 `x(monthStart)` 月区间内。
- 进价折线/dot：点 X = **`x(weekStart + 3.5d)`（周中点，写死，全程一致）**——数据是周聚合桶，点放周 slot 中心，与旧图语义一致。
- X 轴月份标签：取 ~7 个 monthStart，标签 X = `x(monthStart)`；**首尾标签须落在 viewBox 内**——**首标签 `text-anchor="start"`、末标签 `text-anchor="end"`、中间 `text-anchor="middle"`**（仅靠 x 坐标不足以证明文字不溢出，须配合 anchor 收边）。

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
- **X 共享日期域**（HC-P3-9）：算 `t0/t1`，`x(date)` helper；月柱与进价点都经它定位。
- 月柱：`barHeight = max(0, saleQty + retailQty)`（HC-P3-7）；`maxQ = max(1, ...各月 barHeight)`；柱左沿 `x(monthStart)`、宽 `x(下月1号)-x(monthStart)-gap`；正净柱 `<rect>` 带 `<title>`；**负净月画 baseline warn 标记**（可命中，带「净退货」`<title>`）；零净不画。
- 进价序列：前向填充 + 反向外推 → 每周有效 price；`sameValue = maxP===minP`。
- 折线：**真 step path**（HC-P3-8），点 X = `x(weekStart + 3.5d)`（周中点，HC-P3-9）；`sameValue` → 中段水平线。
- dot：仅 `rawUnitPriceLocal != null` 的周；`<title>`（CN 货拆 ¥→€）。
- 双 Y 轴 + X 月份标签：SVG 内 `<text>`，正常 viewBox + 默认 preserveAspectRatio；X 标签首尾收边在 viewBox 内（HC-P3-9）。
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
- 无事件 SKU（**非空但无 events 的 barcode**；注意空 barcode 匹配不上 `/<barcode>/timeline` path route，故用真实存在/任意非空且无事件的码）→ 200，timeline 全零/None、monthly_sales 全零（合法）。
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
  - **负净销量月不产生负 height + 退货标记可命中**（断言无 rect height < 0；存在 `[data-kind="net-return"]` 元素、有实际宽高、内部 `<title>` 含「净退货」——经选择器选中，不依赖标签形状）。
  - **红队场景**：单负净月、无采购 → hasData=true（不显「无数据」）且存在 `[data-kind="net-return"]` 可命中标记。
  - **两次不同进价 → path 含阶梯跳变**（断言 path 有垂直段 / 直角，非单纯斜线）。
  - **同价分支** → 折线中段 + 右轴单 tick。
  - **X 共享日期域对齐**（HC-P3-9）：给定已知日期的月柱 + 落在该月日历范围内的采购周，断言该进价点 X 落在该月柱的 X 区间内（证明同一时间域，无索引漂移）。
  - **窄容器**：小 viewBox/宽度下，X 轴首标签 x 在 `[0,W]` 内**且 `text-anchor="start"`**、末标签 x 在 `[0,W]` 内**且 `text-anchor="end"`**（仅查 x 不足以证明文字不溢出）。
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

### 第二轮审查（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 9 | BLOCKER | 负净月零高柱无悬停区 → 「净退货」`<title>` 不可达（红队：单负净月无采购=近空图无 tooltip） | HC-P3-7 补：负净月 baseline 画可命中 warn 标记承载 `<title>`，仍无负 height；测试加红队场景 |
| 10 | BLOCKER | 36 月 vs 156 周 X 坐标域未定义，索引均分会时间漂移 | HC-P3-9：两序列映射同一日期域 `x(date)`，月柱按真实月时长定宽定位；测试加同域对齐断言 |
| 11 | 建议 | 「空货号」措辞（空 barcode 匹配不上 path route） | 后端测试改「无事件 SKU/非空 barcode」 |
| 12 | 建议 | 缺窄容器测试 | TimelineChart 加窄容器 X 首尾标签在 viewBox 内断言 |

### 第三轮审查（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 13 | 锁定 | 负净标记仍「短横线或小三角」二义 | HC-P3-7 锁定：月区间中心、baseline 上方、固定宽高(底8/高6) warn 小三角 + `data-kind="net-return"` |
| 14 | 锁定 | 进价点 X：HC-P3-9 写「weekStart 或周中点二选一」与组件段「weekStart」冲突 | 统一锁定**周中点 `weekStart + 3.5d`**（周聚合桶语义，合旧图）；HC-P3-9 + 组件段 + 折线 X 三处一致 |
| 15 | 建议 | 负净标记测试依赖 SVG 标签形状 | 加稳定选择器 `data-kind="net-return"`，测试经它选中 |
| 16 | 建议 | 窄容器仅查 x 不足证明不溢出 | 测试加断言首标签 `text-anchor="start"`、末标签 `text-anchor="end"` |
