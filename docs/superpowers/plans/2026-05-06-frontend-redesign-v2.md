# 前端重构（v2）—— DataOps 数据终端风格

> **起草**：2026-05-06
> **设计输入**：`C:/Users/jxwu2002/Downloads/ui_/design_handoff_dataops_terminal/`
> **方向**：把当前 filing-cabinet 浅色单一主题，迁到「暗色专业数据终端」风格 +
> 一组系统级新功能（搜索 / 主题切换 / 折叠侧栏 / 键盘快捷键 / 子条信息带）。
> **技术约束**：**不引入 npm 包 / React / Vite**——继续 Flask + Jinja + Alpine.js +
> 原生 JS + Canvas 自绘。设计里的 React 要翻译成 Alpine + 模板。

---

## 1. 当前 vs 设计：结构对齐

9 个模块完全对得上：

| 设计 nav id | 当前 page id | 备注 |
|---|---|---|
| tags | pageMain | 标签处理 |
| dedupe | pageDup | 查重 — **设计扩了功能**（见 §3.10）|
| purchase | pagePurchase | 采购 |
| attendance | pageAttendance | 考勤 — **设计完全重做**（日历视图 + popover）|
| sku | pageHistory | 货号历史，3 sub-tab 都对得上 |
| quality | pageDataQuality | 数据质量 — **设计窄化为只看多库位**（见 §3.10）|
| inout | pageInventory | 进销存导入 |
| overseas | pageForeignCustomers | 老外客人 |
| sales | pageSalesAnalytics | 销售分析 |

nav 结构无需改。配色 / 排版 / 信息密度 / 交互模式才是重点变化。

---

## 2. 系统级新功能（跨页）

**A. 必做 / 高价值**

| # | 项 | 说明 | 实施量 |
|---|---|---|---|
| A1 | **暗色主题** | 默认 dark；保留浅色作 paper 备选。CSS 变量 token 直接抄设计 | 1 天，主要改 tokens.css + 各 page CSS |
| A2 | **主题切换 ☀/☾ 按钮** | header 右侧。`body[data-theme]` + 持久化到 localStorage | 0.5 天 |
| A3 | **侧栏折叠 200px ↔ 56px** | hover 折叠态显 tooltip。Alpine store 加 `nav.collapsed` | 0.5 天 |
| A4 | **header (44px) + 子信息带 (28px)** | header: breadcrumb / 搜索框 / 状态 pill / 时钟 / 主题钮 / 区域。子条: SESSION / OPERATOR / STOCKPILE 计数 / UPTIME | 1 天 |
| A5 | **实时时钟** | HH:MM:SS，setInterval 更新 | 10 分钟 |
| A6 | **键盘快捷键** | ⌘1-9 切 nav，⌘K 聚焦搜索，Esc 关弹层。全局 keydown | 0.5 天 |
| A7 | **状态 pill (IDLE/RUNNING/WARN)** | header 右侧。Alpine store 派生。当前已有 badge，但语义和样式都要换 | 0.5 天 |
| A8 | **字体栈：JetBrains Mono / Inter / Space Grotesk** | 自托管或 Google Fonts CSS。3 个 face | 0.5 天 |
| A9 | **背景 32×32 网格（dark 主题）** | `body::before` + radial mask + 可关 | 1 小时 |

**B. 中等价值 / 选做**

| # | 项 | 说明 |
|---|---|---|
| B1 | **⌘K 全局搜索面板** | 货号 / 文件 / 异常 ID 联合搜索，结果分组显示。**需后端新 endpoint**（见 §5）|
| B2 | **强调色切换（4 预设：green/amber/cyan/violet）** | 用户偏好；做了的话 localStorage 持久化 |

**C. 装饰但不落地（建议跳过）**

| 项 | 原因 |
|---|---|
| LATENCY 4ms / UPTIME 142h | 单进程 Flask 没有这些指标，给假数据是骗自己 |
| 副本节点 3/3 / 索引大小 8.4 GB | SQLite 单文件，无意义 |
| SHA-256 校验 / 自动备份 → /archive | 当前不做校验和归档，标语等于谎言 |
| Tweaks 面板（设计时工具） | handoff README 自己说了 prod 移除 |

---

## 3. 各页面变化

### 3.1 标签处理（pageMain → tags）

**最大改动**。当前是「文件管理 / 异常处理 / 文件管理 panel」+ 顶部上传区，散乱。设计有强结构：

