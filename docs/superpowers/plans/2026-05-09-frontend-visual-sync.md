# Frontend 视觉对齐 plan（DataOps Terminal handoff）

**起草日期**：2026-05-09
**最后更新**：2026-05-11
**当前状态**：✅ **全部完结** — 13/13 PR 已 ship（12 done + 1 dropped）

## 起因

用户反馈：当前前端跟 `C:\Users\jxwu2002\Downloads\ui_ (1)\design_handoff_dataops_terminal\`（DataOps Terminal handoff）在视觉上仍有显著差距。

具体：查重页"完全不一样"、采购页"完全没同步"、考勤"细节差异"、货号历史"明显细节差异"、数据质量"明显差异"，互传应该搬到左侧栏（不在汉堡）、终端日志浮窗不要前端显示了、左上角 logo 和浏览器 favicon 都重新设计了。

**这是视觉对齐 plan，不是新功能 plan**。

## design handoff 关键参考文件

- **`DIMENSIONS.md`** —— 像素级尺寸规范（必读，是 source of truth）
- `README.md` —— overview + design tokens (颜色/字体/spacing/radius)
- `logo-favicon.md` —— logo 与 favicon 设计规范
- `transfer-module.md` —— 互传模块（升级到顶级 nav 项 module 10）
- `sidebar-icons.md` —— 侧栏 9 个图标规范
- `data-terminal.html` 与 `src/*.jsx` —— 各页结构源
- `src/pages-extra.jsx` —— Purchase / Attendance / Dedupe / Quality / Inout / Overseas
- `src/pages-history.jsx` —— SkuHistoryPage 三个子 tab
- `src/pages-sales.jsx` —— Sales Analysis
- `tweaks-panel.jsx` —— prod 不要

## 已完成（13/13 全 ship）

| 批 | audit PR# | GitHub PR | merged commit | 标题 |
|---|---|---|---|---|
| A | 1+2 | #7  | `9ae0848` | feat(branding): logo + favicon 换终端光标风（>_） |
| A | 3   | #8  | `314d570` | refactor: 删前端终端日志浮窗（保留 activityPanel + store API） |
| A | ~~13~~ | N/A | — | ~~主页右栏 ActivityLog 删除后 right-stack 收口~~ — **取消**：用户保留 #activityPanel |
| B | 5   | #9  | `9da8ab5` | feat(dedupe): 标签查重页按设计重做（4 stat + 工具条 + 4 group panel） |
| B | 6   | #10 | `2487f95` | feat(purchase): 采购页按设计重做（upload zone + 真表格 + footer + history） |
| C | 4   | #12 | `abda18d` | feat(transfer): 互传从 FAB 抽屉搬到 nav module 10（pageTransfer 2 列） |
| D | 7   | #13 | `cb4d688` | feat(history): 货号历史 子 tab 头按设计重做 |
| D | 8a  | #14 | `3240f3a` | feat(history): 货号查询 4 卡按设计重做（CUR/SLA/PUR/HIS） |
| D | 8b  | #15 | `29b9937` | feat(history): TML 52 周 chart 从 canvas 重写为 SVG |
| E | 9   | #16 | `5a030ff` | feat(history): 最近改动重做 + 持久 QUERY 大 panel + GradeBadge |
| E | 10  | #17 | `2083442` | feat(data-quality): 数据质量页按设计重做（banner + 2 stat + 2 panel） |
| E | 11  | #18 | `5cd21e3` | feat(foreign-customers): 老外客人页按设计重做（控制条 + 5 stat + REC panel） |
| E | 12  | #19 | `86b3eff` | feat(inventory): 进销存导入页按设计重做（卡片 radio + DB-STATE + RECENT） |

> Plan 文档自身：`#11` (`26e9d42`) docs(plan): frontend 视觉对齐 plan 存档。
> 本次终结收尾 PR 见 git log 末尾。

## 完结小结

视觉对齐 13-PR 计划于 2026-05-11 全部 ship。所有 9 页（含互传新增）全部按 design handoff 重做：
- 全站 token 化：`var(--bg-*)` / `var(--ink-*)` / `var(--accent)` / `var(--mono)` 等统一约定
- 5 页都有 PanelHeader (code + title + sub + actions) 模式
- 多页用 stat box grid + tone（accent/info/warn/error）
- 全表格统一 mono 11.5 + sticky thead uppercase + zebra + accent hover
- 状态/类型 pill 全套（accent/info/warn/error 色）
- ghost / primary CTA 同款
- 多页 lazy load on first nav switch（sa/dq/dup/inventory）

后端 0 改动 — 所有 PR 都纯前端 + 复用现有 endpoint 协议。

不在本 plan 范围（仍是 backlog）：
- Frontend bundler (Vite/esbuild) — 等真要装 npm 包
- alembic check 3 个 PK NOT NULL diff — 等真改 schema 时一并
- R10 Pipeline 5 stage 真 SSE — 等 SSE 实现
- Header 全局搜索 ⌘K — YAGNI
- Accent presets / Background grid toggle — Tweaks 自删
- 货号查询销售/采购 stat 缺项 + ExceptionsPanel inline actions — 功能差异，不在视觉对齐

---

## PR 4 · 互传模块从 FAB 抽屉搬到左侧栏 module 10 ✅ 已 merge (PR #12)

> 简化版实施：设计的 ConnectionBar 4 metric (配对码/延迟/带宽/在线)、send/recv queue 区分、传输历史 后端无数据 → 跳过这些；保留 ConnectionBar light + 2 列主区（文件互传 + 文字互传）。所有 element ID + store API 保留，后端 `routes_transfer.py` 0 改动。



**目标**：设计 `transfer-module.md` 把它升级成顶级 nav 项（10 号），左侧 ⇄ 图标，主区是 3×3 grid 的完整 page；当前还是右下抽屉。

**当前**：
- FAB `#transferFab` (`templates/index.html:712-715`) + 抽屉 `aside#transferDrawer` (`index.html:717-763`) 浮在所有页之上
- `static/js/store.js:62-66` `ui.toggleTransfer` 控制 `transferDrawer` boolean
- `static/css/widgets/transfer-drawer.css` 全是右滑 320px 抽屉的样式
- quickmenu 里也有"文件互传"入口 (`index.html:791-796`)
- 侧栏 `nav.pages` 只有 9 项 (`store.js:151-161`)

**改成**（参 `transfer-module.md` §24-58）：
- `store.js:151-161` 加第 10 项 `{ id: 'transfer', label: '互传', icon: 'transfer', code: '10', shortcut: '0' }`
- `index.html` SVG sprite 加 `#icon-transfer`（用 sidebar-icons.md inout 的 ⇄ 风格变体或 lucide `arrow-left-right`）
- `MODULES · 09` 改成 `· 10`（`layout.css:75` + `index.html:103`）
- `index.html` 加 `<div class="page" id="pageTransfer" :class="$store.nav.current === 'transfer' ? 'active' : ''">`，按 transfer-module.md 写 3 列 × 3 行 grid（`gridTemplateColumns: '1fr 1fr 360px'` `gridTemplateRows: 'auto 1fr auto'`）：ConnectionBar / Send Queue / Recv Queue / Chat Panel / Transfer History
- 删掉 FAB / drawer / quickmenu 里的入口；保留 `Alpine.store('transfer')` `Alpine.store('messages')` API
- 新增 `static/css/page-transfer.css`，`widgets/transfer-drawer.css` 整个废弃

**改动文件**：
- `templates/index.html` (line 87 sprite、line 103 module 计数、line 712-763 删 FAB+drawer、line 785-804 删 quickmenu transfer 项、新增 pageTransfer 块)
- `static/js/store.js` (line 151-161 加项；line 53-79 删 `transferDrawer`/`transferDot`/`quickTransferDot`)
- 新建 `static/css/page-transfer.css`
- `templates/index.html:21` 删 transfer-drawer.css 引用
- 后端 `routes_transfer.py` 完全不动

**估时**：~5h（结构最大改动）。

**风险**：transfer 既要 page 化又要保后端 API/状态，要小心 `Alpine.store('ui').transferDrawer` 和 `quickTransferDot` 被其他模块引用（`messaging.js` / `transfer.js` 可能 push 红点），`grep -rn "transferDot\|transferDrawer\|quickTransfer" static/` 全删干净。

---

## PR 7 · 货号历史 子 tab 头部对齐设计

**目标**：当前子 tab 用 emoji glyph + 普通字体，设计是 mono glyph + active 时 2px accent 底边 + 9.5 mono code label 风。

**当前** (`templates/index.html:419-423`)：
```html
<button class="tabs__tab">🔎 货号查询</button>
<button class="tabs__tab">📊 最近改动</button>
<button class="tabs__tab">📂 扫描批次</button>
```
样式来自 `static/css/components.css` 的 `.tabs`，效果与 `pages-history.jsx:33-57` 不一致。`page-history.css:1-12` padding 是 `20 24`，设计是 `padding: 14`。

**改成** (参 `pages-history.jsx:24-57` + DIMENSIONS.md §3.3)：
- `#pageHistory.active` padding 改成 14, gap 14
- 子 tab：`padding: 11px 14px`，glyph 用 mono `⌕ ◷ ⊞` (font 13)，active 时 `border-bottom: 2px solid var(--accent)`、color ink-0 weight 600；inactive ink-2 weight 500
- 搜索行：参 `pages-history.jsx:60-91` 改成 `<div>` 包 input 样式（accent ⌕ 前缀 + ↵ kbd 后缀），按钮高 34、`查询` lg primary、`重置` lg ghost
- 加 RECENT chip 行（最近查过的 6 个 SKU 横排 mono chip）

**改动文件**：
- `templates/index.html` (line 419-423)：tab DOM 改字
- `static/css/page-history.css` (line 1-50 + 新增子 tab 段)：padding/font/glyph 全调

**估时**：~2h。**风险**：低；只改头部，下面 `historyCurrentPanel` 等内容不动。

---

## PR 8 · 货号历史 - 货号查询子页（5 卡）按设计重做

**目标**：设计是 5 个独立 panel（CUR / SLA / PUR / TML / HIS），每个有 PanelHeader（code + 标题 + sub + 右侧 actions）；当前只有 5 个普通 `.panel` 标题字。

**当前** (`templates/index.html:441-466` + `static/js/history.js:295-376` 渲染)：
- `historyCurrent` 用 `kv-grid`（`auto-fill, minmax(220px, 1fr)`），不是设计的固定 4 列
- `historyAnalytics` 把销售面/采购面/客户拆分都塞一个 panel 里
- `historyTimelineChart` 用 canvas 280px 高（设计是 SVG 200 高）+ 自家 chart-legend
- 没有 ClientCard 那种带 `border-left: 2px` 的 GR/CN 二列布局

**改成** (参 `pages-history.jsx:413-654`)：
1. **CurrentStateCard** (`CUR`): `display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px 24px;`、11 个字段（mono label 9.5 letter 0.1em + value 13 mono/sans）、PanelHeader 右侧加 `编辑` `复制货号` ghost xs btn
2. **SalesAnalysisCard** (`SLA`): 拆出来独立 panel，分 `SALES SIDE` (4×4 grid, 8 个 KV) + `CLIENT SPLIT` (CN/GR ClientCard 二列，每个 border-left 2px 标签色)
3. **PurchaseCard** (`PUR`): 4 列 grid `repeat(4, 1fr)` 4 个 KV + 底部 warn 提示 box (border-left 2px warn, 背景 `rgba(255,182,39,.05)`)
4. **TimelineCard** (`TML`): 改用 SVG 200px 高，柱 + 折线（`pages-history.jsx:695-755` 算法），右上角加 `销量(柱) accent pill` + `进价(折线) warn pill` + `导出 ghost btn`
5. **HistoryTimeline** (`HIS`): 真时间线（每条左侧 10px 圆点 + 1px 竖线，参 `pages-history.jsx:809-854`）

**改动文件**：
- `templates/index.html` (line 441-466)：5 个 panel DOM 重写（保留 hidden state）
- `static/js/history.js` (line 295-450+ renderAnalytics/renderResult)：渲染函数全改
- `static/css/page-history.css` (line 100+ kv-grid/cust-split/cat-row 等)：增 ClientCard / TimelineEvent / KV 样式
- 52 周 chart 改用 SVG 实现（取消 canvas）

**估时**：~6h。

**风险**：高 —— 是改动量最大的 PR。后端 `/analytics/sku/:bc` 协议不动（`s.total_qty` `cs.cn` 字段都用），但 timeline canvas → svg 是从头写。如果 timeline chart 风险大可以拆 PR 8a (CUR/SLA/PUR/HIS) + 8b (52 周 chart)。

---

## PR 9 · 货号历史 - 最近改动子页 5 stat + filter chip 重做

**目标**：当前 batch select + summary + chips + list 风格散；设计是顶部 batch panel + 5 stat box grid + 5 个 filter chip 按钮 + table。

**当前** (`templates/index.html:470-485` + `static/js/index-recent-changes.js`)：`rcSummary` `rcChips` `rcList` 三个 div 全是自定义 class，无 stat box，filter chip 风格不一致。

**改成** (参 `pages-history.jsx:164-297` `RecentChangesPanel`)：
1. **Batch picker panel** (PanelHeader `BATCH` + `展开 raw 事件` ghost CTA)：内部 select height 32 minWidth 360 mono
2. **5 stat grid** `grid-template-columns: repeat(5, 1fr); gap: 10`：库位变更 / 型号变更 / 新增 / 失效 / 重新上架（StatBox 风格，padding `12 14`、数字 22 weight 600，tone 按 count 0/>0 切 default/accent/warn/error/info）
3. **来回波动注**：单行 mono 11px ink-3 文字
4. **Filter tabs** padding 10 + 6 个 chip，active 时 `bg accent / color bg-0 / weight 700`，inactive `bg bg-3 / color ink-1 / border line`，每个 chip 右侧 `count` mono 10
5. **List**：mono 11.5 表格，列 `货号 型号 变化 时间`，"变化" cell 按 kind 用不同 inline-flex chip（loc 用 `→` 箭头分隔，new/expire/restock 各一个 colored bg+border 圆角 chip）

**改动文件**：
- `templates/index.html` (line 470-485)：DOM 重写
- `static/js/index-recent-changes.js`：`renderSummary` `renderChips` `renderList` 函数全改
- `static/css/page-history.css`：增 `.rc-stat-grid` `.rc-filter-chip` `.rc-list-table` 段

**估时**：~3h。**风险**：低，独立子 tab。

---

## PR 10 · 数据质量页 加 banner + 4 stat

**目标**：当前只有 hint + 2 panel（multi/flippers），设计有顶部 info banner + 4 个 StatBox + DQ-01 panel 表格。**设计 README 与 jsx 自相矛盾，按 jsx 为准**。

**当前** (`templates/index.html:504-532` + `static/js/data-quality.js`)：
- 只有 dqHint panel（一段说明文字）
- 2 个隐藏的 dq-section panel（multi-kind / flippers），样式来自 `static/css/page-data-quality.css`，简单 dq-table

**改成** (参 `pages-extra.jsx:694-788` `QualityPage` + DIMENSIONS.md §3.7)：
1. **顶部 info banner**：`flex` 行，左 36×36 info 蓝方块 ⓘ 图标 + 中间标题"只读视图 · 数据质量诊断" + sub mono"本页只展示，不修改..." + 右侧 `READ ONLY` info pill + `刷新` primary CTA
2. **4 列 StatBox grid**：`同维度多库位 (warn) / 覆盖货号 (default) / warehouse 维度 (warn) / store 维度 (warn)`，每个 padding `12 14` 数字 22
3. **DQ-01 panel** (PanelHeader `DQ-01` + 右上 select"全部维度/warehouse/store" + `一键复制` CTA)：表格列 `# 条码 型号 当前 LOCATION 重复维度`，#列 ink-3，条码列 accent，重复维度列用 warn/info pill
4. flippers 那块保留作为第二个 panel（`DQ-02`）

**改动文件**：
- `templates/index.html` (line 504-532)：DOM 重写加 banner + stats grid
- `static/js/data-quality.js`：新增 `renderStats(report)` `renderBanner()`，表格渲染加分隔符 / pill
- `static/css/page-data-quality.css` (line 1-100)：增 banner / stat-grid 样式

**估时**：~2.5h。**风险**：后端 `/data_quality` JSON 已经有 `multi_same_kind.count` / `flippers.count` / `whitespace_anomalies.count` 等，可直接喂 stat。

---

## PR 11 · 老外客人页 5 stat + 状态 pill 对齐

**目标**：设计有 5 个 stat box（记录数/总欠款/已付/未付/已托运）+ 表格里 paid/unpaid/partial/overdue 4 种 pill；当前没 stat 也没规范 pill。

**当前** (`templates/index.html:533-590`)：fcSummary 一个 div 显示汇总文字、`.fc-table` 表格无 status pill 着色。

**改成** (参 `pages-extra.jsx:1135-1247` `OverseasPage`)：
1. 顶部控制条加 PanelTitleInline `OVS-MO` + 月份 select + `刷新` `下载 PDF` ghost + 右 `+ 新增记录` primary
2. **5 列 StatBox grid**：记录数 / 总欠款 (warn) / 已付 (accent) / 未付逾期 (error) / 已托运 (info)
3. 表格字段统一 mono 11.5，欠款列右对齐 warn 色，状态列改成 4 种 pill (`stMap`：paid=accent / unpaid=error / partial=warn / overdue=error)
4. 月份切换 → API 不变 (`/foreign_customers?month=`)，只是渲染 stat

**改动文件**：
- `templates/index.html` (line 533-572)：DOM 加 stats grid
- `static/js/foreign-customers.js`：`renderSummary` 改成 5 stat box；`renderRecords` 状态列改 pill
- `static/css/page-foreign-customers.css`：增 .fc-stat-grid

**估时**：~2h。**风险**：低；纯渲染层。

---

## PR 12 · 进销存导入页 radio 卡片 + db state 视觉化

**目标**：设计的 radio kind 是带 dot 的卡片按钮、db state 有 4 stat box + 客户类型分布水平 bar；当前是原生 radio + 文字 stats。

**当前** (`templates/index.html:592-635`)：原生 `<input type="radio">`、`#invStats` 是文字行、`#invImports` 也是文字。

**改成** (参 `pages-extra.jsx:791-958` `InoutPage`)：
1. **radio kind 改卡片按钮**：`padding 8 14`、border 1 + active 时 `accent / bg rgba(0,255,149,.06)`、左侧 10×10 圆 dot
2. **DB state panel** (PanelHeader `DB-STATE`)：4 stat grid (事件总数 accent / 客户 info / 供应商 / SKU accent) + 客户类型分布 4 pill + 右侧 320×6 水平堆叠 bar
3. **最近导入 panel** (PanelHeader `RECENT`)：mono 表格列 `时间 类型 文件 行数 OK 重复 错误 操作员`，类型 pill (purchase=accent / sales=info / product=warn)，OK 列 accent、重复 warn、错误 error
4. 终端风注释（`$ 上传 ERP 导出...`）放在 padding-top + border-top dashed 区

**改动文件**：
- `templates/index.html` (line 592-635)：DOM 重写
- `static/js/inventory.js`：`renderStats` `renderImports` 函数改
- `static/css/page-inventory.css`：增 inv-radio-card / inv-stat-grid / inv-cust-bar

**估时**：~3h。**风险**：低。

---

## 其它已知差异（不在本 plan 内）

这些项要么已被否决、要么属于另一类重构：

- **PR-FE-7d-3 考勤页对齐 design handoff**（1-1.5h）—— 在 `2026-05-06-frontend-redesign-v2.md` 已登记，等"用户看习惯"再上
- **R10 Pipeline 5 stage 真 SSE**（PR-FE-8d）—— 等真 SSE 实现时整体重写
- **Header 全局搜索 ⌘K**（中）—— 用户判断"侧栏切页够用"，YAGNI
- **Accent presets / Background grid toggle**（低）—— Tweaks panel handoff 自己说 prod 删掉
- **数据质量 README KPI 4 quadrant** —— 设计文档自相矛盾，按 jsx 为准（即 PR 10）
- **货号查询销售/采购 stat 缺项 + ExceptionsPanel inline actions**（功能差异）—— 不在视觉对齐范围

---

## 怎么恢复（下次新会话）

1. 打开 `C:\Users\jxwu2002\Desktop\label-sync`
2. 跟新 assistant 说：「**继续 frontend visual sync，读 docs/superpowers/plans/2026-05-09-frontend-visual-sync.md，按下面执行**」
3. 指定批次（例如"开批 C"或"做 PR 10"）
4. 新 assistant 应该：
   - 读本文件 + `git log --oneline -20` 确认进度
   - 读对应 design 源（`pages-extra.jsx` / `pages-history.jsx` 等）+ `DIMENSIONS.md`
   - 读对应当前文件（`templates/index.html` / `static/js/*.js` / `static/css/*.css`）
   - 实施前先确认（按既往习惯：每个 PR 改完起 dev server、用户手测 OK 再 commit + push + PR + merge）

## 维护

- **每完成一个 PR**：把上面"已完成"表加一行（PR# / 标题 / commit hash），从对应 PR 章节末尾加 `**已 merge**：commit-hash` 并把章节标题加 ✅
- **新发现差异**：补到"其它已知差异"或新开一节
- **需求变更**：在该 PR 章节加 `> 2026-XX-XX 调整：原 X，改 Y`，旧文不删
