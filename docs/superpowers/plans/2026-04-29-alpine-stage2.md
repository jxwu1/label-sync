# 阶段 2：前端响应式 (Alpine.js) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把跨页 UI 状态从 `index.js` 模块作用域迁到 7 个 `Alpine.store(...)`（SSOT 模式），同时把 nav 改成数据驱动以根治 `switchPage` 硬编码 pageMap/navMap 那个 bug 类。

**Architecture:** 引入 Alpine v3.14 本地静态文件；新建 `static/js/store.js` 注册 7 个 store（term/app/upload/ui/messages/transfer/nav）；遗留模块直接调 `Alpine.store(...)`，不留门面。拆 2 个 PR：`refactor/alpine-stores`（PR1，6 个非 nav store + 抽屉）→ 观察 1-2 天 → `refactor/alpine-nav`（PR2，nav 数据驱动）。

**Tech Stack:** Alpine.js v3.14（本地静态文件，无 npm/Vite）、Flask Jinja2 模板、原生 ES module。验证：pytest 全套 + `docs/verify-checklist.md` 手测。

**Spec:** `docs/superpowers/specs/2026-04-29-alpine-stage2-design.md`

---

## File Structure

**新增**
- `static/vendor/alpinejs/alpine.min.js` — Alpine v3.14.x UMD 文件（下载，零编译）
- `static/js/store.js` — 7 个 store 注册，包在 `alpine:init` 事件回调里
- `docs/verify-checklist.md` — 前端验证清单（PR1/PR2 共用）

**修改**
- `templates/index.html` — 抽屉/FAB/终端 改 `x-data` 绑定（PR1）；nav 改 `<template x-for>`（PR2）；6 个 page 容器 active class 改 `:class`（PR2）
- `static/js/index.js` — 删除 `term/setBadge/setStatus/logs/selected/lastLog/renderLog/renderFiles`，全部改调 store；删 `window.rmFile/clearLog/delMsg`（PR1）；删 `switchPage` 函数和 `window.switchPage`（PR2）；顶部 import store.js
- `static/js/index-warnings.js` — 删除 `initWarnings({term})` 注入，直接调 `Alpine.store('term').push(...)`

**不动**（YAGNI 边界，参见 spec §3.1）
- `static/js/purchase.js` / `attendance.js` / `index-stockpile.js` / `history.js` / `data-quality.js` / `index-recent-changes.js` / `index-dup.js` / `transfer.js` / `messaging.js` / `shared.js`

---

## PR1: `refactor/alpine-stores`

### Task 1: Bootstrap Alpine 与 verify-checklist 框架

**Files:**
- Create: `static/vendor/alpinejs/alpine.min.js`（下载）
- Create: `docs/verify-checklist.md`
- Modify: `templates/index.html`（`<head>` 末尾加 script）

- [ ] **Step 1: 创建分支**

```bash
git checkout main
git pull
git checkout -b refactor/alpine-stores
```

- [ ] **Step 2: 下载 Alpine v3.14 本地静态文件**

```bash
mkdir -p static/vendor/alpinejs
curl -L -o static/vendor/alpinejs/alpine.min.js https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js
```

期望：文件大小约 45KB；用 `head -1 static/vendor/alpinejs/alpine.min.js` 应看到 `(()=>{...` 之类压缩 JS 起始。

- [ ] **Step 3: 在 `templates/index.html` `</head>` 前加 script 标签**

修改 `templates/index.html` 第 19-20 行（`</head>` 前）：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/widgets/quickmenu.css') }}">
<script defer src="{{ url_for('static', filename='vendor/alpinejs/alpine.min.js') }}"></script>
</head>
```

- [ ] **Step 4: 创建 `docs/verify-checklist.md`**

```markdown
# 前端验证清单

> 阶段 2 (Alpine) PR1/PR2 手测清单。每个 PR 在 description 里贴完成状态。

## 通用 (每个 PR 必跑)
- [ ] 浏览器加载首页无 console error
- [ ] 6 个 nav 都能切到对应 page (main/dup/purchase/attendance/history/data_quality)
- [ ] 货号历史页 2 个二级 tab 切换正常 (查询 / 最近改动)

## PR1: refactor/alpine-stores
- [ ] 拖入 .xlsx / .csv → 文件列表显示 → 点 × 删除一项
- [ ] 上传 → /run → 终端日志实时刷新，badge idle→running
- [ ] 处理中 #status 显示 spinner + 文案
- [ ] 完成后 badge=done，下载/复制按钮显示
- [ ] 点"重置"清空全部 UI，badge 回 idle
- [ ] 复制所有型号 (去重) / (含重复) 两个按钮
- [ ] 重复检查 tab 上传 → 结果显示
- [ ] 终端 FAB 计数 = 日志条数；点击开关抽屉
- [ ] 终端"清空"按钮可用
- [ ] 互传 FAB 点击 → 抽屉打开 → 红点消失
- [ ] 互传抽屉拖入文件 → 列表刷新；下载链接可点
- [ ] 文字互传：输入 → Ctrl+Enter 发送 → 列表显示 → 删除
- [ ] 右下角 quickMenu：点击展开 → 子按钮触发对应抽屉 → 点外部关闭

