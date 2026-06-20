# 货号历史页 Phase 4c（退役旧 SPA 页 + 删旧 recent_changes 蓝图 + 删深链）设计

**状态：** 已批准（2026-06-20，设计终审 APPROVE）。三轮审查处置：第一轮（原子性任务重排 / URL map 反向守护 / scoped grep 排除 docs / 显式暂存防脏工作树 / 下载路径修正 / `gen_ts_types --check`）；第二轮（302 测试改 seed admin session 非失效 LOGIN_DISABLED / Location 用 urlparse 精确断言 + 未登录回跳链 / grep 排除 tests 防守护自命中 / 措辞「唯一新增 302」/「不改 Vue Router」）；第三轮（spec grep 与 plan 对齐去 tests / Ruff I001 import 序 + 测试纳入 ruff / 已登录 vs 未登录 302 语义澄清）。

## 背景与目标

货号历史已逐阶段全量迁到 Vue `/ui/history`（Phase 1 / 2a / 2b / 3 / 4a / 4b / 4b.5）。4b.5 完成信息架构追平后，新 Vue 页与旧 Alpine 页（`/?page=history`）已视觉 parity，**视觉降级障碍已清除**。本期（4c）是货号历史迁移**收官**：退役旧 SPA 货号历史页、删除其专属旧端点蓝图、删除新页里的「查看完整分析（旧版）→」安全阀深链。

**这是以删除为主的退役任务**：零数据逻辑变更、零 schema 变更；**唯一新增 = 旧书签 `/?page=history` 的服务端 302 兼容重定向（A1）**。

## ⚠️ 关键纠正：`/scan_history/*` 全部保留（不可删）

历史 backlog 笔记曾写「4c 删旧 `/scan_history/*`」——**这是错的，本设计推翻它**。代码证据：

- **新 Vue 页** `frontend/src/pages/history/ScanBatchPanel.vue` 用 `/scan_history/batches/<id>/download/{csv,zip}` 和 `/files/<name>` 做二进制下载（4b 决策：列表走新 `/api/history/scan-batches`，下载复用既有 `/scan_history/*`）。
- **仍是旧版的标签处理页** `static/js/index.js`：`loadLastBatch()` 调 `GET /scan_history/batches`（行 386）；「下载结果」`__batchDownload` 调 `/scan_history/batches/<id>/download/zip`（行 272/359）。
- `app/services/scan_history.py` 还被 `app/routes/dashboard.py` 直接调用（行 86/204）。

→ **`app/routes/scan_history.py` 整个蓝图、`app/services/scan_history.py` 服务、及其测试全部保留不动。**

## 范围

### 删除（旧 SPA 货号历史页）

| # | 目标 | 文件 / 位置 |
|---|---|---|
| D1 | 旧页 include | `templates/index.html:197`（`{% include 'partials/_page_history.html' %}`）|
| D2 | 旧页 3 个 script 标签 | `templates/index.html:217`（history.js）、`:220`（index-recent-changes.js）、`:221`（index-scan-history.js）|
| D3 | 旧页模板文件 | `templates/partials/_page_history.html` |
| D4 | 旧页 JS 文件 | `static/js/history.js` |
| D5 | 旧「最近改动」子面板 JS | `static/js/index-recent-changes.js` |
| D6 | 旧「扫描批次」子面板 JS | `static/js/index-scan-history.js` |
| D7 | 旧 SPA 侧栏 nav 条目 | `static/js/store.js:164`（`{ id: "history", ... }`）|

### 删除（旧 recent_changes 蓝图——纯旧页专属）

| # | 目标 | 文件 / 位置 |
|---|---|---|
| D8 | 旧 HTTP 蓝图文件 | `app/routes/recent_changes.py`（`/recent_changes/imports`、`/<id>/summary`、`/<id>/changes`）|
| D9 | 蓝图注册 | `app/routes/__init__.py:26`（import）+ `:40`（`register_blueprint`）|
| D10 | 旧端点路由测试 | `tests/test_recent_changes_routes.py`（仅测旧 HTTP 路由）|

**保留** `app/services/recent_changes.py`：新 `/api/history/recent-changes/*`（`app/routes/history.py:85-132`）复用它。其 service 测试（`test_recent_changes_service.py` / `test_recent_changes_detail_service.py` / `test_recent_changes_perf.py`）保留。

### 删除（新 Vue 页深链安全阀）

