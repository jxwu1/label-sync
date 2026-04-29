# 阶段 2：前端响应式 (Alpine.js) — 设计文档

**起草日期**：2026-04-29
**对应 roadmap 阶段**：阶段 2 `refactor/alpine`
**前置依赖**：阶段 1 / 阶段 1.5 已完成（无技术依赖，仅排期上避免与多库位改造同期）
**预计 PR**：2 个 (`refactor/alpine-stores`、`refactor/alpine-nav`)

---

## 1. 问题与目标

### 当前痛点

1. **`static/js/index.js:38-47` 的 `switchPage` 硬编码 `pageMap`/`navMap`**
   - 6 个 tab 在两个对象里双向维护，新增/重命名 tab 易漏配（roadmap 决策日志记录的 "history tab 漏配" bug 即此类）
2. **跨页 UI 状态散在 `index.js` 模块作用域**
   - `logs[]` / `selected[]` / `lastLog` / `poll` / 各 drawer 的 `classList.toggle` 状态 — 全部命令式 DOM 操作
3. **`window.xxx` 全局函数挂载**
   - `switchPage` / `rmFile` / `clearLog` / `delMsg` 仅为支持 inline `onclick` 而暴露到全局，污染全局命名空间

### 不在本次目标内（明确边界）

- 各 tab 内部交互 (`purchase.js` / `attendance.js` / `stockpile.js` / `history.js` / `data-quality.js`) 的命令式逻辑
- 引入 npm/Vite bundler
- 引入前端测试框架 (Playwright / Vitest)

### 成功标准

1. `switchPage` 不再有硬编码 pageMap/navMap，新增 tab 仅需在一处配置数组追加一项
2. 全部跨页 UI 状态由 `Alpine.store(...)` 持有，遗留模块直接读写 store（SSOT 模式）
3. `window.switchPage` / `window.rmFile` / `window.clearLog` / `window.delMsg` 全部删除
4. `pytest` 全套通过（当前 233 个 case），手测 verify-checklist 全过
5. 阶段 2 完成后，`refactor/alpine-stores` + `refactor/alpine-nav` 两个 PR 合并到 `main`

---

## 2. 决策摘要（来自 brainstorming）

| # | 决策 | 选项 | 理由概要 |
|---|------|------|---------|
| 1 | 范围 | nav + 跨页 UI 状态 | 不动各 tab 内部，blast radius 受控；roadmap 与 YAGNI 双重约束 |
| 2 | Alpine 引入方式 | 本地静态文件 (`static/vendor/alpinejs/alpine.min.js`) | 局域网/单端部署，CDN 不一定可达 |
| 3 | 迁移顺序 | 先抽屉、再 nav | 抽屉是浮层 (低风险)；nav 改坏会影响所有入口 (高风险) |
| 4 | state 模式 | A — 遗留模块直接调 `Alpine.store(...)` (SSOT) | 一次彻底解决，不留门面间接层；调用面经查只有 `index.js` + `index-warnings.js` |
| 5 | 范围边界 | 见 §3.1 详表 | 拒绝 scope creep，10 项明确不纳入 |
| 6 | Store 粒度 | 7 个细粒度 store | Alpine 设计鼓励 small store；每个 store 的 domain 边界真实 |
| 7 | 验证方式 | D — 手测 + `docs/verify-checklist.md` | Playwright 进 roadmap 后续；不混合 scope |
| 8 | PR 拆分 | 2 个 (stores / nav) | 与 Q3 顺序对齐；中间观察期暴露回归 |
| 9 | nav 配置形状 | B 极简版 — `{ id, label, icon }` | YAGNI，`initFn` 等 hooks 留待阶段 3 真用上 |
| 10 | Alpine 启动时序 | `defer` 加载 + `alpine:init` 事件注册 store | 官方推荐；与本地静态文件方案兼容 |

---

## 3. 架构设计

### 3.1 范围边界（精确）

**纳入**

- `static/js/index.js` 内全部 `term/setBadge/setStatus`、抽屉 `classList.toggle`、`switchPage`、上传/处理流程相关命令式 DOM
- `static/js/index-warnings.js` 删除 `initWarnings({ term })` 注入，改直接调 store
- `templates/index.html` 抽屉容器与 nav 部分改 `x-data` / 数据驱动
- 删除全部因 inline `onclick` 而存在的 `window.xxx` 函数挂载

**不纳入**（YAGNI 清单，登记为后续扩展或潜在风险）