| 设计 panel | 当前对应 | 状态 |
|---|---|---|
| **UploadPanel**（drag-drop + 4 角刻线 + 三按钮：开始处理 / 配置规则 / 重放上次） | top-action-bar drop zone | 视觉重做；"配置规则 / 重放上次" 是 **新交互** |
| **PipelinePanel**（5 阶段：PARSE → NORMALIZE → MATCH → AUDIT → COMMIT，进度条 + 当前阶段 shimmer） | 无对应 | **完全新增**。当前后端只发"完成 / 失败"，没分阶段事件 |
| **ExceptionsPanel**（折叠行 + 严重度 dot HIGH/MED/LOW + code + 字段表格 + 建议动作 + 应用建议/手动编辑/查看原行/忽略） | warnPanel | **数据模型扩展**：当前异常没有 severity / code / 字段级 diff / suggested action |
| **FilesPanel**（文件队列 DONE/RUN/QUEUE/FAIL + per-file progress） | 无对应 | **新增**。当前没有"队列"概念 |
| **StockpilePanel**（4 tab：状态 / 初始化 / 月度比对 / 搜索）| 在独立 stockpile blueprint 里 | 把现有 stockpile 功能搬进标签页右栏 panel |
| **ActivityLog**（终端流式日志 [HH:MM:SS][TAG] msg） | 终端抽屉里有类似的 | **整合**：现有终端 log 可复用，移到 inline panel |

**需要的后端工作**（最重）：
- 把 import / scan 流程拆成 5 阶段事件流（PARSE/NORMALIZE/MATCH/AUDIT/COMMIT），每段发一个进度。**SSE（Server-Sent Events）合适**——Flask 原生支持，不需 WebSocket。
- 异常分类扩展：当前 `task_state` 里 anomaly 只有 barcode/location 错。要扩到「字段级 diff + 严重度 + 建议值」。

**取舍建议**：
- A 选项（**激进**）：改后端发 5 阶段进度。3-5 天。
- B 选项（**保守**）：前端展示 5 阶段壳，但只在「开始」「完成」两点切状态，中间 3 段并行假亮。1 天。
- 推荐 **B 起步**——先把 UI 落地，后端事件流留作 PR 5.5（如真有需要再做）。

### 3.2 查重（pageDup → dedupe）

设计里 dedupe 包含 4 类：whitespace / prefix / 重复段 / 空库位（orphan）。**当前这些都在 pageDataQuality 里**。

**关键决策**：
- 拆分成两页（**按设计**）：dedupe 收 4 类清理项，quality 只看 store/warehouse 多维度统计
- OR 保持当前合并（**少改**）

推荐 **拆分**。语义更清晰：dedupe = 数据清洁工作流（要修的），quality = 维度健康监测（只看的）。当前 `pageDup` 是空骨架，刚好填它。

### 3.3 采购（pagePurchase）

视觉重做 + 几个新交互：
- **解析结果表格**带 hover 高亮 + 状态 Pill (MATCH/NEW/CHECK)
- 底部 footer 「SUM · N ROWS · M UNITS」
- 三个 footer button：一键复制 / 一键入库 / 下载全部
- 月份历史条改成下拉 + chip 显示。当前已有但样式要换

工作量：1 天纯样式 + 状态分类逻辑。

### 3.4 考勤（pageAttendance）

**完全重做**。当前是 row-per-day 表格，设计是 **日历月历视图**。

| 新功能 | 说明 |
|---|---|
| 7×6 日历网格 | 每个 cell = 一天，含日期 + 状态 dot + 时段 / 备注 |
| **DayEditor popover** | 单击 cell 弹出，含状态 5 选 / 时段 / 半天 / 备注。**智能定位**（不溢出视口）|
| 多选模式 | Shift/⌘ 或顶部"批量选择"toggle，选中 cells 高亮 |
| 状态-快设按钮 | 选中后顶部条出现 5 个快速设状态按钮 |
| 键盘 1-5 设状态 | 选中 cells 后按数字键 |
| 员工列表（右侧 rail）| 每员工月填写率 progress bar |
| 「填充全月正常」/「节假日导入」action | **节假日导入是新功能** |

工作量大：2-3 天。是这次重构里**单页最重的一个**。

但当前考勤也确实简陋——日历视图对操作员是巨大体验提升。**值得投。**

### 3.5 货号历史（pageHistory → sku）

3 sub-tab 全对得上。视觉与排版重做，几个数据点是新的：

**5a. 货号查询**：
- 销售面 KV 当前 5 个，设计 8 个。**新指标**：日均件数 / 周转速度 / 退货率
  - 日均件数：`total_qty / lifespan_days`，**纯前端可算**
  - 周转速度：库存周转率，需"平均库存量"，当前**无数据基础**——跳过
  - 退货率：当前没有"退货" 事件类型——跳过
