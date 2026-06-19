# 货号历史页 Phase 4b.5（信息架构重排：左固定 概况/深度 + 右弹性折叠卡）设计

**状态：** 已批准（2026-06-19，设计终审 APPROVE）。两轮设计审查处置：第一轮（container query 不用视口媒体查询 / 放宽 max-width / 左栏固定宽度非 position:fixed / 完整 ARIA / 换 SKU 重置 / 共享 store 错误态 / nullable restock 空态 / 折叠断言用 isVisible）；第二轮 APPROVE + 三建议（flex 子项 min-width:0 / tabs 改普通按钮+aria-pressed 避 roving tabindex / §1 注明只改生产代码）。

## 背景与目标

新 Vue `/ui/history` 货号查询 tab 当前是**扁平单列**，比旧 Alpine 页（`/?page=history`）的「左固定 概况/深度 + 右弹性折叠卡」仪表盘**明显朴素**。直接 Phase 4c 退役旧页会造成**视觉降级**。本期（4b.5）只迁旧页的**信息架构**到 Vue 页，达到视觉验收后再做 4c。

**不做**：不抄 Alpine 代码（`history.js`/`_page_history.html` 仅作 IA 参照）；不迁旧全局顶栏（App Shell 已提供壳）；不动批次记录 tab（4a/4b）、不动 App Shell、不动路由、不动任何 store/API/组件内部。

## 范围

**纯前端模板 + CSS 重排，零业务/数据逻辑变更。** 本期新增的仅是两个 **UI 状态**（`leftTab` + 折叠状态 `cardOpen`）。

- **复用现有一切不动**：`history` / `skuAnalytics` / `skuExtras` / `skuTimeline` 四个 store、所有 `/api/*` 端点、`TimelineChart.vue` 组件、`static/css/tokens.css` 设计 token。
- **生产代码只改 `frontend/src/pages/history/HistoryPage.vue`**（货号查询 tab 命中态的模板结构 + scoped CSS）。折叠卡是该文件内的**模板/CSS 模式**（重复的卡头/卡身结构 + scoped class），**不新建组件**。
- 测试文件 `HistoryPage.test.ts` 会改（替换过时断言 + 新增）。

## 布局架构（§2）

货号查询 tab **命中态**（`result.kind === "hit"`）改为两栏：

```
.history（内容区，container-type: inline-size, max-width ~1400px, margin auto）
└─ .history__cols（命中态才渲染；flex）
   ├─ .history__left   flex: 0 0 340px; min-width: 0;   （Hero + 概况/深度）
   └─ .history__right  flex: 1 1 0;   min-width: 0;       （5 张折叠卡，纵向 flex）
```

- **容器查询而非视口媒体查询**：`container-type: inline-size` 设在 `.history`（内容区，其 inline-size ≈ 扣除 App Shell 侧栏后的真实主内容宽度）；`@container (max-width: 900px)` 时 `.history__cols` 改 `flex-direction: column`、`.history__left` 改 `flex-basis: auto`，左栏置顶、右卡堆其下。**不用** `@media (max-width:…)`（视口宽含侧栏，1200px 窗口扣侧栏剩 ~980px 却仍判两栏 → 挤）。
- **「左栏固定」= 固定宽度** `flex: 0 0 340px`，**非** `position: fixed`。比旧版 320px 略宽，给 深度 的热力图/客户表喘息。
- 两栏 flex 子项均 `min-width: 0`，防长本地品名 / SVG / 表格撑破右栏（flex 子项默认 `min-width:auto` 会溢出）。
- `.history` 的 `max-width` 从 **1100px 放宽到 ~1400px**（`HistoryPage.vue:552`），逼近旧页空间利用率。
- **非命中态**（notfound / fuzzy / 初始 / 加载 / 错误）维持现状单列，**不进两栏**。
- 批次记录 tab、搜索框、RECENT chips、PageHeader、「查看完整分析（旧版）→」深链全保留不动（4c 才删深链）。

## 左栏：Hero + 概况/深度（§3）

- **Hero**（复用现有）：货号 / 条码 / 在售-停售 pill / 数量 / 复制按钮。
- **概况/深度 切换**：两个**普通按钮** `<button type="button" :aria-pressed="leftTab === 'overview'">概况</button>` / `…'deep'…>深度</button>`（不用 `role=tablist` 以免引入 roving tabindex + 方向键导航；2 态 toggle 用 `aria-pressed` 可达性等价）。状态 `const leftTab = ref<"overview" | "deep">("overview")`。**切换独立于右栏**（只换左栏内容，右卡不受影响——对齐旧版）。
- **概况**（默认）：复用现有 overview `<dl>`（品名 / 本地品名 / 店面位置 / 仓库位置 / 售价 / 来源 / 最后更新）。
- **深度**：复用现有 `skuExtras` 区块（退货率+价格波动 / 零售汇总 / CN·老外客户 TOP 表 / 月度热力图 / 持仓+预测），含其 `extrasStore.loading` / `extrasStore.error` 加载/错误态。深度栏的 **TOP 表 + 月度热力图加 `overflow-x: auto`** 横向溢出保护（340px 容不下时局部横滚，不撑破布局）。
- **RST 补货快照不在左栏**——移到右栏当卡片（对齐旧版 IA：RST 是右侧卡，不在 深度 tab）。

## 右栏：5 张折叠卡（§4）

复用 HistoryPage.vue 内的卡片模板/CSS 模式（非新组件）。折叠状态：