| # | 目标 | 文件 / 位置 |
|---|---|---|
| D11 | 深链 `<a href="/?page=history">` | `frontend/src/pages/history/HistoryPage.vue:145-146` |
| D12 | 副标题去「（完整分析见旧版）」 | `HistoryPage.vue:143` → `subtitle="核心查询 · 完整分析 · 批次记录"` |

### 新增（旧书签兼容——服务端 302）

| # | 目标 | 文件 / 位置 |
|---|---|---|
| A1 | `/` 路由检测 `page=history` → 服务端 302 跳 `/ui/history` | `app/routes/pages_tasks.py:37-43` `index()`（删旧页前先就位，旧书签/登录回跳无闪屏可靠落 Vue 页）|

**为何服务端 302 而非 store.js 客户端跳转**：服务端重定向无闪屏、不等 JS、对未登录→登录回跳链路也可靠（用户决策，2026-06-20）。仅特判 `page=history`，其余 `page=*` 仍交客户端 SPA。

### 新增（货号下钻深链——最终审查发现的回归补救）

最终全分支审查发现：删 `static/js/history.js` 后，`static/js/restock.js`（**补货决策页，live nav**）的货号列下钻 `window.historySearch(bc)` 永远 undefined → 静默 no-op（`sales-analytics.js` 同款但该页已退出 nav，dead code）。这是 spec 初版依赖审计的盲区（只查了 `href="/?page=history"` 锚点，漏了命令式 `switch("history") + window.historySearch()` 路径）。决策（用户 2026-06-20）= 给 Vue 页加 `?q=` 深链并自动搜索，再把下钻重指向。

| # | 目标 | 文件 / 位置 |
|---|---|---|
| A2 | 302 透传 `q`：`/?page=history&q=<bc>` → `/ui/history?q=<urlencoded bc>` | `app/routes/pages_tasks.py` index()（用 `urllib.parse.quote(q, safe="")`）|
| B1 | Vue 页 `?q=` 深链自动搜索 + 空 q 复位 | `HistoryPage.vue`：`useRoute()` + `watch(() => route.query.q, …, { immediate: true })`（非 onMounted——同页换货号 / 前进后退也要更新）→ **非空** trim 后切 search tab + `q.value=…` + `runSearch(…)`；**空/缺省 → `doReset()`**（清输入 + reset 四 store + 经各 store reset 的代际 id 作废在途请求）——否则从 `?q=A` 点侧栏「货号历史」回到无 q 时，输入框与 A 的结果会残留 |
| B2 | 补货页下钻重指向 | `static/js/restock.js`（`.rs-bc-link` handler）→ `location.href = "/ui/history?q=" + encodeURIComponent(bc)`，删 `window.historySearch` 死块 |
| B3 | 旧分析页下钻同步清理（dead but 一致性） | `static/js/sales-analytics.js` 同款重指向 / 删死块 |

**watch 而非 onMounted**：同页内换货号（route.query.q 变）、浏览器前进/后退都要触发搜索；`immediate: true` 覆盖首次进入。A→B 快切由 `runSearch`/`store.load` 既有 HC-B7 staleness 守卫兜底（fresh bool）。

### 测试反转（守护方向调头）

| # | 目标 | 文件 |
|---|---|---|
| T1 | 旧页「必须保留」守护 → 改「必须已删」守护 | `tests/test_history_legacy_preserved.py`（断言 store.js 无 history 条目、`_page_history.html`/`history.js`/index-recent-changes.js/index-scan-history.js 均不存在、index.html 不再 include/script 旧页）→ 重命名 `test_history_legacy_retired.py`|
| T2 | 新页深链测试反转 | `frontend/src/pages/history/HistoryPage.test.ts:92-99`（现断言 `a.history__legacy-link` 存在且 href=`/?page=history`）→ 改断言该链接**不存在**|

## 保留（明确不动，防误删）

- `/scan_history/*` 全部端点 + service + 测试（见上「关键纠正」）。
- `app/services/recent_changes.py` + 其 service 测试（新 `/api/history/recent-changes` 复用）。
- `/api/history/*` 全部新端点（新 Vue 页数据源）。
- `frontend/src/pages/history/` 下除 HistoryPage.vue 深链外的一切（四 store、ScanBatchPanel、TimelineChart、RecentChanges 组件等）。
- `frontend/src/shell/nav-items.ts`：`history` 已是 `routeName`（指向 Vue），不动。
- `templates/index.html` 其余 legacy 页 include / script 不动。
- `static/css/components.css` 旧 `hist-v2` / `hist-tml` 等孤立 CSS 规则：**本期不删**（与其他旧页共用同一文件，孤立规则无害；删除收益低、动共用文件有回归风险）。列为后续可选清理。