- "查看原行" / "复制货号" / "编辑" 按钮——前两个简单，"编辑" 当前页未实现
- HistoryTimeline：**vertical timeline with 类型色 dot**（create/price/grade/sale/purchase/audit）。当前是平铺列表。**需后端 stockpile_changes 增 sale/purchase/audit 类型映射**

**5b. 最近改动**：当前已实现，视觉换皮即可

**5c. 扫描批次**：当前已实现，视觉换皮即可

工作量：1.5 天（主要 timeline 重做 + 视觉）。

### 3.6 数据质量（pageDataQuality → quality）

**窄化**。设计只展示「同维度多库位」+ 4 个 KPI。当前页 6 个 section（multi/flippers/whitespace/unknown/duplicate/empty）里：
- multi → 留在 quality 页
- whitespace / unknown / duplicate / empty → 迁到 dedupe 页（§3.2）
- flippers → 留 quality（监测维度健康）

工作量：0.5 天（只是 section 移位 + 视觉换皮）。

### 3.7 进销存导入（pageInventory → inout）

新功能：
- **采购单 / 销售单 radio**（当前用 dropdown，设计用 radio with dot 风格）
- **DB state 4 个 stat box**（事件总数 / 客户 / 供应商 / SKU）—— 当前有，重排
- **客户类型分布 horizontal bar**（chinese/foreign/mixed/unknown 比例）——**新可视化**
- **最近导入表格**（时间/类型/文件/行数/OK/重复/错误/操作员）—— 当前没有"操作员"列，**新字段**

**注意**：操作员需要登录系统才能记录。当前无 auth。给个写死的 `admin` 占位即可。

工作量：1 天。

### 3.8 老外客人（pageForeignCustomers → overseas）

变动小。新增：
- 5 个 stat box（记录数 / 总欠款 / 已付 / 未付逾期 / 已托运）—— 状态 paid/unpaid/partial/overdue 字段当前**没有**，需要后端加 status 列或派生字段
- 搜索框（客户名 / 税号）—— 当前没有

工作量：0.5 天 + 后端加 status enum（0.5 天）。

### 3.9 销售分析（pageSalesAnalytics → sales）

视觉换皮 + 增强：
- **可点击列头排序**（当前用 dropdown）
- **每行 sparkline 趋势条**（12 周柱状缩略）—— **新增**
- **GradeBadge 颜色编码**（A/B/C/D，当前显示数字）—— 设计实际是按 grade 分 4 档颜色 dot。可以做
- 4 组筛选 chip 风格换

工作量：0.5 天。

### 3.10 「拆 dedupe + 窄 quality」澄清

| 当前 pageDataQuality 里 | 设计去向 | 备注 |
|---|---|---|
| multi_same_kind | 留 quality | 维度健康 |
| flippers | 留 quality | 维度健康 |
| whitespace_anomalies | 迁 dedupe | 清洁工作流 |
| unknown_prefix | 迁 dedupe | 清洁工作流 |
| duplicate_segments | 迁 dedupe | 清洁工作流 |
| empty_locations | 迁 dedupe | 清洁工作流 |

后端 `data_quality_service.py` 函数签名不动，前端只是把渲染分到两个 page。

---

## 4. 工作量估算 + 拆 PR 建议

| PR | 内容 | 估时 |
|---|---|---|
| **PR-FE-1 基础设施** | 暗色主题 token / 字体 / 折叠侧栏 / 主题切换 / header 重做 / 子条 / 实时时钟 / 全局快捷键 | 2-3 天 |
| **PR-FE-2 dedupe 拆分 + quality 窄化** | 把 data_quality 4 类迁 dedupe，quality 只留多库位 | 1 天 |
| **PR-FE-3 sales 视觉换皮 + sparkline** | 列头排序 / chip 重做 / 行内 sparkline | 1 天 |
| **PR-FE-4 sku history 视觉换皮 + timeline 重做** | vertical timeline with 类型 dot / 销售面 KV 加日均件数 | 1.5 天 |
| **PR-FE-5 inventory + overseas 视觉 + 增强** | 客户类型 bar / 最近导入表格 / 老外搜索框 + status | 1.5 天 |
| **PR-FE-6 purchase 视觉换皮** | 解析结果表 + footer + 状态 pill | 1 天 |
| **PR-FE-7 attendance 完全重做（最重）** | 日历视图 / DayEditor popover / 多选 / 键盘快捷键 / 员工 rail / 节假日导入 | 2-3 天 |
| **PR-FE-8 标签页 panel 重组** | UploadPanel / Pipeline 壳 / Exceptions 重做 / FilesPanel / StockpilePanel 整合 / ActivityLog | 3-4 天 |
| **PR-FE-9 收尾 + e2e** | 浏览器手测每页 / 修 bug / e2e smoke 加 4 case（dark theme / sidebar collapse / shortcut / theme toggle） | 1 天 |