```ts
const DEFAULT_CARD_OPEN = { sla: true, pur: true, rst: false, tml: false, his: false } as const;
const cardOpen = ref<Record<"sla"|"pur"|"rst"|"tml"|"his", boolean>>({ ...DEFAULT_CARD_OPEN });
function toggleCard(k: keyof typeof DEFAULT_CARD_OPEN) { cardOpen.value[k] = !cardOpen.value[k]; }
```

| 卡 | 徽标 | 内容（复用现有区块 / store） | 默认 |
|---|---|---|---|
| 销售分析 | SLA | `analyticsStore` SLA（总销量/营收/独立客户/寿命/12周趋势）+ CN/老外拆分卡 | **开** |
| 采购面 | PUR | `analyticsStore` PUR（库存推算/毛利率/365天采购/上次采购） | **开** |
| 补货决策快照 | RST | `extrasStore` restock（财务/库存/累计盈亏/销售26周/紧迫分） | 关 |
| 销售/进价时间线 | TML | `TimelineChart.vue`（组件不动，挪进卡身） | 关 |
| 历史时间线 | HIS | `history` events（时间倒序） | 关 |

- **卡头** = `<button type="button" :id="'sbcard-<k>'" :aria-expanded="cardOpen.<k>" :aria-controls="'sbpanel-<k>'" @click="toggleCard('<k>')">`（含徽标 + 标题 + chevron）。**卡身** = `<div :id="'sbpanel-<k>'" role="region" :aria-labelledby="'sbcard-<k>'" v-show="cardOpen.<k>">`。
- 多卡可同时展开；折叠用 `v-show`（内容保留在 DOM）。**TML 用 `v-show` 安全**：`TimelineChart` 是固定 viewBox SVG，不依赖挂载时测宽。
- **SLA / PUR 拆成两张独立卡，但共享 `analyticsStore`**：两张卡身各自渲染 `analyticsStore.loading`（「加载中…」）/ `analyticsStore.error`（错误条），任一态两卡都显示（同源 store）。
- **RST 卡渲染 `extrasStore.loading` / `extrasStore.error`；`extrasStore.vm.restock === null` 时卡身显示「暂无补货快照」**（不留空卡）。

## 换 SKU 重置（§3+§4 红队：状态泄漏）

每次命中**新 barcode** 时，`leftTab` 重置为 `overview`、`cardOpen` 重置为 `DEFAULT_CARD_OPEN`，防 SKU A 的「深度」/折叠态泄漏到 SKU B。机制 = 监听命中 barcode 变化（覆盖搜索 + RECENT chip 两条路径）：

```ts
const hitBarcode = computed(() =>
  store.result?.kind === "hit" ? store.result.current.barcode : null);
watch(hitBarcode, (bc) => {
  if (bc) { leftTab.value = "overview"; cardOpen.value = { ...DEFAULT_CARD_OPEN }; }
});
```

## 错误处理 / 边界

- 左栏 深度：`extrasStore` 加载/错误/空态沿用现有渲染（仅位置从单列移入左栏 深度 tab）。
- 右栏 SLA/PUR：共享 `analyticsStore` loading/error，两卡各自显示。
- 右栏 RST：`extrasStore` loading/error + `restock === null` → 「暂无补货快照」。
- 非命中态不进两栏，维持现状。
- 重排不改任何 store 的请求/并发/重置逻辑（HC-B7 代际守卫等全不动）。

## 测试（§5）

**组件测试（`HistoryPage.test.ts` 扩展 + 修订）：**
- 命中态渲染 `.history__cols` 两栏；非命中态不渲染两栏（维持单列）。
- 概况/深度 toggle：点「深度」→ 左栏显示 深度 内容（退货率等）且右卡不变；`aria-pressed` 随切换。
- 右卡折叠 toggle：点卡头 → `aria-expanded` 翻转、卡身 `isVisible()` 翻转（**用 `isVisible()` 不用文本存在**，因 `v-show` 内容仍在 DOM）。
- 默认折叠态：SLA/PUR 卡身可见、RST/TML/HIS 不可见。
- 右栏卡片**顺序断言** SLA→PUR→RST→TML→HIS（**替换**现有「概况 dl 在走势图前」的旧单列顺序断言）。
- **换 barcode 重置**：先命中 A 切到 深度 + 展开 RST，再命中新 barcode B → `leftTab==='overview'` 且 RST 折叠回默认。
- **RST 空态**：`restock === null` → RST 卡存在且卡身显示「暂无补货快照」（**更新**现有「restock null → 补货快照面板不存在」断言为新空态）。
- SLA/PUR 在 `analyticsStore.error` 时两卡各显错误条；RST 在 `extrasStore.error` 时显错误。

**浏览器人工验收（组件单测不验真实 flex/container 布局）：**
- 宽内容宽度（≥900px container）：两栏，左 340 + 右弹性，对照旧页布局。
- 窄内容宽度（<900px container，含 App Shell 侧栏挤压场景）：堆叠，左栏置顶。
- 两档均**断言无水平滚动条**（min-width:0 + overflow-x 保护生效）。
- 本地 `/ui/history` 与旧 `/?page=history` 并排对照，用户最终拍板视觉够格再进 4c。

**回归：** 既有 7 状态 / RECENT / 批次子-tab / no-analytics / 预测过期徽标等测试继续全绿（重排不改数据流）。

## 不做（YAGNI）

折叠态不持久化（localStorage）；不复刻旧顶栏；不动批次记录 tab；不改 store/API/组件内部；不引表格/折叠库；不做 4c 退役（视觉验收后另起）。