## 边界 / 风险

- **旧书签 `/?page=history`**：删 store.js history 条目后旧 SPA 不再有该页（否则静默落 dashboard 默认页）。由 A1 服务端 302 兜底 → 旧书签可靠落 `/ui/history`。无其他入站链接指向 `/?page=history`（唯一一处即被删的深链 D11）。
- **`index.js`（标签处理页）不触碰 history 页 DOM**——已核实它只调 `/scan_history/*` 端点（共用服务），删 history.js / 旧 partial 不影响它。
- **删 recent_changes 蓝图前确认无第三方调用**：grep **限定非测试源** `git grep -n "/recent_changes" -- app static templates frontend`（不含 docs：历史引用含本 spec/plan；不含 tests：新守护测试 `test_history_legacy_retired.py` 含 `"/recent_changes"` 字面量会自命中）。HTTP 调用方仅 `static/js/index-recent-changes.js`——**故任务顺序：先删旧 SPA 页（含该调用方），再删蓝图**，避免出现「页在调、端点已 404」的中间提交（原子性）。`app/routes/history.py` 的新端点是 `/api/history/recent-changes/*`（连字符，独立 url_prefix，独立 import service），不经旧蓝图。
- **删除 `test_recent_changes_routes.py` 前**已确认（审查核实）它只测旧 `/recent_changes` HTTP 层薄包装（参数解析/错误），不含 service 断言（service 断言归 `test_recent_changes_service.py` 等）。**且删除前先补「反向契约」行为测试**：用 `create_app(seed_auth=False, prewarm=False)` 检 `app.url_map`——`/recent_changes/*` 规则**不在**、`/api/history/recent-changes/*` 与 `/scan_history/*` 规则**仍在**。仅断言文件/ import 不存在无法发现「从别处重新注册」。

## 验证（合并前全绿）

- 后端：`pytest tests/`（sqlite）+ `./test.ps1`（本地 PG + xdist）全绿；删端点后无残留 import 错误。
- 前端：`cd frontend && npm run test:unit`（jsdom）全绿 + `npx vue-tsc --noEmit` typecheck + `npm run build`。
- `python tools/gen_ts_types.py --check` —— 本期**不增删 schema**，退出码 0（无漂移）。
- `ruff check` / `ruff format --check` clean。
- **行为契约测试**：**已登录**请求 `/?page=history` 直接 302 → Location path `/ui/history`；**未登录**请求先被登录闸 302 到 `/login?next=…`（`next` 保留 `page=history`），登录后重放原 URL 再 302 到 `/ui/history`（完整回跳链）。`app.url_map` 无 `/recent_changes/*`、有 `/api/history/recent-changes/*` 与 `/scan_history/*`。
- **下钻深链测试**：①302 透传——`/?page=history&q=<bc>` → Location path `/ui/history` 且 query `q` == `<bc>`（含需编码的 q，如带空格/特殊字符，验证 urlencode 正确）；②Vue 页（用 **reactive route fixture**，覆盖运行时 query 变化而非仅首次挂载）——`?q=` 首次进入自动搜索；**A→B 快切**（route.query.q 连续变）走 staleness 守卫不串台；**A→空**（route.query.q 变为空，如点侧栏回到无 q）清空输入 + reset 不残留。
- **浏览器人工验收**：`./dev.ps1 -Frontend` 起本地栈，`/ui/history` 命中态——确认深链已消失、页面功能完整（查询 / 概况-深度 / 5 折叠卡 / 批次记录两子-tab 含扫描批次下载）；访问 `/?page=history` 被 302 跳到 `/ui/history`；标签处理页（`/?page=main`）「下载结果」仍可用（`/scan_history/batches/<id>/download/zip` 未受影响）。

## 不做（YAGNI）

- 不删 `/scan_history/*`（代码强制保留）。
- 不删 `recent_changes` / `scan_history` service 层。
- 不清 `components.css` 孤立 CSS（另列可选）。
- 不动任何仍是 legacy 的其他 SPA 页（dashboard / main / dup / purchase / …）。
- **不改 Vue Router / nav-items.ts / App Shell**（A1 仅改 Flask `/` 路由 `pages_tasks.index`，与 Vue 路由无关）。