| 项 | 当前状态 | 不纳入原因 | 后续路径 |
|---|---------|-----------|---------|
| `purchase.js:602` 的 page-private `setStatus` | 与全局 `setStatus` 同名但作用域内私有 | 是 page-local 状态，迁了反而拉大耦合面 | 阶段 2 后续 PR 单独迁 purchase 内部 |
| `attendance.js` / `purchase.js` / `index-stockpile.js` 内部命令式 DOM | 共 ~1500 行 | 阶段 2 选项 C 已在 Q1 否定 | 阶段 2 后续 PR 逐 tab 迁移 |
| `setInterval` 轮询 (`/status` 1s、transfer/messages 5s) | 命令式生命周期 | 与状态正交，迁了无收益 | 未来若 SPA 化再改 Alpine `init/destroy` |
| `shared.js:setupDropZone` 拖拽逻辑 | 命令式事件绑定 | 与状态正交 | 不动 |
| nav `initFn` 配置钩子 | 不存在 | YAGNI | 阶段 3 scan-history 真需要时再加 |
| Page 容器全数据驱动 (component 化) | 各 page HTML 在模板里手写 | 各 page 内部结构差太大，强行模板化失控 | 不做 |
| Vitest store 单测 | 不存在 | store 逻辑薄，单测捕不到真 bug | 不做 |
| Playwright e2e | 不存在 | 阶段 2 范围之外 | **写入 roadmap 横切技术债，作为阶段 2 完成后独立 follow-up** |
| Vite + npm bundler | 不存在 | roadmap 横切技术债已登记 | 等真正引入 npm 包 (Tailwind/ECharts) 时一并 |
| 单一全局 store | 不采用 | 模糊 SSOT 边界 | 不做 |

### 3.2 Store 设计（7 个）

文件：`static/js/store.js` (新增，<200 行)

```js
// store.js
document.addEventListener('alpine:init', () => {
  Alpine.store('term', {
    logs: [],
    lastLog: 0,
    push(text, cls = '', src = 'lp') { this.logs.push({ text, cls, src }); },
    clear() { this.logs = []; this.lastLog = 0; },
    setLastLog(n) { this.lastLog = n; },
  });

  Alpine.store('app', {
    badgeType: 'idle',
    badgeText: '空闲',
    statusText: '请先上传文件',
    statusCls: '',
    setBadge(type, text) { this.badgeType = type; this.badgeText = text; },
    setStatus(text, cls = '') { this.statusText = text; this.statusCls = cls; },
  });

  Alpine.store('upload', {
    selected: [],
    add(files) { this.selected.push(...files); },
    remove(i) { this.selected.splice(i, 1); },
    clear() { this.selected = []; },
  });

  Alpine.store('ui', {
    termDrawer: false,
    transferDrawer: false,
    quickMenu: false,
    transferDot: false,
    quickTransferDot: false,
    toggleTerm() { this.termDrawer = !this.termDrawer; },
    toggleTransfer() {
      this.transferDrawer = !this.transferDrawer;
      this.transferDot = false;
      this.quickTransferDot = false;
    },
    toggleQuick() { this.quickMenu = !this.quickMenu; },
    closeAll() { this.termDrawer = false; this.transferDrawer = false; this.quickMenu = false; },
  });

  Alpine.store('messages', {
    list: [],
    setList(items) { this.list = items; },
  });

  Alpine.store('transfer', {
    files: [],
    setFiles(items) { this.files = items; },
  });

  // PR2 nav store —— PR1 阶段不引入此 store
  Alpine.store('nav', {
    current: 'main',
    pages: [
      { id: 'main',         label: '价格标处理', icon: '🏷️' },
      { id: 'dup',          label: '重复检查',   icon: '🔍' },
      { id: 'purchase',     label: '采购',       icon: '📦' },
      { id: 'attendance',   label: '考勤',       icon: '📅' },
      { id: 'history',      label: '货号历史',   icon: '📊' },
      { id: 'data_quality', label: '数据质量',   icon: '🔍' },
    ],
    switch(id) { this.current = id; },
  });
});
```

### 3.3 模板改造（要点）

**抽屉部分（PR1）**