## PR2: refactor/alpine-nav
- [ ] 6 个 nav 项点击都能切到对应 page，active class 正确
- [ ] 页面刷新后默认在 main tab
- [ ] grep 验证 `static/js/` 下无 `window.switchPage` 残留
- [ ] grep 验证 `templates/` 下无 `onclick="switchPage` 残留
```

- [ ] **Step 5: 启动 Flask + 浏览器手测 Alpine 加载**

```bash
python app.py  # 或本仓库实际启动方式
```

打开浏览器 → 控制台输入 `Alpine.version` → 期望返回 `"3.14.9"` 或类似版本号。

- [ ] **Step 6: 运行 pytest 确认零回归**

```bash
python -m pytest -q
```

期望：253 passed。

- [ ] **Step 7: Commit**

```bash
git add static/vendor/alpinejs/ templates/index.html docs/verify-checklist.md
git commit -m "feat(alpine): bootstrap Alpine v3.14 本地静态文件 + verify checklist"
```

---

### Task 2: 注册 7 个 store（含 nav store，PR2 才启用）

**Files:**
- Create: `static/js/store.js`
- Modify: `static/js/index.js`（顶部加 import）

- [ ] **Step 1: 创建 `static/js/store.js`，注册全部 7 个 store**

完整文件内容：

```js
// Alpine stores — 阶段 2 SSOT
// 所有跨页 UI 状态都集中在这里。遗留模块直接调 Alpine.store('xxx').yyy(...)
"use strict";

document.addEventListener("alpine:init", () => {
  // 终端日志
  Alpine.store("term", {
    logs: [],
    lastLog: 0,
    push(text, cls = "", src = "lp") {
      this.logs.push({ text, cls, src });
    },
    clear() {
      this.logs = [];
      this.lastLog = 0;
    },
    setLastLog(n) {
      this.lastLog = n;
    },
  });

  // 全局 badge / status
  Alpine.store("app", {
    badgeType: "idle",
    badgeText: "空闲",
    statusText: "请先上传文件",
    statusCls: "",
    setBadge(type, text) {
      this.badgeType = type;
      this.badgeText = text;
    },
    setStatus(text, cls = "") {
      this.statusText = text;
      this.statusCls = cls;
    },
  });

  // 待上传文件
  Alpine.store("upload", {
    selected: [],
    add(files) {
      this.selected.push(...files);
    },
    remove(i) {
      this.selected.splice(i, 1);
    },
    clear() {
      this.selected = [];
    },
  });

  // 浮层 / 红点
  Alpine.store("ui", {
    termDrawer: false,
    transferDrawer: false,
    quickMenu: false,
    transferDot: false,
    quickTransferDot: false,
    toggleTerm() {
      this.termDrawer = !this.termDrawer;
    },
    toggleTransfer() {
      this.transferDrawer = !this.transferDrawer;
      this.transferDot = false;
      this.quickTransferDot = false;
    },
    toggleQuick() {
      this.quickMenu = !this.quickMenu;
    },
    closeQuick() {
      this.quickMenu = false;
    },
    closeTerm() {
      this.termDrawer = false;
    },
    closeTransfer() {
      this.transferDrawer = false;
    },
  });

  // 跨端消息
  Alpine.store("messages", {
    list: [],
    setList(items) {
      this.list = items;
    },
  });

  // 互传文件列表
  Alpine.store("transfer", {
    files: [],
    setFiles(items) {
      this.files = items;
    },
  });

  // Nav (PR2 才会被模板消费；PR1 阶段提前注册让形状稳定)
  Alpine.store("nav", {
    current: "main",
    pages: [
      { id: "main",         label: "标签",     icon: "📋" },
      { id: "dup",          label: "查重",     icon: "🔍" },
      { id: "purchase",     label: "采购",     icon: "📦" },
      { id: "attendance",   label: "考勤",     icon: "🕐" },
      { id: "history",      label: "货号历史", icon: "📜" },
      { id: "data_quality", label: "数据质量", icon: "🔍" },
    ],
    switch(id) {
      this.current = id;
    },
  });
});
```

- [ ] **Step 2: 在 `static/js/index.js` 第 1 行 import store.js**

修改 `static/js/index.js` 第 1-5 行（顶部）：

```js
import "./store.js";
import { esc, logClass, copyToClip, setupDropZone } from "./shared.js";
import { uploadTransferFiles, loadTransferFiles } from "./transfer.js";
import { sendTextMessage, loadMessages, deleteMessage } from "./messaging.js";
import { initWarnings, waitMsg, renderReview } from "./index-warnings.js";
import { initStockpile } from "./index-stockpile.js";
```

- [ ] **Step 3: 浏览器验证 store 注册成功**

刷新页面 → 控制台输入：

```js
Alpine.store('term').push('test')
Alpine.store('term').logs
```

期望：第二行返回 `[{text:'test', cls:'', src:'lp'}]`。

```js
Alpine.store('nav').pages.length
```

期望：`6`。

- [ ] **Step 4: pytest sanity**

```bash
python -m pytest -q
```

期望：253 passed（store.js 不影响后端）。

- [ ] **Step 5: Commit**

```bash
git add static/js/store.js static/js/index.js
git commit -m "feat(alpine): 注册 7 个 store (term/app/upload/ui/messages/transfer/nav)"
```

---

### Task 3: term store 接管终端日志

**Files:**
- Modify: `static/js/index.js`（删 `term/logs/lastLog/renderLog/clearLog`，调用全切到 store）
- Modify: `static/js/index-warnings.js`（删 initWarnings 注入）
- Modify: `templates/index.html` 第 264-279 行（终端 FAB + 抽屉）

- [ ] **Step 1: 改 `templates/index.html` 终端 FAB 与抽屉**

替换第 264-279 行：

```html
<button class="term-fab" id="termFab" type="button" x-data @click="$store.ui.toggleTerm()">
  <span>▸ 终端日志</span>
  <span class="term-fab__count" id="termFabCount" x-text="$store.term.logs.length">0</span>