**总计 ~14-19 天**。

**推荐顺序**：1 → 2 → 3 → 5 → 4 → 6 → 9 收一次小尾 → 7 → 8。
- 1 是基础所有页都依赖
- 2/3/5/4/6 是视觉换皮，每个 1-1.5 天，连续做累计成就感强
- 9 第一次收尾——能上线一个"统一视觉但功能未变"的版本，提前发现问题
- 7 / 8 是真正的功能重做，留到最后单独做 + 单独测

每个 PR 独立可合可回滚。中间任何一步用户发现"我不喜欢"都可以叫停。

---

## 5. 后端配套（最少）

只在以下场景**必须**改后端：

1. **A8 字体**：自托管 fonts → `static/vendor/fonts/`，可能 30MB，要进 git LFS 或 .gitignore + 上线脚本。**或**用 Google Fonts CSS（局域网部署可能访问不到——需确认）
2. **B1 ⌘K 全局搜索**：新 endpoint `GET /search?q=`，联合查 stockpile / inventory_events / 文件名。中等工作量
3. **PR-FE-7 节假日导入**：新 endpoint 或 CLI 工具拉某个数据源的中国法定节假日
4. **PR-FE-7 当 attendance 用日历视图后**：当前后端按"行"存事件，前端按"格"渲染，数据结构 OK，无后端改动
5. **PR-FE-8 真做 pipeline 进度事件**（A 选项）：Flask SSE endpoint。**B 选项跳过**

---

## 6. 不实施清单（明确）

避免重构变成抄装饰：

- ❌ 副本节点 / 索引大小 / LATENCY / UPTIME 假数据
- ❌ Tweaks 设计面板
- ❌ React / TypeScript / Recharts / TanStack Table（保持现栈）
- ❌ 操作员登录 / session / JWT（认证不在 v2 范围）
- ❌ 周转速度 / 退货率（无数据基础）
- ❌ Pipeline 真 SSE 进度（除非用户明确想要再升 v3）

---

## 7. 风险与决策点

需要用户拍板的：

1. **字体**：JetBrains Mono / Inter / Space Grotesk 是否要 Google Fonts CDN？局域网能否访问？不能就自托管（多 ~30MB）
2. **暗色 vs 浅色默认**：设计默认 dark；当前用户习惯 light filing-cabinet。建议**默认 dark + 头部一键切回 light**
3. **强调色**：设计默认 `#00ff95` 终端绿。批发店景对绿色无特殊禁忌？
4. **考勤日历视图（PR-FE-7）**：需要确认这是真的体验提升还是改革成本大。可以先做截图 mockup 看用户反应
5. **拆 dedupe / quality**：是否同意拆？还是保持现合并

---

## 8. 第一步建议

把 **PR-FE-1 基础设施** 先做了。理由：

- 风险低（只动 CSS / token / 一些跨页 store）
- 一旦 token 切到设计的，所有后续 page 直接受益于同一调色板
- 主题切换钮做完后，用户**马上能看到效果**判断喜不喜欢
- 任何后续 page 改动都基于 PR-FE-1 的 token

如果 PR-FE-1 做完用户觉得整体方向不对，损失只有 2-3 天 + 一个 commit 可回滚。

---

## 维护

- 每个 PR 完成后在本文件末尾打勾 + 写 commit hash
- 各页面具体新功能命中后端的，开 sub-issue 单独跟
- 用户发现"想加 X" / "不想要 Y" → 改这份 plan 而不是默默加塞

---

## 待办：PR-FE-N 预加载策略（用户提出，2026-05-06）

**问题**：标签查重 / 数据质量 / 销售分析 / 老外客人 / 货号历史最近改动 等页打开后默认空，必须按"刷新"才出数据。首次切过去突兀。

**用户倾向**：网站打开就预加载（保留刷新按钮做"强制重拉"语义）。

**实施方案**（不全量，分层 idle）：

1. **立刻**：substrip stockpile 计数（已做 in PR-FE-1）
2. **站启动 500ms idle**：data_quality（重） + sales_analytics（重）
3. **首次进该页时再加载**：老外客人当月 / 货号历史最近改动（依赖用户选择月份/批次）
4. **永远等输入**：货号查询（依赖 barcode）

**架构**：
- `Alpine.store("preload")` 管 idle 任务队列
- 各页 JS 模块导出 `preload()` 函数（`refresh()` 内部复用）
- 站启动后 `requestIdleCallback` 排任务

**估时**：0.5-1 天

**触发时机**：等当前 PR-FE-3..PR-FE-8 走完后，整体看哪些页"突兀感最重"再决定。**当前不做**。