```html
<!-- term drawer -->
<div id="termDrawer" :class="$store.ui.termDrawer ? '' : 'hide'" x-data>
  <button @click="$store.ui.toggleTerm()">×</button>
  <div id="tbod">
    <template x-for="(item, i) in $store.term.logs" :key="i">
      <div :class="`${item.src === 'dc' ? 'log-dc' : 'log-lp'} ${item.cls}`" x-text="item.text"></div>
    </template>
    <span x-show="$store.term.logs.length === 0" class="log-dim">等待操作</span>
  </div>
</div>

<!-- term FAB -->
<button id="termFab" @click="$store.ui.toggleTerm()" x-data>
  <span id="termFabCount" x-text="$store.term.logs.length"></span>
</button>

<!-- transfer drawer & FAB 类似处理 -->
<!-- quickMenu 类似处理 -->
```

**Nav 部分（PR2）**

```html
<nav class="app-nav" x-data>
  <template x-for="p in $store.nav.pages" :key="p.id">
    <div class="app-nav__item"
         :class="$store.nav.current === p.id ? 'active' : ''"
         @click="$store.nav.switch(p.id)">
      <span x-text="p.icon"></span>
      <span x-text="p.label"></span>
    </div>
  </template>
</nav>

<!-- page 容器仍手写，但 active class 由 store 计算 -->
<div class="page" id="pageMain" :class="$store.nav.current === 'main' ? 'active' : ''" x-data>...</div>
<div class="page" id="pageHistory" :class="$store.nav.current === 'history' ? 'active' : ''" x-data>...</div>
<!-- 其余 4 个 page 同模式 -->
```

### 3.4 加载与启动时序

`templates/index.html` `<head>` 末尾：

```html
<script defer src="/static/vendor/alpinejs/alpine.min.js"></script>
<script type="module" src="/static/js/index.js"></script>
```

- `index.js` 顶部 `import './store.js';` —— store.js 内部用 `document.addEventListener('alpine:init', ...)` 注册，时序由 Alpine 的事件保证
- Alpine 版本：v3.14.x 最新稳定版，下载至 `static/vendor/alpinejs/alpine.min.js`

### 3.5 遗留模块的写法变化（A 模式 SSOT）

**`index.js`**

- 删除 `function term(...)` / `function setBadge(...)` / `function setStatus(...)` 三个本地函数
- 全部 25 个调用点改成 `Alpine.store('term').push(...)` / `Alpine.store('app').setBadge(...)` / `Alpine.store('app').setStatus(...)`
- 删除 `let logs = []` / `let lastLog = 0` / `let selected = []` 三个模块变量
- 删除 `function renderLog()` / `function renderFiles()` —— 渲染由 Alpine 反应式接管
- 删除 `window.switchPage` / `window.rmFile` / `window.clearLog` / `window.delMsg`
- `window.xxx` 调用改成模板里 `@click="..."`
- `setupDropZone` 回调内的 `selected.push(...)` 改成 `Alpine.store('upload').add(...)`

**`index-warnings.js`**

- 删除 `let _term`、`export function initWarnings(fns) { _term = fns.term; }`
- 内部所有 `_term(...)` 改成 `Alpine.store('term').push(...)`
- 导出列表只剩 `waitMsg` / `renderReview`

---

## 4. PR 拆分

### PR1: `refactor/alpine-stores`

**范围**

- 新增 `static/vendor/alpinejs/alpine.min.js`
- 新增 `static/js/store.js`（除 nav store 外的 6 个 store；nav store 也写入但暂不被模板使用）
- `templates/index.html` 抽屉/FAB/quickMenu 部分改 `x-data` / store 绑定；nav 部分**不动**（仍走 `switchPage`）
- `static/js/index.js` 删除 `term/setBadge/setStatus/logs/selected/lastLog/renderLog/renderFiles` 与对应 `window.xxx`，调用全切到 store
- `static/js/index-warnings.js` 删除依赖注入，直接调 store

**验证**

- `pytest` 全套通过
- `docs/verify-checklist.md`（PR1 部分）人工跑通

**预计代码增减**：+250 / -180

### PR2: `refactor/alpine-nav`

**范围**

- `templates/index.html` nav 部分改 `<template x-for>` 数据驱动；6 个 page 容器的 `active` class 改 `:class` 计算
- `static/js/index.js` 删除 `function switchPage(...)` 与 `window.switchPage` 挂载
- `static/js/store.js` 的 `nav` store 在 PR1 已注册，本 PR 仅启用消费

**验证**

- `pytest` 全套通过
- `docs/verify-checklist.md`（PR2 部分）人工跑通；重点验证 6 个 tab 切换

**预计代码增减**：+30 / -50

### PR 之间的间隔