</button>

<div class="terminal-log" id="termDrawer" x-data :class="$store.ui.termDrawer ? '' : 'hide'">
  <div class="terminal-log__head">
    <span class="terminal-log__dot"></span>
    <span class="terminal-log__title">终端日志</span>
    <button class="terminal-log__clear" type="button" @click="$store.term.clear()">清空</button>
    <button class="terminal-log__close" id="termClose" type="button" @click="$store.ui.closeTerm()">收起</button>
  </div>
  <div class="terminal-log__body" id="tbod">
    <template x-for="(item, i) in $store.term.logs" :key="i">
      <div :class="`${item.src === 'dc' ? 'log-dc' : 'log-lp'} ${item.cls}`" x-text="item.text"></div>
    </template>
    <span class="log-dim" x-show="$store.term.logs.length === 0">等待操作</span>
  </div>
</div>
```

- [ ] **Step 2: 改 `static/js/index.js` 第 8-30 行（删旧 term/log 实现）**

替换第 8-30 行：

```js
const $ = (selector) => document.querySelector(selector);
let selected = [], poll = null;
initWarnings();
```

注：删除：`logs`、`lastLog`、`setBadge`/`setStatus` 函数（下一 task 处理）、`function term(...)`、`renderLog()`、`clearLog` + `window.clearLog`。`initWarnings()` 不再传参（下一步在 warnings 里改）。

- [ ] **Step 3: index.js 内全部 `term(...)` 调用改成 `Alpine.store('term').push(...)`**

精确替换列表（第 67、61、59、62、75、95、98、100、105、108、110、113、123、134、146、150、151、153、154 行的 `term(...)`）：

```bash
# 用 sed 批量替换的等价 Edit 操作，每处单独 Edit。示例：
# 第 12 行已删除 term 函数定义
# 第 67 行: term(data.log[i], logClass(data.log[i]));
#       → Alpine.store('term').push(data.log[i], logClass(data.log[i]));
```

精确做法：在 `static/js/index.js` 内对每个 `term(` 调用做 Edit，将 `term(` 替换成 `Alpine.store('term').push(` 并保留参数。

同时把第 67 行附近 `lastLog` 引用改成 `Alpine.store('term').lastLog` / `Alpine.store('term').setLastLog(...)`：

第 65-69 行（`function handleStatus(data)` 内）：

```js
function handleStatus(data) {
  if (data.log && data.log.length > Alpine.store('term').lastLog) {
    const last = Alpine.store('term').lastLog;
    for (let i = last; i < data.log.length; i++) Alpine.store('term').push(data.log[i], logClass(data.log[i]));
    Alpine.store('term').setLastLog(data.log.length);
  }
```

第 122-123 行（`reset` 处理器内）：

```js
clearInterval(poll);
Alpine.store('term').setLastLog(0);
Alpine.store('term').push("已清空界面，准备下一批", "log-dim");
```

第 187-192 行（`restore` 函数内）：

```js
async function restore() {
  try {
    const data = await (await fetch("/status")).json();
    if (data.log && data.log.length) {
      const term = Alpine.store('term');
      term.clear();
      data.log.forEach((t) => term.push(t, logClass(t)));
      term.setLastLog(data.log.length);
    }
    handleStatus(data); if (data.running) startPoll();
  } catch (e) { console.error("Status restore failed:", e); }
}
```

- [ ] **Step 4: 改 `static/js/index-warnings.js`，删依赖注入**

读当前文件确认结构（应该 < 30 行）：

```bash
cat static/js/index-warnings.js
```

把文件改成：

```js
// 删除这行：let _term = () => {};
// 删除这行：export function initWarnings(fns) { _term = fns.term; }
// 把所有 _term(...) 改成 Alpine.store('term').push(...)
// 改后：导出 waitMsg, renderReview, initWarnings (initWarnings 改成空 noop 保持调用方签名)
```

具体编辑：先 Read 该文件全文，再分步 Edit：

1. 删除模块顶部 `let _term = ...` 行
2. 把 `export function initWarnings(fns) { _term = fns.term; }` 改成 `export function initWarnings() {}`（空 noop，调用方仍能 import 调用）
3. 把所有 `_term(...)` 改成 `Alpine.store('term').push(...)`

- [ ] **Step 5: 浏览器手测**

```bash
python app.py
```

- 打开首页 → 终端 FAB 计数显示 0
- 点击终端 FAB → 抽屉打开
- 点击"清空"→ 抽屉显示"等待操作"
- 上传一个文件 → 期望抽屉里出现"上传完成：xxx"
- 控制台 `Alpine.store('term').logs.length` 应该 ≥ 1

- [ ] **Step 6: pytest sanity**

```bash
python -m pytest -q
```

期望：253 passed。

- [ ] **Step 7: Commit**

```bash
git add static/js/index.js static/js/index-warnings.js templates/index.html
git commit -m "feat(alpine): term store 接管终端日志，删除 initWarnings 依赖注入"
```

---

### Task 4: app store 接管 badge / status

**Files:**
- Modify: `templates/index.html`（badge 节点 + #status 节点）
- Modify: `static/js/index.js`（删 setBadge/setStatus 函数，调用切 store）

- [ ] **Step 1: 改 `templates/index.html` badge（第 43 行）**

```html
<span class="badge" id="badge" x-data
      :class="`badge-${$store.app.badgeType}`"
      x-text="$store.app.badgeText"
      style="margin-bottom: 14px; align-self: flex-end;">空闲</span>
```

- [ ] **Step 2: 找到 `#status` 节点并改为 store 绑定**

```bash
grep -n 'id="status"' templates/index.html
```

把找到的节点改成（保持原有 class/属性）：

```html
<div class="status" id="status" x-data
     :class="$store.app.statusCls ? `status ${$store.app.statusCls}` : 'status'"
     x-html="$store.app.statusText">请先上传文件</div>
```

注：用 `x-html` 而非 `x-text` 是因为现有代码里有 `<span class="spin"></span>正在...` 这种 HTML 字符串注入。所有 status 内容都来自 index.js，trusted。

- [ ] **Step 3: 改 `static/js/index.js`，删 setBadge/setStatus 函数**

删除第 10、11 行（两个函数定义）。

把所有 `setBadge(...)` 改成 `Alpine.store('app').setBadge(...)`，所有 `setStatus(...)` 改成 `Alpine.store('app').setStatus(...)`。

调用点（按当前行号）：第 55、59、60、62、73、77、79、81、85、95、98、100、105、108、110、122、71（`setBadge('idle', '空闲')`）等。

每处单独 Edit。

- [ ] **Step 4: 浏览器手测**

- 首页加载 → badge 显示"空闲"，class 含 `badge-idle`
- 上传文件 + 点开始处理 → badge 切 "处理中"，class 含 `badge-running`；#status 显示"处理中..."带 spinner
- 处理失败/完成 → badge/status 切对应状态
- 点重置 → badge 回"空闲"

- [ ] **Step 5: pytest sanity**

```bash
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add static/js/index.js templates/index.html
git commit -m "feat(alpine): app store 接管 badge/status"
```

---

### Task 5: upload store 接管文件选择列表

**Files:**
- Modify: `templates/index.html`（`#files` 容器）
- Modify: `static/js/index.js`（删 `selected` / `renderFiles` / `rmFile` / `window.rmFile`）

- [ ] **Step 1: 找 `#files` 容器，改为 x-for**

```bash
grep -n 'id="files"' templates/index.html
```

期望找到：`<div id="files"></div>` 类节点。改为：

```html
<div id="files" x-data>
  <template x-for="(f, i) in $store.upload.selected" :key="i">
    <div class="file">
      <span class="name" x-text="f.name"></span>
      <span class="rm" @click="$store.upload.remove(i)">×</span>
    </div>
  </template>
</div>
```

同时找 `#upload` 按钮，把 disabled 改成 store 计算：

```bash
grep -n 'id="upload"' templates/index.html
```

把它的 `disabled` 属性改成 Alpine `:disabled`：

```html
<button class="btn ..." id="upload" x-data :disabled="$store.upload.selected.length === 0">上传</button>
```

- [ ] **Step 2: 改 `static/js/index.js` — 删 selected / renderFiles / rmFile**

删除第 8 行的 `let selected = []`（与 `poll` 拆开后只剩 `let poll = null;`）。

删除 `function renderFiles()` 和 `function rmFile(i)`、`window.rmFile = rmFile;` 三处。

把 `setupDropZone` 回调改成调 store（第 50 行附近）：

```js
setupDropZone($("#drop"), $("#fileInput"), (files) => {
  Alpine.store('upload').add([...files]);
});
```

把 `$("#upload").onclick = async () => { if (!selected.length) return; ...` 改成读 store：

```js
$("#upload").onclick = async () => {
  const sel = Alpine.store('upload').selected;
  if (!sel.length) return;
  const upload = $("#upload");
  Alpine.store('app').setStatus('<span class="spin"></span>正在上传文件...');
  try {
    const formData = new FormData();
    sel.forEach((f) => formData.append("files", f));
    const data = await (await fetch("/upload", { method: "POST", body: formData })).json();
    if (!data.ok) {
      Alpine.store('app').setStatus("上传失败：" + data.msg, "error");
      Alpine.store('term').push("上传失败：" + data.msg, "log-err");
      return;
    }
    Alpine.store('app').setStatus("上传成功，共 " + data.saved.length + " 个文件", "success");
    Alpine.store('term').push("上传完成：" + data.saved.join(", "), "log-ok");
    $("#run").disabled = false;
  } catch (e) {
    Alpine.store('app').setStatus("上传失败：" + e, "error");
    Alpine.store('term').push("上传失败：" + e, "log-err");
  }
};
```

注：`upload.disabled = false` 调用全部删除——按钮 disabled 由 store 自动计算。

把 `$("#reset").onclick` 里的 `selected = []`、`$("#files").innerHTML = ""`、`$("#fileInput").value = ""`、`$("#upload").disabled = true` 简化为：

```js
$("#reset").onclick = () => {
  Alpine.store('upload').clear();
  $("#fileInput").value = "";
  $("#run").disabled = true;
  // ... 其余按钮显隐保留 ...
};
```

- [ ] **Step 3: 浏览器手测**

- 拖入 1 个文件 → 列表显示
- 拖入第 2 个 → 列表 2 项
- 点 × → 该项消失
- 全部删完 → 上传按钮 disabled
- 上传 → 处理 → 重置 → 列表清空，按钮 disabled

- [ ] **Step 4: pytest sanity**

```bash
python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add static/js/index.js templates/index.html
git commit -m "feat(alpine): upload store 接管 selected[]，删除 renderFiles/rmFile"
```

---

### Task 6: ui store 接管抽屉与红点

**Files:**
- Modify: `templates/index.html`（transfer FAB + drawer + 终端 close 按钮 + quickMenu）
- Modify: `static/js/index.js`（删第 199-231 行所有 onclick 绑定，改成模板里 @click）

- [ ] **Step 1: 改 transfer FAB（第 234-237 行）**

```html
<button class="transfer-fab" id="transferFab" type="button" x-data @click="$store.ui.toggleTransfer()">
  <span>📨 文件互传</span>
  <span class="transfer-fab__dot" id="transferFabDot" x-data :class="$store.ui.transferDot ? 'is-on' : ''"></span>
</button>
```

- [ ] **Step 2: 改 transfer drawer 容器（第 239 行起）**

```html
<aside class="transfer-drawer" id="transferDrawer" x-data :class="$store.ui.transferDrawer ? 'is-open' : ''">
  <div class="transfer-drawer__head">
    <span class="transfer-drawer__title">文件互传</span>
    <button class="transfer-drawer__close" id="transferDrawerClose" type="button" @click="$store.ui.closeTransfer()">关闭</button>
  </div>
  <!-- 其余内部内容保持不变 -->
```

- [ ] **Step 3: 改 quickMenu（第 281 行起）**

读现有结构：

```bash
sed -n '281,310p' templates/index.html
```

替换 quickMenu 的 onclick 为 @click，并把面板可见性绑到 store：

```html
<div class="quickmenu" id="quickMenu" x-data :class="$store.ui.quickMenu ? 'is-open' : ''">
  <button class="quickmenu__toggle" id="quickToggle" type="button" title="工具菜单" aria-label="工具菜单"
          @click.stop="$store.ui.toggleQuick()">≡</button>
  <div class="quickmenu__panel">
    <button class="quickmenu__item" id="quickTransfer" type="button"
            @click="$store.ui.toggleTransfer(); $store.ui.closeQuick()">
      📨 文件互传 <span class="quickmenu__dot" id="quickTransferDot" :class="$store.ui.quickTransferDot ? 'is-on' : ''"></span>
    </button>
    <button class="quickmenu__item" id="quickTerm" type="button"
            @click="$store.ui.toggleTerm(); $store.ui.closeQuick()">
      ▸ 终端 <span class="quickmenu__count" id="quickTermCount" x-text="$store.term.logs.length">0</span>
    </button>
  </div>
</div>
```

注：quickMenu 原结构里如果有跟上面字段名/class 不同的 children，逐字段对照后改。

- [ ] **Step 4: 改 `static/js/index.js`，删第 199-231 行所有抽屉/quickMenu onclick 绑定**

删除整段（约 199-231 行）：
- `$("#termFab")?.addEventListener(...)` 与 `$("#termClose")?.addEventListener(...)`
- `$("#transferFab")?.addEventListener(...)` 与 `$("#transferDrawerClose")?.addEventListener(...)`
- `$("#quickToggle")` / `$("#quickTransfer")` / `$("#quickTerm")` 全部
- `document.addEventListener("click", (e) => { ... 关闭 quickMenu })` 这段

第 199-231 行整段删除后，原 index.js 文件结尾在 `initStockpile();` 行（约第 197 行）。

但点击外部关闭 quickMenu 这段需要保留——改成 Alpine 的 `@click.outside`：

把 quickMenu 容器加上 `@click.outside="$store.ui.closeQuick()"`：

```html
<div class="quickmenu" id="quickMenu" x-data
     :class="$store.ui.quickMenu ? 'is-open' : ''"
     @click.outside="$store.ui.closeQuick()">
```

- [ ] **Step 5: 删除 `window.clearLog`（已经在 Task 3 里把 clearLog 函数删了，但如果有残留挂 window 也清掉）**

```bash
grep -n "window.clearLog" static/js/index.js
```

如果有命中，删掉那行。

- [ ] **Step 6: 浏览器手测**

- 终端 FAB 点击 → 抽屉开 / 再点 → 关
- 终端"收起"按钮 → 抽屉关
- 互传 FAB 点击 → 抽屉开，红点（如有）消失
- 互传"关闭"按钮 → 抽屉关
- 右下 ≡ 按钮点击 → quickMenu 展开
- 点击 quickMenu 外部空白 → 自动关
- quickMenu 子按钮"📨 文件互传" → 互传抽屉开，quickMenu 关
- quickMenu 子按钮"▸ 终端" → 终端抽屉开，quickMenu 关

- [ ] **Step 7: pytest sanity**

```bash
python -m pytest -q
```

- [ ] **Step 8: Commit**

```bash
git add static/js/index.js templates/index.html
git commit -m "feat(alpine): ui store 接管抽屉/quickMenu/红点"
```

---

### Task 7: messages store 接管文字互传消息列表

**Files:**
- Modify: `templates/index.html`（`#msgList`）
- Modify: `static/js/index.js`（删 `loadMsgsUI` 内的 innerHTML 拼接 + `window.delMsg`）

- [ ] **Step 1: 改 `#msgList`（第 261 行）**

```html
<div class="message-list" id="msgList" x-data>
  <template x-for="i in $store.messages.list" :key="i.id">
    <div class="message" :class="i.sender === 'A' ? 'is-self' : ''">
      <div class="message__head">
        <span class="message__source" x-text="i.sender === 'A' ? '我（A）' : 'B 端'"></span>
        <span>
          <span class="message__time" x-text="i.time"></span>
          <button class="message__del" @click="window.__delMsg(i.id)">×</button>
        </span>
      </div>
      <div class="message__body" x-text="i.text"></div>
    </div>
  </template>
  <div class="empty" x-show="$store.messages.list.length === 0">暂无消息</div>
</div>
```

注：`window.__delMsg` 是临时桥（下一步会处理）。也可以用 Alpine `$dispatch` 或直接在 module 暴露闭包，这里用最直白的 `window.__delMsg` 私有命名空间。

- [ ] **Step 2: 改 `static/js/index.js` — `loadMsgsUI` 切 store，`delMsg` 改 `window.__delMsg`**

替换 `loadMsgsUI` 函数（约第 180-183 行）：

```js
async function loadMsgsUI() {
  const m = await loadMessages();
  Alpine.store('messages').setList(m);
}
```

替换 `delMsg` 函数（约第 185 行）：

```js
async function __delMsg(id) {
  await deleteMessage(id);
  loadMsgsUI();
}
window.__delMsg = __delMsg;
```

注：使用 `window.__delMsg` 而非 `window.delMsg` 是为了让"window 命名空间"看起来明显是内部桥（双下划线前缀）。如果以后改 Alpine 组件 method 形式，这层桥也能干净删除。

- [ ] **Step 3: 浏览器手测**

- 文字互传输入框输入消息 → 发送 → 消息列表出现
- 点击消息 × → 该条消息消失
- 列表空时显示"暂无消息"

- [ ] **Step 4: pytest sanity**

```bash
python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add static/js/index.js templates/index.html
git commit -m "feat(alpine): messages store 接管消息列表"
```

---

### Task 8: transfer store 接管互传文件列表

**Files:**
- Modify: `templates/index.html`（`#tList`）
- Modify: `static/js/index.js`（`loadTransferUI` 切 store）

- [ ] **Step 1: 改 `#tList`（第 253 行）**

```html
<div id="tList" x-data>
  <template x-for="i in $store.transfer.files" :key="i.name">
    <div class="transfer-file">
      <span class="transfer-file__name" :title="i.name" x-text="i.name"></span>
      <span class="transfer-file__size" x-text="i.size + 'KB'"></span>
      <a class="transfer-file__dl" :href="`/transfer_download/${encodeURIComponent(i.name)}`">下载</a>
    </div>
  </template>
  <div class="empty" x-show="$store.transfer.files.length === 0">暂无</div>
</div>
```

- [ ] **Step 2: 改 `static/js/index.js` — `loadTransferUI` 切 store**

替换 `loadTransferUI` 函数（约第 159-162 行）：

```js
async function loadTransferUI() {
  const items = await loadTransferFiles();
  Alpine.store('transfer').setFiles(items);
}
```

- [ ] **Step 3: 浏览器手测**

- 互传抽屉打开
- 拖入文件到 t-drop 区 → 列表刷新出现该文件
- 5 秒轮询自动刷新
- 列表空时显示"暂无"
- 下载链接可点

- [ ] **Step 4: pytest sanity**

```bash
python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add static/js/index.js templates/index.html
git commit -m "feat(alpine): transfer store 接管互传文件列表"
```

---

### Task 9: index.js 收尾清理 + PR1 整体验证

**Files:**
- Modify: `static/js/index.js`（兜底审查 + 修文件结构）

- [ ] **Step 1: grep 验证 `window.xxx` 全部清理（仅保留 switchPage，留给 PR2）**

```bash
grep -n "^window\.\|window\.[a-zA-Z_]\+ *=" static/js/index.js
```

期望仅 1 处命中（`window.switchPage` 或 `window.__delMsg`）。`window.__delMsg` 是 Task 7 留的桥可保留；`window.rmFile` / `window.clearLog` / `window.delMsg` 应该都已删除。如有残留，删掉。

- [ ] **Step 2: grep 验证 `setBadge(`/`setStatus(`/`term(` 全切到 store**

```bash
grep -n "^[^/]*[^a-zA-Z_]\(setBadge\|setStatus\|term\)(" static/js/index.js
```

期望：所有命中都是 `Alpine.store('xxx').yyy(...)` 形式。如果有裸 `term(...)` / `setBadge(...)` 调用残留，全部改成 store 形式。

注意：`Alpine.store('term')` 的 `term` 不算调用，是字符串字面量。

- [ ] **Step 3: 检查 `index.js` 顶层结构**

```bash
wc -l static/js/index.js
```

期望：原 231 行减到 ~180-200 行（删了 term/renderLog/renderFiles/抽屉绑定等）。

读完整文件人工巡查一遍：
```bash
cat static/js/index.js
```

确认：
- `import './store.js'` 在第 1 行
- 没有 `let logs = []` / `let lastLog = 0` / `let selected = []`
- `function term/setBadge/setStatus/renderLog/renderFiles/clearLog/rmFile` 全部不存在
- `initWarnings()` 调用无参数（warnings 不再需要 term 注入）

- [ ] **Step 4: 完整运行 verify-checklist.md PR1 段**

启动 Flask，按 `docs/verify-checklist.md` "PR1: refactor/alpine-stores" 段下每个 checkbox 实测。每过一项就打勾。

- [ ] **Step 5: pytest 完整跑**

```bash
python -m pytest -q
```

期望：253 passed。

- [ ] **Step 6: 在 verify-checklist.md PR1 段记录"全部通过"**

修改 `docs/verify-checklist.md`，在 PR1 段末尾加：

```markdown
**PR1 验证结果**：[日期] 全部通过 by [user]
```

- [ ] **Step 7: Commit verify-checklist 更新**

```bash
git add docs/verify-checklist.md
git commit -m "docs(verify): PR1 手测全过"
```

- [ ] **Step 8: Push PR1 分支**

```bash
git push -u origin refactor/alpine-stores
```

- [ ] **Step 9: 等待与观察**

PR1 合并到 main 后，**至少观察 1-2 天**再开 PR2（spec §4 决策）。期间业务/手测照常使用，发现回归立即 revert PR1。

PR1 合并指令（用户决定时机）：

```bash
git checkout main
git pull
git merge --no-ff refactor/alpine-stores
git push origin main
```

---

## PR2: `refactor/alpine-nav`

**前置**：PR1 已合并到 main 且观察期通过。

### Task 10: nav 数据驱动 + page active class store 化

**Files:**
- Modify: `templates/index.html`（nav block + 6 个 page 容器的 class）

- [ ] **Step 1: 切到 main 拉最新，开 PR2 分支**

```bash
git checkout main
git pull
git checkout -b refactor/alpine-nav
```

- [ ] **Step 2: 改 `templates/index.html` 第 23-44 行 nav block**

替换为：

```html
<div class="app-nav" id="nav" x-data>
  <template x-for="p in $store.nav.pages" :key="p.id">
    <div class="app-nav__item"
         :id="'nav' + p.id.charAt(0).toUpperCase() + p.id.slice(1).replace(/_(.)/g, (_, c) => c.toUpperCase())"
         :class="$store.nav.current === p.id ? 'app-nav__item active' : 'app-nav__item'"
         @click="$store.nav.switch(p.id)">
      <span class="app-nav__icon" x-text="p.icon"></span>
      <span x-text="p.label"></span>
    </div>
  </template>
  <span style="flex:1"></span>
  <span class="badge" id="badge" x-data
        :class="`badge-${$store.app.badgeType}`"
        x-text="$store.app.badgeText"
        style="margin-bottom: 14px; align-self: flex-end;">空闲</span>
</div>
```

注：`:id` 的拼接保留 `navMain` / `navDataQuality` 这种 camelCase 命名仅为兼容现有 CSS（如有按 id 选择的样式）。如确认 CSS 仅用 class 选择器，可删 `:id`。

更安全做法：先 grep 确认 CSS：
```bash
grep -rn "#nav\(Main\|Dup\|Purchase\|Attendance\|History\|DataQuality\)" static/css/
```

如果 0 命中，删除 `:id` 行简化模板：

```html
<template x-for="p in $store.nav.pages" :key="p.id">
  <div class="app-nav__item"
       :class="$store.nav.current === p.id ? 'app-nav__item active' : 'app-nav__item'"
       @click="$store.nav.switch(p.id)">
    <span class="app-nav__icon" x-text="p.icon"></span>
    <span x-text="p.label"></span>
  </div>
</template>
```

- [ ] **Step 3: 改 6 个 page 容器的 class，加 `:class` 绑定**

找到所有 `<div class="page" id="page...">`：

```bash
grep -n 'class="page' templates/index.html
```

每个 page 容器形如：
```html
<div class="page active" id="pageMain">  ← 第 47 行
<div class="page" id="pageDup">           ← 第 124 行
<div class="page" id="pagePurchase">      ← 第 130 行
<div class="page" id="pageAttendance">    ← 第 131 行
<div class="page" id="pageHistory">       ← 第 132 行
<div class="page" id="pageDataQuality">   ← 第 155 行
```

全部改成：

```html
<div class="page" id="pageMain"        x-data :class="$store.nav.current === 'main'         ? 'page active' : 'page'">
<div class="page" id="pageDup"         x-data :class="$store.nav.current === 'dup'          ? 'page active' : 'page'">
<div class="page" id="pagePurchase"    x-data :class="$store.nav.current === 'purchase'     ? 'page active' : 'page'">
<div class="page" id="pageAttendance"  x-data :class="$store.nav.current === 'attendance'   ? 'page active' : 'page'">
<div class="page" id="pageHistory"     x-data :class="$store.nav.current === 'history'      ? 'page active' : 'page'">
<div class="page" id="pageDataQuality" x-data :class="$store.nav.current === 'data_quality' ? 'page active' : 'page'">
```

注：写死字符串 `'main'` 等比循环更清晰，因为每个 page 容器内 HTML 结构不同（不能 template 化，spec §3.3 决策）。

- [ ] **Step 4: 浏览器手测**

- 加载首页 → 默认在 main tab，nav 中"标签"项 active
- 点击"查重" → 切到 dup page，"查重"项 active，"标签"项失活
- 顺序点 6 个 nav 项 → 都能切
- 刷新页面 → 回到 main tab（store 不持久化是预期行为）

- [ ] **Step 5: 在浏览器控制台验证 nav store 状态**

```js
Alpine.store('nav').current  // 当前 tab
Alpine.store('nav').switch('history')  // 应该切到货号历史
```

- [ ] **Step 6: pytest sanity**

```bash
python -m pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add templates/index.html
git commit -m "feat(alpine): nav 数据驱动 + page active class 改 store 计算"
```

---

### Task 11: 删除 `switchPage` 函数与 `window.switchPage`

**Files:**
- Modify: `static/js/index.js`

- [ ] **Step 1: 删除 `switchPage` 函数**

```bash
grep -n "switchPage" static/js/index.js
```

期望命中两行：函数定义和 `window.switchPage = switchPage;`。删除整个函数及 window 挂载（约 9 行）。

删除后该处约第 38-47 行整段消失。

- [ ] **Step 2: grep 模板里残留 onclick**

```bash
grep -n 'onclick="switchPage' templates/index.html
```

期望：0 命中（Task 10 已经把 nav 用 @click 替代）。如有命中，本应在 Task 10 改掉，此处补改。

- [ ] **Step 3: grep window.switchPage 全仓清零**

```bash
grep -rn "switchPage" static/ templates/
```

期望：0 命中（除了 store.js 里 `Alpine.store('nav').switch(...)` 这种 `switch` 不算 `switchPage`）。

- [ ] **Step 4: 浏览器手测**

- 控制台输入 `typeof window.switchPage` → 期望 `"undefined"`
- nav 切换照常工作
- 控制台无 error

- [ ] **Step 5: pytest sanity**

```bash
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add static/js/index.js
git commit -m "feat(alpine): 删除 switchPage 函数与 window.switchPage"
```

---

### Task 12: PR2 整体验证 + commit + push

- [ ] **Step 1: 完整运行 verify-checklist.md "PR2: refactor/alpine-nav" 段**

按清单实测每条，打勾。

- [ ] **Step 2: pytest 完整跑**

```bash
python -m pytest -q
```

期望：253 passed。

- [ ] **Step 3: 在 verify-checklist.md PR2 段记录"全部通过"**

```markdown
**PR2 验证结果**：[日期] 全部通过 by [user]
```

- [ ] **Step 4: Commit verify 更新**

```bash
git add docs/verify-checklist.md
git commit -m "docs(verify): PR2 手测全过"
```

- [ ] **Step 5: Push PR2 分支**

```bash
git push -u origin refactor/alpine-nav
```

- [ ] **Step 6: PR2 合并指令（用户决定时机）**

```bash
git checkout main
git pull
git merge --no-ff refactor/alpine-nav
git push origin main
```

- [ ] **Step 7: 更新 roadmap 把阶段 2 打勾**

修改 `docs/superpowers/plans/2026-04-28-roadmap.md`：

把"阶段 2：前端响应式（refactor/alpine）"段下原 6 条 `- [ ]` 都改成 `- [x]`，并在段末加：

```markdown
**实施备忘**（2026-XX-XX 完成）：
1. 拆 2 个 PR：refactor/alpine-stores（6 stores + 抽屉）→ refactor/alpine-nav（nav 数据驱动）
2. Alpine v3.14.9 本地静态文件，零 npm/Vite 引入
3. SSOT 模式：遗留模块直接调 Alpine.store(...)，不留门面
4. spec: docs/superpowers/specs/2026-04-29-alpine-stage2-design.md
5. plan: docs/superpowers/plans/2026-04-29-alpine-stage2.md

**未做（YAGNI 后续登记）**：
- 各 tab 内部命令式 DOM (purchase/attendance/stockpile 等) 迁 Alpine
- nav initFn 钩子（阶段 3 真用上时再加）
- Playwright e2e（阶段 2 完成稳定 1-2 周后单独 PR）
```

- [ ] **Step 8: Commit roadmap**

```bash
git add docs/superpowers/plans/2026-04-28-roadmap.md
git commit -m "docs(roadmap): 阶段 2 完成打勾 + 备忘"
git push origin main
```

---

## 执行顺序总览

```
Task 1  Bootstrap Alpine + checklist
Task 2  store.js 注册 7 个 store
Task 3  term store
Task 4  app store
Task 5  upload store
Task 6  ui store (抽屉/红点)
Task 7  messages store
Task 8  transfer store
Task 9  PR1 收尾验证 + push
─── 观察 1-2 天 ───
Task 10 nav 数据驱动 + page active
Task 11 删 switchPage
Task 12 PR2 收尾验证 + push + roadmap
```

**预计**：PR1 1.5 天 / 观察 1-2 天 / PR2 0.5 天 / 合计 3-4 工作日（与 spec §8 估算一致）。

---

## 失败兜底

- 任何一个 Task 测试不通过：本 task 内部 revert 当前修改、定位原因、再重做该 task；不要跨 task 累积修复
- PR1 合并后观察期发现回归：`git revert <merge-commit>` PR1，分析后重新做
- PR2 失败：单独 revert PR2，PR1 不受影响

## 偏离 spec 时

如执行中发现 spec 决策需要调整，**停下来**，回 spec 改决策再继续；不要在 plan 执行中静默偏离。改决策记录追加到 spec §9 决策日志。