PR1 合并后**至少观察 1-2 天**再开 PR2。让 PR1 的回归（如有）暴露在没有 PR2 干扰的环境里，便于定位。

---

## 5. 验证策略（Q7=D）

新增 `docs/verify-checklist.md`（首次创建）。结构：

```markdown
# 前端验证清单

## 通用 (每个 PR 必跑)
- [ ] 页面加载无 console error
- [ ] 6 个 tab 切换正常 (main/dup/purchase/attendance/history/data_quality)

## PR1: refactor/alpine-stores
- [ ] 上传文件 → /run → 终端日志实时显示，badge 正常切换
- [ ] 等待处理 → 继续处理流程
- [ ] 处理失败时 badge 显示"出错"
- [ ] 重置按钮清空所有 UI 状态
- [ ] 复制型号 (去重 / 含重复) 两个按钮
- [ ] 重复检查上传 → 结果显示
- [ ] 终端 FAB 按钮：开关抽屉、计数刷新、脉动动画
- [ ] 互传 FAB 按钮：开关抽屉、上传文件、列表刷新、红点消失
- [ ] 右下角 quickMenu：弹出、点击外部关闭、子按钮触发对应抽屉
- [ ] 消息列表：发送、刷新、删除

## PR2: refactor/alpine-nav
- [ ] 6 个 nav 项点击都能切到对应 page
- [ ] 当前 active 项视觉高亮正确
- [ ] 页面刷新后回到 main tab
- [ ] inline 调用 switchPage('xxx') 不再存在 (grep 验证)
```

每个 PR 在 PR description 里贴 checklist 完成情况。

Playwright e2e 套件作为阶段 2 完成后的独立 follow-up，写入 roadmap 横切技术债。

---

## 6. 风险与回滚

### 已识别风险

1. **Alpine 反应式与现有 ES module 脚本时序冲突**
   - 缓解：`alpine:init` 事件注册 store；`defer` 保证 script 顺序
2. **`x-text` / `x-html` 转义差异导致 XSS 行为变化**
   - 缓解：所有用户输入改 `x-text`（自动转义）；只有信任来源用 `x-html`。当前 `esc(...)` 调用全部由 Alpine 接管
3. **遗留模块直接调 `Alpine.store(...)` 时机过早（Alpine 还未启动）**
   - 缓解：`Alpine.store(...)` 在 `alpine:init` 完成前调用是无效的；`index.js` 顶层逻辑大多由用户事件触发，不会在 Alpine 启动前被调；少数顶层调用（`restore()`、`loadTransferUI()`、`loadMsgsUI()`）改成在 `alpine:init` 之后或包到 `DOMContentLoaded` 内
4. **`window.deleteMessage` 等 inline onclick 删除后漏改 HTML**
   - 缓解：grep 全仓 `onclick="` / `window\.` 确认零残留再合并

### 回滚预案

- PR1 / PR2 单独 revert 都不影响对方
- 极端情况（Alpine 本身有问题）：revert PR1 即恢复纯 vanilla 状态

---

## 7. 后续路线（写入 roadmap）

阶段 2 完成后，按下表追加到 roadmap：

| 项 | 归属 | 触发条件 |
|---|------|---------|
| 各 tab 内部命令式 DOM 迁 Alpine | 阶段 2 子项 | 单 tab 真有可见痛点时单独 PR |
| Playwright e2e 套件 | 横切技术债 | 阶段 2 上线稳定 1-2 周后 |
| Vite + npm bundler | 横切技术债（已登记） | 真正引入第一个 npm 包时 |
| nav `initFn` 钩子 | 阶段 3 子项 | scan-history tab 进入时需要触发数据加载 |
| `purchase.js` page-private state 迁 store | 阶段 2 子项 | purchase 内部出现状态同步痛点时 |

---

## 8. 工作量估算

- PR1 (`refactor/alpine-stores`)：1.5 天
- PR1 间隔观察：1-2 天
- PR2 (`refactor/alpine-nav`)：0.5 天
- 合计：约 3-4 个工作日

---

## 9. 决策日志（brainstorming 会话）

按 Q1-Q10 顺序记录，详见 §2 决策摘要表。这次会话的关键转折：

1. Q4 选 A 而非推荐的 B —— 用户明确表态"一次解决问题"，接受更大改动量换取 SSOT
2. Q9 答完后用户提原则："YAGNI 不做的事情都要写进 roadmap"。本 spec §3.1 不纳入清单 + §7 后续路线即此原则的落地
