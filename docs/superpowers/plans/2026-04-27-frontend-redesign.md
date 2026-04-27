# A 端前端重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 A 端前端从"压成 1 行的 CSS + 散落 inline style + 短类名"重构为"原生 CSS 变量 token + 模块化 CSS + 语义类名 + 标签处理主页 T3 重排 + 其他 3 页 T2 换皮"，功能逻辑零改动。

**Architecture:** 不引入构建工具。`static/css/` 拆为 `tokens.css / base.css / components.css / layout.css / page-*.css / widgets/*.css`。HTML 改 `<link>` 列表，类名重命名，inline style 清零。Stockpile 4 子块 → tab 面板，终端日志 / 文件互传 → FAB + 抽屉。purchase / attendance / dup 三页仅 CSS 换皮。

**Tech Stack:** Flask + Jinja2 + 原生 ES Module JS + 原生 CSS（CSS Custom Properties）。

**参考 spec:** `docs/superpowers/specs/2026-04-27-frontend-redesign-design.md`

**全局规则**

- 每完成一个 Task 都要：① 启动 Flask（`python app.py` 或现有启动方式）→ ② 浏览器打开 A 端 → ③ 切到对应受影响页 → ④ 看 console 无报错、看视觉无回退 → ⑤ git commit。
- 视觉重构不强制 TDD（pytest 套件已覆盖后端，前端无单测基础）；本 plan 把"运行 + 浏览器手测 + grep 检查"作为 verify。
- 每次 commit message 前缀：`refactor(frontend):`。
- 任何步骤遇到样式回退或 JS 报错，先 `git diff` 排查，不要继续累加变更。

---

## File Structure

**新建：**
- `static/css/tokens.css` — `:root` CSS 变量（颜色 / 间距 / 圆角 / 字号 / 字体 / 阴影 / 动效）
- `static/css/base.css` — reset、`body`、通用排版
- `static/css/components.css` — `.btn` 体系、`.panel`、`.badge`、`.drop`、`.tabs`、`.form-input`、`.spin` 等
- `static/css/layout.css` — `.app-header / .app-nav / .app-layout / .app-pages / .top-action-bar`
- `static/css/page-main.css` — 标签处理页（T3 重排专属样式）
- `static/css/page-dup.css` — 重复检查页（T2 换皮）
- `static/css/page-purchase.css` — 采购订单页（替换原 `purchase.css`）
- `static/css/page-attendance.css` — 考勤页（替换原 `attendance.css`）
- `static/css/widgets/terminal-log.css` — 终端日志浮动抽屉
- `static/css/widgets/transfer-drawer.css` — 文件互传滑出抽屉
- `static/js/index-stockpile.js` — 从 `index.js` 拆出的 stockpile 模块 + tab 切换

**修改：**
- `templates/index.html` — `<link>` 列表、类名替换、inline style 清零、布局结构 T3 重排
- `static/js/index.js` — 移除 stockpile 代码、加日志/互传 toggle、清 inline style
- `static/js/index-warnings.js` — 清 inline style
- `static/js/transfer.js` — 宿主容器引用调整（仍走 `id`）
- `static/js/messaging.js` — 同上
- `static/js/attendance.js` — 清 inline style
- `static/js/purchase.js` — 清 inline style

**删除（M9）：**
- `static/css/index.css`（旧 1 行版）
- `static/css/purchase.css`（已被 `page-purchase.css` 取代）
- `static/css/attendance.css`（已被 `page-attendance.css` 取代）

---

## Task 1 — M1: 设计 token + base.css 落地

**目标：** 引入 CSS 变量系统，外观与现状一致（取值与旧 `index.css` 等价）。

**Files:**
- Create: `static/css/tokens.css`
- Create: `static/css/base.css`
- Modify: `templates/index.html` (add `<link>`)

- [ ] **Step 1: 写 `static/css/tokens.css`**

```css
:root {
  /* 表面 */
  --c-bg: #0f1117;
  --c-surface: #161a25;
  --c-surface-elev: #1a1d27;
  --c-surface-deep: #13151f;
  --c-border: #232838;
  --c-border-subtle: #1f2433;

  /* 文字 */
  --c-text: #e2e8f0;
  --c-text-muted: #94a3b8;
  --c-text-dim: #64748b;
  --c-text-faint: #4a5568;
  --c-text-mute2: #cbd5e1;

  /* 强调 */
  --c-accent: #4f46e5;
  --c-accent-hover: #4338ca;
  --c-accent-soft: #1e1b4b;
  --c-accent-fg: #818cf8;

  /* 状态 */
  --c-info: #60a5fa;
  --c-info-bg: #1e3a5f;
  --c-success: #4ade80;
  --c-success-bg: #14532d;
  --c-warn: #fbbf24;
  --c-warn-strong: #fb923c;
  --c-warn-bg: #422006;
  --c-warn-bg-strong: #431407;
  --c-danger: #f87171;
  --c-danger-bg: #450a0a;
  --c-danger-border: #7f1d1d;

  /* 代码色 */
  --c-code: #fbbf24;
  --c-loc: #60a5fa;

  /* 间距 */
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px;
  --sp-4: 16px; --sp-5: 20px; --sp-6: 24px;

  /* 圆角 */
  --r-sm: 6px; --r-md: 8px; --r-lg: 10px; --r-xl: 14px; --r-pill: 999px;

  /* 字号 */
  --fs-xs: 10px; --fs-sm: 11px; --fs-md: 12px; --fs-base: 13px; --fs-lg: 15px;

  /* 字体 */
  --ff-sans: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
  --ff-mono: "Cascadia Code", "Consolas", ui-monospace, monospace;

  /* 阴影 */
  --sh-fab: 0 6px 20px rgba(0,0,0,.4);
  --sh-overlay: 0 12px 48px rgba(0,0,0,.75);

  /* 动效 */
  --t-fast: .12s ease;
  --t-base: .2s ease;
}
```

- [ ] **Step 2: 写 `static/css/base.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--ff-sans);
  background: var(--c-bg);
  color: var(--c-text);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--c-border); border-radius: var(--r-sm); }
::-webkit-scrollbar-thumb:hover { background: var(--c-text-faint); }
```

- [ ] **Step 3: 在 `templates/index.html` 的 `<head>` 中，把现有 3 个 `<link>` 之前插入 tokens 与 base**

把第 7-9 行（原 3 个 link）替换为：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/base.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/index.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/purchase.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/attendance.css') }}">
```

- [ ] **Step 4: 验证**

Run: 启动 Flask，浏览器打开 A 端
Expected: 视觉与重构前完全一致；DevTools Console 无报错；DevTools Elements 中 `:root` 可见所有变量。

- [ ] **Step 5: Commit**

```bash
git add static/css/tokens.css static/css/base.css templates/index.html
git commit -m "refactor(frontend): M1 introduce design tokens + base.css"
```

---

## Task 2 — M2: components.css + 类名重命名（按钮体系）

**目标：** 把按钮 / 面板 / 徽章等通用组件抽到 `components.css`，短类名 `.u/.r/.c/.d/.m/.x` → `.btn-secondary/.btn-primary/.btn-warning/.btn-success/.btn-info/.btn-ghost`。视觉与现状一致。

**Files:**
- Create: `static/css/components.css`
- Modify: `templates/index.html`
- Modify: `static/css/index.css`（删除已迁移的规则）

- [ ] **Step 1: 写 `static/css/components.css`（按钮 + 通用部件）**

```css
/* ========== Buttons (主按钮 .btn) ========== */
.btn {
  width: 100%;
  padding: 10px;
  border: none;
  border-radius: var(--r-md);
  font-size: var(--fs-base);
  font-weight: 600;
  cursor: pointer;
  margin-bottom: 7px;
  transition: background var(--t-fast);
  font-family: inherit;
}
.btn:disabled { opacity: .45; cursor: not-allowed; }

.btn-secondary { background: #2d3148; color: #fff; }
.btn-secondary:hover:not(:disabled) { background: #374162; }

.btn-primary { background: var(--c-accent); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--c-accent-hover); }

.btn-warning { background: #c2410c; color: #fff; display: none; }
.btn-warning:hover:not(:disabled) { background: #9a3412; }

.btn-success { background: #059669; color: #fff; display: none; }
.btn-success:hover { background: #047857; }

.btn-info { background: #0e7490; color: #fff; display: none; }
.btn-info:hover:not(:disabled) { background: #0c6578; }

.btn-ghost { background: var(--c-surface-deep); color: var(--c-text-muted); border: 1px solid var(--c-border); display: none; }
.btn-ghost:hover { background: var(--c-border); color: #fff; }

/* ========== Small buttons (.btn-s) ========== */
.btn-s {
  font-size: var(--fs-md);
  padding: 5px 10px;
  border-radius: var(--r-sm);
  cursor: pointer;
  font-family: inherit;
}
.btn-s.is-warn { border: 1px solid var(--c-warn-strong); background: transparent; color: var(--c-warn-strong); }
.btn-s.is-warn:hover { background: var(--c-warn-bg-strong); }
.btn-s.is-danger { border: 1px solid var(--c-danger-border); background: transparent; color: var(--c-danger); }
.btn-s.is-danger:hover { background: var(--c-danger-bg); }
.btn-s.is-ghost { border: 1px solid var(--c-text-faint); background: transparent; color: var(--c-text-muted); }
.btn-s.is-ghost:hover { background: #1e2433; color: #fff; }
.btn-s.is-warn-solid { border: none; background: #c2410c; color: #fff; }
.btn-s.is-warn-solid:hover { background: #9a3412; }
.btn-s.is-success { border: 1px solid #059669; background: transparent; color: var(--c-success); }
.btn-s.is-success:hover { background: var(--c-success-bg); }
.btn-s.is-ghost-strong { border: 1px solid var(--c-border); background: transparent; color: var(--c-text-muted); }
.btn-s.is-ghost-strong:hover { background: var(--c-border); color: #fff; }

/* ========== Mini button (header) ========== */
.btn-mini {
  background: #1e2433;
  border: 1px solid var(--c-border);
  color: var(--c-text-muted);
  border-radius: var(--r-md);
  padding: 6px 10px;
  cursor: pointer;
}
.btn-mini:hover { background: var(--c-border); color: #fff; }
.btn-mini.active { background: var(--c-accent-soft); border-color: var(--c-accent); color: var(--c-accent-fg); }

/* ========== Panel ========== */
.panel {
  background: var(--c-surface-elev);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.panel-hd {
  padding: 11px 14px;
  border-bottom: 1px solid var(--c-border);
  font-size: var(--fs-sm);
  font-weight: 700;
  color: var(--c-text-dim);
  text-transform: uppercase;
}
.panel-bd { padding: 14px; overflow: auto; flex: 1; }

/* ========== Badge ========== */
.badge {
  font-size: var(--fs-md);
  padding: 3px 10px;
  border-radius: var(--r-pill);
  font-weight: 600;
}
.badge-idle { background: var(--c-border); color: var(--c-text-muted); }
.badge-running { background: var(--c-info-bg); color: var(--c-info); }
.badge-waiting { background: var(--c-warn-bg); color: var(--c-warn-strong); }
.badge-done { background: var(--c-success-bg); color: var(--c-success); }
.badge-error { background: var(--c-danger-bg); color: var(--c-danger); }

/* ========== Drop zones ========== */
.drop, .t-drop {
  border: 2px dashed var(--c-border);
  border-radius: var(--r-md);
  text-align: center;
  cursor: pointer;
  transition: var(--t-base);
}
.drop { padding: var(--sp-6); }
.t-drop { padding: var(--sp-3); margin-bottom: var(--sp-2); }
.drop:hover, .drop.drag, .t-drop:hover, .t-drop.drag {
  border-color: var(--c-accent);
  background: #1e1b4b22;
}
.drop input, .t-drop input { display: none; }
.hint { font-size: var(--fs-sm); color: var(--c-text-faint); margin-top: var(--sp-1); }

/* ========== Status / spinner / common bits ========== */
.status { font-size: var(--fs-md); color: var(--c-text-dim); text-align: center; min-height: 18px; }
.status.error { color: var(--c-danger); }
.status.success { color: var(--c-success); }

.spin {
  display: inline-block;
  width: 12px; height: 12px;
  border: 2px solid var(--c-border);
  border-top-color: var(--c-info);
  border-radius: 50%;
  animation: s .7s linear infinite;
  vertical-align: middle;
  margin-right: 5px;
}
@keyframes s { to { transform: rotate(360deg); } }

.empty { color: var(--c-text-faint); font-size: var(--fs-base); text-align: center; padding: 28px 0; }

.row { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.col { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.code { font-weight: 700; color: var(--c-code); word-break: break-all; }
.loc { color: var(--c-loc); }
.sub { color: var(--c-text-muted); font-size: var(--fs-md); }

/* ========== Files list ========== */
.files { margin: 12px 0; }
.file {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  background: var(--c-surface-deep);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  padding: 7px 10px;
  margin-bottom: 6px;
  font-size: var(--fs-md);
}
.file .name { color: var(--c-text-mute2); word-break: break-all; }
.file .rm { cursor: pointer; color: var(--c-text-faint); font-size: 16px; }
.file .rm:hover { color: var(--c-danger); }

/* ========== Form ========== */
.form { display: none; gap: 8px; margin-top: 8px; }
.form input {
  flex: 1;
  padding: 8px 10px;
  background: var(--c-surface-deep);
  border: 1px solid var(--c-warn-strong);
  border-radius: var(--r-sm);
  color: #fff;
  outline: none;
}

/* ========== Tags ========== */
.tag-ok { font-size: var(--fs-md); font-weight: 700; color: var(--c-success); }
.tag-del { font-size: var(--fs-md); font-weight: 700; color: var(--c-danger); }

/* ========== Action button rows (warn list) ========== */
.actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
```

- [ ] **Step 2: 在 `templates/index.html` 的 `<head>` 加 `components.css` link**

紧跟 `base.css` 之后：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/components.css') }}">
```

- [ ] **Step 3: 全局类名重命名（HTML + JS）**

**重命名映射（按 spec §5）：**

| 旧 | 新 |
|---|---|
| `class="btn u"` | `class="btn btn-secondary"` |
| `class="btn r"` | `class="btn btn-primary"` |
| `class="btn c"` | `class="btn btn-warning"` |
| `class="btn d"` | `class="btn btn-success"` |
| `class="btn m"` | `class="btn btn-info"` |
| `class="btn x"` | `class="btn btn-ghost"` |
| `class="btn-s bc"` | `class="btn-s is-warn"` |
| `class="btn-s bd"` | `class="btn-s is-danger"` |
| `class="btn-s bi"` | `class="btn-s is-ghost"` |
| `class="btn-s bf"` | `class="btn-s is-warn-solid"` |
| `class="btn-s bg"` | `class="btn-s is-success"` |
| `class="btn-s cx"` | `class="btn-s is-ghost-strong"` |

执行（Windows bash 用 sed 不可靠，用 Edit 工具逐文件改）：

需要扫描的文件：
- `templates/index.html`
- `static/js/index.js`
- `static/js/index-warnings.js`
- `static/js/purchase.js`
- `static/js/attendance.js`
- `static/js/transfer.js`
- `static/js/messaging.js`

每个文件用 grep 查"`btn u`"等出现位置，逐个替换。注意 className 拼接也要改（如 `"btn r"` 字符串字面量）。

- [ ] **Step 4: 从 `static/css/index.css` 删除已迁移到 components.css 的规则**

旧 `index.css` 里这些段全部删除（保留其他与组件无关的部分到下一个 task 处理）：
- `.btn{...}`、`.u/.r/.c/.d/.m/.x{...}` 及 `:hover` / `:disabled` 变体
- `.btn-s{...}`、`.bc/.bd/.bi/.bf/.bg/.cx{...}` 及 `:hover` 变体
- `.btn-mini{...}` 及变体
- `.panel/.panel-hd/.panel-bd{...}`
- `.badge{...}` + 5 个变体
- `.drop/.t-drop{...}` + 变体
- `.hint`、`.status` + 变体、`.spin`、`@keyframes s`
- `.empty`、`.row`、`.col`、`.code`、`.loc`、`.sub`
- `.files`、`.file{...}`、`.file .name`、`.file .rm`
- `.form`、`.form input`
- `.tag-ok`、`.tag-del`
- `.actions`

剩余的 `.header / .layout / .nav / .main / .pages / .page / .transfer / .term / 等` 留给下个 task。

- [ ] **Step 5: 验证**

Run: 启动 Flask，浏览器跑 A 端 → 标签处理页 → 上传文件 → 点开始处理（不需真处理，看按钮颜色） → 切到查重页 → 文件互传发送一条消息
Expected: 所有按钮（紫主操作 / 灰次要 / 橙继续 / 绿下载 / 青复制 / 透明清空）颜色与旧版一致；`#status` 文字、面板头、文件列表、drop 区视觉一致；console 无报错。

`grep -rn "btn u\|btn r\|btn c\|btn d\|btn m\|btn x\| bc\| bd\| bi\| bf\| bg\| cx" templates/ static/js/` 应只剩误命中（如注释或非类名场景），无类名遗漏。

- [ ] **Step 6: Commit**

```bash
git add static/css/components.css static/css/index.css templates/index.html static/js/
git commit -m "refactor(frontend): M2 extract components + rename short class names"
```

---

## Task 3 — M3: layout.css + 侧导航瘦身 + 顶部 action bar

**目标：** 主框架层抽到 `layout.css`，标签处理页加 `.top-action-bar`，侧导航 170px → 56px，主区网格改为 `1fr 320px`。

**Files:**
- Create: `static/css/layout.css`
- Create: `static/css/page-main.css`
- Modify: `templates/index.html`
- Modify: `static/css/index.css`（删除被迁移的布局规则）

- [ ] **Step 1: 写 `static/css/layout.css`**

```css
/* ========== App header ========== */
.app-header {
  height: 52px;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-4);
  background: var(--c-surface-elev);
  border-bottom: 1px solid var(--c-border);
}
.app-header__title { flex: 1; font-size: var(--fs-lg); font-weight: 700; }

/* ========== App layout ========== */
.app-layout { display: flex; flex: 1; overflow: hidden; }

/* ========== Side nav (slim) ========== */
.app-nav {
  width: 56px;
  background: var(--c-surface-deep);
  border-right: 1px solid var(--c-border);
  padding: var(--sp-3) var(--sp-1);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.app-nav.hide { width: 0; padding: 0; border-right: none; overflow: hidden; }
.app-nav__item {
  padding: var(--sp-2) 0;
  color: var(--c-text-muted);
  cursor: pointer;
  border-radius: var(--r-md);
  text-align: center;
  font-size: var(--fs-xs);
  line-height: 1.4;
  transition: background var(--t-fast);
}
.app-nav__item:hover { background: var(--c-surface-elev); color: var(--c-text); }
.app-nav__item.active { background: var(--c-accent-soft); color: var(--c-accent-fg); }
.app-nav__icon { display: block; font-size: 16px; margin-bottom: 2px; }

/* ========== Main + pages ========== */
.app-main { flex: 1; display: flex; overflow: hidden; }
.app-pages { flex: 1; padding: var(--sp-4); overflow: hidden; min-height: 0; }
.page { display: none; height: 100%; }
.page.active { display: grid; gap: var(--sp-4); overflow-y: auto; min-height: 0; }
```

- [ ] **Step 2: 写 `static/css/page-main.css`**

```css
/* ========== Page: 标签处理（T3 重排） ========== */
#pageMain.active {
  grid-template-columns: 1fr 320px;
  grid-template-rows: auto 1fr;
  height: calc(100vh - 84px);
}

/* 顶部 action bar 跨两列 */
.top-action-bar {
  grid-column: 1 / 3;
  display: flex;
  gap: var(--sp-3);
  align-items: stretch;
}
.top-action-bar .drop { flex: 1; padding: var(--sp-3) var(--sp-4); margin: 0; }
.top-action-bar .btn { width: auto; padding: 0 var(--sp-5); margin: 0; min-width: 140px; }

/* 异常处理面板：占左列、撑满 2 行 */
#warnPanel { grid-column: 1; grid-row: 2; }

/* Stockpile 面板：占右列 */
#stockpilePanel { grid-column: 2; grid-row: 2; }

/* ========== Page: 重复检查 ========== */
#pageDup.active { grid-template-columns: 1fr; height: calc(100vh - 84px); }
```

- [ ] **Step 3: `templates/index.html` 改 link、改类名、改主页结构**

**3a) link 段（替换 head 内全部 css link）：**

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/base.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/components.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/layout.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-main.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/index.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/purchase.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/attendance.css') }}">
```

**3b) header / nav / layout 类名替换：**

| 旧 | 新 |
|---|---|
| `<div class="header">` | `<div class="app-header">` |
| `<div class="header-title">` | `<div class="app-header__title">` |
| `<div class="layout">` | `<div class="app-layout">` |
| `<div class="nav" id="nav">` | `<div class="app-nav" id="nav">` |
| `<div class="nav-item ...">` | `<div class="app-nav__item ...">` |
| `<div class="main">` | `<div class="app-main">` |
| `<div class="pages">` | `<div class="app-pages">` |

**3c) 侧导航文字 + 图标（emoji）：**

```html
<div class="app-nav" id="nav">
  <div class="app-nav__item active" id="navMain" onclick="switchPage('main')">
    <span class="app-nav__icon">📋</span>标签
  </div>
  <div class="app-nav__item" id="navDup" onclick="switchPage('dup')">
    <span class="app-nav__icon">🔍</span>查重
  </div>
  <div class="app-nav__item" id="navPurchase" onclick="switchPage('purchase')">
    <span class="app-nav__icon">📦</span>采购
  </div>
  <div class="app-nav__item" id="navAttendance" onclick="switchPage('attendance')">
    <span class="app-nav__icon">🕐</span>考勤
  </div>
</div>
```

**3d) `#pageMain` 内部重排为：top-action-bar + warnPanel + stockpilePanel + （文件上传按钮组合并入 stockpilePanel 之上的右列卡，或保留为独立按钮组——本步暂保留按钮在 stockpilePanel 上方，作为"操作面板"）**

新结构（替换原 `#pageMain` 内全部）：

```html
<div class="page active" id="pageMain">

  <!-- 顶部 action bar（跨两列） -->
  <div class="top-action-bar">
    <div class="drop" id="drop">
      <input type="file" id="fileInput" multiple accept=".xlsx,.csv">
      <div>📂 拖入文件或点击选择</div>
      <div class="hint">支持扫描 .xlsx、stockpile .csv、模板 .csv</div>
    </div>
    <button class="btn btn-primary" id="run" disabled>开始处理</button>
  </div>

  <!-- 主区：异常处理 -->
  <div class="panel" id="warnPanel">
    <div class="panel-hd">异常处理</div>
    <div class="panel-bd" id="warnBox">
      <div class="empty">暂无需要人工处理的异常</div>
    </div>
  </div>

  <!-- 右列：操作 + Stockpile（M4 改 tab） -->
  <div class="panel" id="stockpilePanel">
    <div class="panel-hd">文件与 Stockpile</div>
    <div class="panel-bd">
      <!-- 文件管理按钮组 -->
      <div class="files" id="files"></div>
      <button class="btn btn-secondary" id="upload" disabled>上传文件</button>
      <button class="btn btn-warning" id="cont">继续处理</button>
      <button class="btn btn-success" id="download">下载结果</button>
      <button class="btn btn-info" id="copyModels">复制所有型号</button>
      <button class="btn btn-info" id="copyModelsAll" hidden>复制所有型号（含重复）</button>
      <button class="btn btn-ghost" id="reset">清空界面，准备下一批</button>
      <div class="status" id="status">请先上传文件</div>

      <hr style="border:0;border-top:1px solid var(--c-border);margin:14px 0">

      <!-- Stockpile（M4 会改为 tab，本步保持原 4 块） -->
      <div class="stockpile-status" id="spStatus">检查中...</div>
      <div class="row">
        <div class="drop" id="spInitDrop" style="flex:1">
          <input type="file" id="spInitInput" accept=".xlsx,.csv">
          <div>拖入系统导出文件初始化数据库</div>
        </div>
        <button class="btn-s is-ghost" id="spInitBtn" disabled>初始化</button>
      </div>
      <div id="spInitMsg" class="hint"></div>
      <div class="row" style="margin-top:8px">
        <div class="drop" id="spCmpDrop" style="flex:1">
          <input type="file" id="spCmpInput" accept=".xlsx,.csv">
          <div>拖入系统导出文件进行月度比对</div>
        </div>
        <button class="btn-s is-ghost" id="spCmpBtn" disabled>比对</button>
      </div>
      <div id="spCmpRes" class="hint"></div>
      <div style="margin-top:8px">
        <input type="text" id="spSearchInput" class="form-input-text" placeholder="搜索条码或型号（至少2个字符）">
        <div id="spSearchRes" class="hint" style="max-height:200px;overflow-y:auto"></div>
      </div>
    </div>
  </div>
</div>
```

注意：`style="..."` 不在本 task 清零（M7 统一处理），但**新写的内容里不要新增 inline style**——上面 `flex:1`、`max-height` 等 inline 是临时保留，下个 task / M7 会清。

把 `.form-input-text` 加到 `components.css`：

```css
.form-input-text {
  width: 100%;
  padding: 6px 8px;
  background: var(--c-surface-deep);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  color: var(--c-text);
  font-size: var(--fs-base);
  outline: none;
  box-sizing: border-box;
}
.form-input-text:focus { border-color: var(--c-accent); }
```

- [ ] **Step 4: 从旧 `static/css/index.css` 删除被迁移的规则**

删除：`.header`、`.header-title`、`.layout`、`.nav`、`.nav.hide`、`.nav-item` 系列、`.main`、`.pages`、`.page`、`.page.active`、`#pageMain.active`、`#pageDup.active`。

留下：`.transfer / .term / .tt / .tf / .tname / .ts / .tdl / .msg / .txt / .ta / .tb / .tsend / .list / .mi / .mh / .ms / .mt / .mb / .md / .th / .dot / .ttl / .clear / .tbod / .log-* / @media` 这些后续步骤处理。

- [ ] **Step 5: 验证**

Run: Flask 起，浏览器开 A 端
Expected:
- 侧导航变窄 56px，4 项有 emoji 图标
- 标签处理页顶部出现 drop + 开始处理按钮（横排）
- 异常处理占左主区
- 右列 320px 是按钮组 + stockpile（视觉混在一起，下个 task M4 会优化）
- 切到查重 / 采购 / 考勤页，三页正常显示（CSS 还是旧的）
- console 无错误

- [ ] **Step 6: Commit**

```bash
git add static/css/layout.css static/css/page-main.css static/css/components.css static/css/index.css templates/index.html
git commit -m "refactor(frontend): M3 layout.css + slim nav + top action bar"
```

---

## Task 4 — M4: Stockpile tab 化 + index-stockpile.js 拆出

**目标：** 把右列里的 stockpile 4 子块（状态 / 初始化 / 比对 / 搜索）合为 1 个 tab 面板，并把相关 JS 从 `index.js` 拆到 `index-stockpile.js`。

**Files:**
- Create: `static/js/index-stockpile.js`
- Modify: `static/js/index.js`（移除 stockpile 代码）
- Modify: `static/css/components.css`（加 `.tabs` 组件）
- Modify: `templates/index.html`（重写 stockpilePanel 内部，移除按钮组到独立 panel？保留——见下）
- Modify: `static/css/page-main.css`（调整 grid，stockpile 面板与按钮组分两个面板）

- [ ] **Step 1: 加 `.tabs` 到 `components.css`**

```css
.tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--c-border);
  margin-bottom: var(--sp-3);
}
.tabs__tab {
  padding: 6px 12px;
  font-size: var(--fs-md);
  color: var(--c-text-dim);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color var(--t-fast), border-color var(--t-fast);
  background: transparent;
  border-top: none;
  border-left: none;
  border-right: none;
  font-family: inherit;
}
.tabs__tab:hover { color: var(--c-text-muted); }
.tabs__tab.active { color: var(--c-accent-fg); border-bottom-color: var(--c-accent); }
.tabs__panel { display: none; }
.tabs__panel.active { display: block; }
```

- [ ] **Step 2: `static/css/page-main.css` 调整为 3 行 grid（顶部 bar + 异常 + 文件操作 + stockpile）**

```css
#pageMain.active {
  grid-template-columns: 1fr 340px;
  grid-template-rows: auto 1fr;
  height: calc(100vh - 84px);
}

#warnPanel { grid-column: 1; grid-row: 2; }

/* 右列：上半文件操作面板 + 下半 stockpile */
.right-stack {
  grid-column: 2;
  grid-row: 2;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  min-height: 0;
}
#filesPanel { flex: 0 0 auto; }
#stockpilePanel { flex: 1; min-height: 0; }
```

- [ ] **Step 3: `templates/index.html` 重写 #pageMain 右列**

替换原 `<div class="panel" id="stockpilePanel">...</div>` 为：

```html
<div class="right-stack">

  <div class="panel" id="filesPanel">
    <div class="panel-hd">文件管理</div>
    <div class="panel-bd">
      <div class="files" id="files"></div>
      <button class="btn btn-secondary" id="upload" disabled>上传文件</button>
      <button class="btn btn-warning" id="cont">继续处理</button>
      <button class="btn btn-success" id="download">下载结果</button>
      <button class="btn btn-info" id="copyModels">复制所有型号</button>
      <button class="btn btn-info" id="copyModelsAll" hidden>复制所有型号（含重复）</button>
      <button class="btn btn-ghost" id="reset">清空界面，准备下一批</button>
      <div class="status" id="status">请先上传文件</div>
    </div>
  </div>

  <div class="panel" id="stockpilePanel">
    <div class="panel-hd">Stockpile 数据库</div>
    <div class="panel-bd">
      <div class="tabs" id="spTabs">
        <button class="tabs__tab active" data-tab="status">状态</button>
        <button class="tabs__tab" data-tab="init">初始化</button>
        <button class="tabs__tab" data-tab="cmp">月度比对</button>
        <button class="tabs__tab" data-tab="search">搜索</button>
      </div>

      <div class="tabs__panel active" data-tab-panel="status">
        <div class="stockpile-status" id="spStatus">检查中...</div>
      </div>

      <div class="tabs__panel" data-tab-panel="init">
        <div class="drop" id="spInitDrop">
          <input type="file" id="spInitInput" accept=".xlsx,.csv">
          <div>拖入系统导出文件初始化数据库</div>
        </div>
        <button class="btn btn-secondary" id="spInitBtn" disabled>初始化</button>
        <div id="spInitMsg" class="hint"></div>
      </div>

      <div class="tabs__panel" data-tab-panel="cmp">
        <div class="drop" id="spCmpDrop">
          <input type="file" id="spCmpInput" accept=".xlsx,.csv">
          <div>拖入系统导出文件进行月度比对</div>
        </div>
        <button class="btn btn-secondary" id="spCmpBtn" disabled>比对</button>
        <div id="spCmpRes" class="hint"></div>
      </div>

      <div class="tabs__panel" data-tab-panel="search">
        <input type="text" id="spSearchInput" class="form-input-text" placeholder="搜索条码或型号（至少2个字符）">
        <div id="spSearchRes" class="hint stockpile-search-results"></div>
      </div>
    </div>
  </div>

</div>
```

加 `static/css/page-main.css`：

```css
.stockpile-search-results { max-height: 200px; overflow-y: auto; margin-top: 6px; }
```

- [ ] **Step 4: 从 `static/js/index.js` 找出所有 stockpile 相关代码（`spStatus / spInit* / spCmp* / spSearch*` 全套），剪贴到新文件 `static/js/index-stockpile.js`**

新文件框架（具体 import 与函数从原 `index.js` 抠出，下面是结构示例）：

```js
import { setupDropZone } from "./shared.js";

const $ = (s) => document.querySelector(s);

// === Tab 切换 ===
function initTabs() {
  const tabs = document.querySelectorAll("#spTabs .tabs__tab");
  const panels = document.querySelectorAll('[data-tab-panel]');
  tabs.forEach((t) => {
    t.addEventListener("click", () => {
      const target = t.dataset.tab;
      tabs.forEach((x) => x.classList.toggle("active", x === t));
      panels.forEach((p) => p.classList.toggle("active", p.dataset.tabPanel === target));
    });
  });
}

// === 状态 / 初始化 / 比对 / 搜索 ===
// （从原 index.js 中"stockpile" 相关 fetch 调用、按钮 onclick、setupDropZone 全部剪过来）

export function initStockpile() {
  initTabs();
  // 调用原有 init / cmp / search 绑定
  // ...
}
```

**剪切原则：** 在原 `index.js` 中 grep `sp[A-Z]` 命中的所有代码块（含 `setupDropZone($("#spInitDrop"), ...)`、`$("#spInitBtn").onclick = ...`、`$("#spCmpBtn").onclick = ...`、`$("#spSearchInput").addEventListener(...)`、`fetch("/stockpile/...")` 等），逐块剪到 `index-stockpile.js`，组装到 `initStockpile()` 内。

- [ ] **Step 5: `static/js/index.js` 顶部加 import + 调用**

```js
import { initStockpile } from "./index-stockpile.js";
// ...其他 import 保留

// 文件末尾或合适位置：
initStockpile();
```

- [ ] **Step 6: `templates/index.html` 加 `<script>` 引入新模块**（如果 `index.js` 直接 import，则**不需要**额外 script tag——原 `<script type="module" src=".../index.js">` 即可拉取依赖）

确认 `<body>` 末尾保持：

```html
<script type="module" src="{{ url_for('static', filename='js/index.js') }}"></script>
<script type="module" src="{{ url_for('static', filename='js/purchase.js') }}"></script>
<script type="module" src="{{ url_for('static', filename='js/attendance.js') }}"></script>
```

- [ ] **Step 7: 验证**

Run: Flask 起，A 端 → 标签处理页
Expected:
- 右列分成两个面板：上"文件管理"按钮组，下"Stockpile 数据库"
- Stockpile 面板顶部有 4 个 tab，点切换正常
- 状态 tab 显示 "检查中..." 或后端返回的状态
- 初始化 tab 拖入文件能选中（按钮启用）
- 比对 tab 同上
- 搜索 tab 输入框响应（输入 ≥2 字符后调 `/stockpile/search`，显示结果）
- console 无报错

- [ ] **Step 8: Commit**

```bash
git add static/css/components.css static/css/page-main.css static/js/index-stockpile.js static/js/index.js templates/index.html
git commit -m "refactor(frontend): M4 stockpile tabs + extract index-stockpile.js"
```

---

## Task 5 — M5: 终端日志 → 浮动 FAB + 抽屉

**目标：** 移除标签处理页内的 200px 终端日志面板（已在 M3 顺手砍），改为右下角浮动按钮 + 可展开抽屉。日志条数显示在按钮上。

**Files:**
- Create: `static/css/widgets/terminal-log.css`
- Modify: `templates/index.html`（在 `</body>` 前加 fab + drawer DOM）
- Modify: `static/js/index.js`（加 toggle 逻辑、计数）
- Modify: `templates/index.html`（加 `<link>` 引入 widget CSS）

- [ ] **Step 1: 写 `static/css/widgets/terminal-log.css`**

```css
.term-fab {
  position: fixed;
  right: var(--sp-4);
  bottom: var(--sp-4);
  z-index: 28;
  background: var(--c-surface-elev);
  border: 1px solid var(--c-border);
  color: var(--c-text-muted);
  border-radius: var(--r-pill);
  padding: 8px 14px;
  font-size: var(--fs-md);
  cursor: pointer;
  box-shadow: var(--sh-fab);
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
}
.term-fab:hover { background: var(--c-border); color: var(--c-text); }
.term-fab__count {
  display: inline-block;
  min-width: 20px;
  padding: 1px 6px;
  background: var(--c-accent);
  color: #fff;
  border-radius: var(--r-pill);
  font-size: var(--fs-xs);
  font-weight: 700;
}
.term-fab__count.is-pulse { animation: term-pulse 1.2s ease; }
@keyframes term-pulse {
  0% { box-shadow: 0 0 0 0 rgba(79,70,229,.6); }
  100% { box-shadow: 0 0 0 12px rgba(79,70,229,0); }
}

.terminal-log {
  position: fixed;
  bottom: var(--sp-6);
  left: 50%;
  transform: translateX(-50%);
  width: 620px;
  height: 220px;
  background: #0d0f1a;
  border: 1px solid #3d4166;
  border-radius: var(--r-xl);
  box-shadow: var(--sh-overlay);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 30;
  transition: var(--t-base);
}
.terminal-log.hide {
  opacity: 0;
  pointer-events: none;
  transform: translateX(-50%) translateY(16px);
}
.terminal-log__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 8px 14px;
  border-bottom: 1px solid #1e2433;
  background: #12142080;
}
.terminal-log__title {
  flex: 1;
  font-size: var(--fs-sm);
  font-weight: 700;
  color: var(--c-text-faint);
  text-transform: uppercase;
}
.terminal-log__close, .terminal-log__clear {
  font-size: var(--fs-sm);
  padding: 2px 9px;
  border-radius: var(--r-sm);
  background: transparent;
  border: 1px solid var(--c-border);
  color: var(--c-text-dim);
  cursor: pointer;
  font-family: inherit;
}
.terminal-log__close:hover, .terminal-log__clear:hover { background: var(--c-border); color: #fff; }
.terminal-log__body {
  flex: 1;
  overflow: auto;
  padding: 8px 14px;
  font-family: var(--ff-mono);
  font-size: var(--fs-md);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.6;
}
.log-lp { color: var(--c-accent-fg); }
.log-dc { color: #2dd4bf; }
.log-err { color: var(--c-danger); }
.log-warn { color: var(--c-warn); }
.log-ok { color: var(--c-success); }
.log-dim { color: var(--c-text-faint); }

@media (max-width: 1100px) {
  .terminal-log { width: calc(100vw - 32px); left: 16px; transform: none; }
  .terminal-log.hide { transform: translateY(16px); }
}
```

- [ ] **Step 2: `templates/index.html` 加 `<link>` 引入**

紧跟其他 css link 之后：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/widgets/terminal-log.css') }}">
```

- [ ] **Step 3: `templates/index.html` 在 `</body>` 之前加 FAB + Drawer DOM**

```html
<button class="term-fab" id="termFab" type="button">
  <span>▸ 终端日志</span>
  <span class="term-fab__count" id="termFabCount">0</span>
</button>

<div class="terminal-log hide" id="termDrawer">
  <div class="terminal-log__head">
    <span style="width:8px;height:8px;border-radius:50%;background:var(--c-border)"></span>
    <span class="terminal-log__title">终端日志</span>
    <button class="terminal-log__clear" onclick="clearLog()">清空</button>
    <button class="terminal-log__close" id="termClose">收起</button>
  </div>
  <div class="terminal-log__body" id="tbod">
    <span class="log-dim">等待操作</span>
  </div>
</div>
```

注意：`#tbod` ID 保留（`index.js` 的 `renderLog` 不需要改）。

**确认 M3 中已经从 `#pageMain` 内移除了原"终端日志面板 200px"** —— 如果 M3 没移除，本步移除：删除 `<div class="panel" style="height:200px">...终端日志...</div>` 整块。

- [ ] **Step 4: `static/js/index.js` 加 toggle + 计数逻辑**

在 `renderLog()` 函数末尾追加：

```js
function renderLog() {
  const tbod = $("#tbod");
  tbod.innerHTML = logs.length
    ? logs.map((i) => `<div class="${i.src === "dc" ? "log-dc" : "log-lp"} ${i.cls}">${esc(i.text)}</div>`).join("")
    : '<span class="log-dim">等待操作</span>';
  tbod.scrollTop = tbod.scrollHeight;

  // 更新 FAB 计数 + pulse
  const count = $("#termFabCount");
  if (count) {
    count.textContent = String(logs.length);
    count.classList.remove("is-pulse");
    void count.offsetWidth;
    count.classList.add("is-pulse");
  }
}
```

在文件末尾加 toggle 绑定：

```js
$("#termFab")?.addEventListener("click", () => {
  $("#termDrawer").classList.toggle("hide");
});
$("#termClose")?.addEventListener("click", () => {
  $("#termDrawer").classList.add("hide");
});
```

- [ ] **Step 5: 验证**

Run: Flask 起，A 端
Expected:
- 右下角出现"▸ 终端日志 [0]"胶囊按钮
- 点击展开浮动日志面板
- 标签处理页底部不再有固定 200px 日志面板（异常处理面板撑满左主区）
- 上传文件后，日志计数 +1，FAB pulse 一下
- 点 FAB 收起 / 展开正常
- "清空"按钮工作
- console 无报错

- [ ] **Step 6: 从旧 `index.css` 删除 `.term / .term.hide / .th / .dot / .ttl / .clear / .tbod / .log-*` 规则及 `@media` 中关于 `.term` 的部分**

- [ ] **Step 7: Commit**

```bash
git add static/css/widgets/terminal-log.css static/css/index.css templates/index.html static/js/index.js
git commit -m "refactor(frontend): M5 terminal log as floating FAB + drawer"
```

---

## Task 6 — M6: 文件互传 → 右上 FAB + 滑出抽屉

**目标：** 移除常驻 300px 右栏 `.transfer`，改为右上胶囊按钮 + 从右滑入抽屉。所有 id 不变，`transfer.js / messaging.js` 选择器照常工作。

**Files:**
- Create: `static/css/widgets/transfer-drawer.css`
- Modify: `templates/index.html`（移除 `.transfer` 块、加 FAB + drawer）
- Modify: `static/js/index.js`（toggle 逻辑）
- Modify: 旧 `index.css` 清理 `.transfer / .tt / .tf / ... / .mi / ...` 等规则

- [ ] **Step 1: 写 `static/css/widgets/transfer-drawer.css`**

```css
.transfer-fab {
  position: fixed;
  right: var(--sp-4);
  top: 12px;
  z-index: 27;
  background: var(--c-surface-elev);
  border: 1px solid var(--c-border);
  color: var(--c-text-muted);
  border-radius: var(--r-pill);
  padding: 6px 14px;
  font-size: var(--fs-md);
  cursor: pointer;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
}
.transfer-fab:hover { background: var(--c-border); color: var(--c-text); }
.transfer-fab__dot {
  display: inline-block;
  width: 6px; height: 6px;
  background: var(--c-danger);
  border-radius: 50%;
  visibility: hidden;
}
.transfer-fab__dot.is-on { visibility: visible; }

.transfer-drawer {
  position: fixed;
  top: 0; right: 0;
  width: 320px;
  height: 100vh;
  background: var(--c-surface-deep);
  border-left: 1px solid var(--c-border);
  padding: var(--sp-3);
  overflow: auto;
  z-index: 26;
  transform: translateX(100%);
  transition: transform var(--t-base);
  box-shadow: var(--sh-overlay);
}
.transfer-drawer.is-open { transform: translateX(0); }

.transfer-drawer__head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: var(--sp-3);
}
.transfer-drawer__title { font-weight: 700; color: var(--c-text); }
.transfer-drawer__close {
  background: transparent;
  border: 1px solid var(--c-border);
  color: var(--c-text-muted);
  border-radius: var(--r-sm);
  padding: 4px 10px;
  cursor: pointer;
  font-family: inherit;
}

/* 复用旧 transfer 内部样式（重命名） */
.section-label {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--c-text-faint);
  text-transform: uppercase;
  letter-spacing: .06em;
  margin: 12px 0 6px;
}
.transfer-file {
  display: flex; align-items: center; justify-content: space-between;
  gap: 6px;
  background: var(--c-bg);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  padding: 5px 9px;
  margin-bottom: 4px;
  font-size: var(--fs-md);
}
.transfer-file__name {
  color: var(--c-text-mute2);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 150px;
}
.transfer-file__size { color: var(--c-text-faint); }
.transfer-file__dl {
  font-size: var(--fs-sm);
  color: var(--c-accent);
  padding: 2px 6px;
  border-radius: var(--r-sm);
  border: 1px solid var(--c-accent);
  text-decoration: none;
}
.transfer-file__dl:hover { background: var(--c-accent); color: #fff; }

.text-msg-input {
  width: 100%;
  background: var(--c-bg);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  color: #fff;
  font-size: var(--fs-md);
  padding: 8px 10px;
  resize: none;
  outline: none;
  font-family: inherit;
}
.text-msg-input:focus { border-color: var(--c-accent); }

.text-msg-actions { display: flex; gap: 5px; justify-content: flex-end; margin-top: 6px; }
.text-msg-btn {
  background: var(--c-surface-deep);
  color: var(--c-text-muted);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  padding: 6px 12px;
  font-size: var(--fs-md);
  cursor: pointer;
}
.text-msg-btn:hover { background: var(--c-border); color: #fff; }
.text-msg-btn.copied { color: var(--c-success); border-color: var(--c-success); }
.text-msg-send {
  background: var(--c-accent);
  color: #fff; border: none;
  border-radius: var(--r-sm);
  padding: 6px 12px;
  font-size: var(--fs-md);
  cursor: pointer;
}
.text-msg-send:hover { background: var(--c-accent-hover); }

.message-list {
  display: flex; flex-direction: column; gap: 5px;
  max-height: 240px; overflow: auto; margin-top: 8px;
}
.message {
  background: var(--c-bg);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 7px 9px;
  font-size: var(--fs-md);
}
.message.is-self { border-color: var(--c-accent); }
.message__head {
  display: flex; justify-content: space-between; align-items: center;
  gap: 6px; margin-bottom: 3px;
}
.message__source { font-weight: 700; color: var(--c-text-muted); font-size: var(--fs-xs); }
.message.is-self .message__source { color: var(--c-accent-fg); }
.message__time { color: var(--c-text-faint); font-size: var(--fs-xs); }
.message__body { color: var(--c-text); word-break: break-all; white-space: pre-wrap; }
.message__del {
  background: transparent; border: none;
  color: var(--c-text-faint);
  cursor: pointer; font-size: var(--fs-sm);
  padding: 0 3px;
}
.message__del:hover { color: var(--c-danger); }
```

- [ ] **Step 2: 引入 `<link>`**

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/widgets/transfer-drawer.css') }}">
```

- [ ] **Step 3: `templates/index.html` 移除原 `<div class="transfer">...</div>` 整块，并替换为：**

```html
<button class="transfer-fab" id="transferFab" type="button">
  <span>📨 文件互传</span>
  <span class="transfer-fab__dot" id="transferFabDot"></span>
</button>

<aside class="transfer-drawer" id="transferDrawer">
  <div class="transfer-drawer__head">
    <span class="transfer-drawer__title">文件互传</span>
    <button class="transfer-drawer__close" id="transferDrawerClose" type="button">关闭</button>
  </div>

  <div class="section-label">发送文件给 B 端</div>
  <div class="t-drop" id="tDrop">
    <input type="file" id="tInput" multiple>
    <div>拖入或点击，发送文件给 B 端</div>
  </div>
  <div class="msg" id="tMsg"></div>

  <div class="section-label">B 端共享文件</div>
  <div id="tList"><div class="empty">暂无</div></div>

  <div class="section-label">文字互传</div>
  <textarea class="text-msg-input" id="textInput" rows="3" placeholder="输入消息，发送给 B 端（Ctrl+Enter）"></textarea>
  <div class="text-msg-actions">
    <button class="text-msg-btn" id="copyText" type="button">复制</button>
    <button class="text-msg-send" id="sendText" type="button">发送</button>
  </div>
  <div class="message-list" id="msgList"><div class="empty">暂无消息</div></div>
</aside>
```

**注意：** 类名变了的部分（`.tt → .section-label`、`.tf → .transfer-file`、`.txt → .text-msg-input`、`.tb → .text-msg-btn`、`.tsend → .text-msg-send`、`.list → .message-list`、`.mi → .message`、`.mh → .message__head`、`.ms → .message__source`、`.mt → .message__time`、`.mb → .message__body`、`.md → .message__del`）需要在 `transfer.js / messaging.js` 内的 `innerHTML` 字符串里同步替换。

`grep` 这两个文件中的字面量类名，全部改名。

- [ ] **Step 4: `static/js/index.js` 加 drawer toggle**

```js
$("#transferFab")?.addEventListener("click", () => {
  $("#transferDrawer").classList.toggle("is-open");
  $("#transferFabDot").classList.remove("is-on");
});
$("#transferDrawerClose")?.addEventListener("click", () => {
  $("#transferDrawer").classList.remove("is-open");
});
```

可选：在 `loadTransferFiles` / `loadMessages` 检测到新内容时，给 dot 加 `.is-on`。本 task 不做（YAGNI），用户主动点开即可。

- [ ] **Step 5: `static/css/index.css` 删除 `.transfer / .tt / .tf / .tname / .ts / .tdl / .msg / .txt / .ta / .tb / .tsend / .list / .mi / .mh / .ms / .mt / .mb / .md` 全部规则及 `@media` 中关于 `.transfer` 的部分**

- [ ] **Step 6: 验证**

Run: Flask 起，A + B 都起；A 端
Expected:
- 右上"📨 文件互传"胶囊按钮
- 点击右滑抽屉打开
- 拖入文件能上传到 B 端（B 端能看到）
- B 端发文件回 A，A 端 tList 出现
- 文字消息双向收发，"复制"/"删除"按钮工作
- 关闭抽屉后内容仍保留（DOM 不销毁）
- console 无报错

- [ ] **Step 7: Commit**

```bash
git add static/css/widgets/transfer-drawer.css static/css/index.css templates/index.html static/js/index.js static/js/transfer.js static/js/messaging.js
git commit -m "refactor(frontend): M6 transfer panel as right-edge slide drawer"
```

---

## Task 7 — M7: inline style 清零

**目标：** 把 HTML / JS 中所有 `style="..."` 替换为类名（M3-M6 中保留的"临时" inline 也一并清掉）。

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/index.js`
- Modify: `static/js/index-warnings.js`
- Modify: `static/js/attendance.js`
- Modify: `static/js/purchase.js`
- Modify: `static/js/transfer.js / messaging.js`（如有遗留）
- Modify: `static/css/components.css`（追加 utility 类）

- [ ] **Step 1: 列清单**

```bash
grep -rn 'style="' templates/ static/js/
```

把每个命中分类：
- 纯排版（`flex:1`、`margin-top:8px`、`max-height:200px` 等）→ 加 utility 类
- 与组件耦合的（如 `border-color:#fb923c`）→ 加组件 modifier 类
- 一次性（如 `background:#... ` 仅这处）→ 加专用类

- [ ] **Step 2: 在 `components.css` 末尾加 utility 类**

```css
/* ========== Utilities ========== */
.u-flex-1 { flex: 1; }
.u-mt-1 { margin-top: var(--sp-1); }
.u-mt-2 { margin-top: var(--sp-2); }
.u-mt-3 { margin-top: var(--sp-3); }
.u-hidden { display: none !important; }

.u-stack { display: flex; flex-direction: column; gap: var(--sp-2); }
.u-row { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
```

按真实需求增减。如已有更具体的 panel/section 类，优先用具体类。

- [ ] **Step 3: 逐文件替换**

每个文件用 Edit 工具，把 `style="X"` 替换为 `class="..."`（合并到现有 class）：
- `templates/index.html` ：14 处（含 M3 临时保留的 `flex:1`、`max-height:200px` 等）
- `static/js/index.js` ：12 处
- `static/js/index-warnings.js` ：10 处
- `static/js/attendance.js` ：12 处
- `static/js/purchase.js` ：3 处

**注意：** 在 JS 字符串拼接里替换时，注意引号匹配。比如：

```js
// 旧
html += `<div class="row" style="margin-top:8px">...</div>`;
// 新
html += `<div class="row u-mt-2">...</div>`;
```

- [ ] **Step 4: 验证**

```bash
grep -rn 'style="' templates/ static/js/ | wc -l
```

Expected: `0`

启动 Flask，逐页点过：标签处理 / 查重 / 采购 / 考勤 / 文件互传抽屉。视觉无回退，console 无报错。

- [ ] **Step 5: Commit**

```bash
git add templates/ static/js/ static/css/components.css
git commit -m "refactor(frontend): M7 zero inline styles"
```

---

## Task 8 — M8: 其他 3 页换皮（T2）

**目标：** `page-dup.css / page-purchase.css / page-attendance.css` 用 token 重写；删除旧 `purchase.css / attendance.css`。

**Files:**
- Create: `static/css/page-dup.css`
- Create: `static/css/page-purchase.css`
- Create: `static/css/page-attendance.css`
- Modify: `templates/index.html`（替换旧 link）
- Delete: `static/css/purchase.css`、`static/css/attendance.css`
- Modify: `static/css/index.css`（删除 `.dup-top / .dup-res / .sum / table / th / td` 等迁移到 `page-dup.css` 的规则）

### Step 1-3: 写 `page-dup.css`

```css
.dup-top {
  border: 2px dashed var(--c-border);
  border-radius: var(--r-md);
  padding: 28px;
  text-align: center;
  cursor: pointer;
}
.dup-top:hover, .dup-top.drag {
  border-color: var(--c-accent);
  background: #1e1b4b22;
}
.dup-top input { display: none; }
.dup-res { margin-top: 14px; overflow: auto; }

.sum {
  font-size: var(--fs-base);
  color: var(--c-text-muted);
  margin-bottom: var(--sp-3);
  padding: 10px 14px;
  background: var(--c-surface-elev);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
}
.sum .hl { color: var(--c-danger); font-weight: 700; }
.sum .ok { color: var(--c-success); font-weight: 700; }

table { width: 100%; border-collapse: collapse; font-size: var(--fs-base); }
th {
  text-align: left;
  padding: 8px 12px;
  background: var(--c-surface-elev);
  color: var(--c-text-dim);
  font-size: var(--fs-sm);
  border-bottom: 1px solid var(--c-border);
}
td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--c-surface-elev);
  color: var(--c-text-mute2);
}
```

### Step 4-5: 写 `page-purchase.css`

读旧 `static/css/purchase.css`（53 行），逐条用 token 重写。常见映射：`#1a1d27` → `var(--c-surface-elev)`、`#2d3148` → `var(--c-border)`、`#e2e8f0` → `var(--c-text)`、`#94a3b8` → `var(--c-text-muted)`、`#4f46e5` → `var(--c-accent)`、`#0f1117` → `var(--c-bg)`，圆角统一 `var(--r-md)`。具体规则照抄结构，仅替换值。

### Step 6-7: 写 `page-attendance.css`

读旧 `static/css/attendance.css`（26 行），同上原则重写。

### Step 8: `templates/index.html` 改 link

替换旧 `purchase.css / attendance.css` 引用为：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-dup.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-purchase.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/page-attendance.css') }}">
```

### Step 9: 验证

Run: Flask 起，A 端 → 切到查重 / 采购 / 考勤每一页都点一遍
Expected:
- 视觉与新设计一致（深色 #0f1117，紫色强调）
- 查重上传 csv，结果表正常
- 采购 / 考勤逻辑无回退（购买、月度、考勤记录展开等）
- console 无报错

### Step 10: Commit

```bash
git add static/css/page-dup.css static/css/page-purchase.css static/css/page-attendance.css templates/index.html static/css/index.css
git commit -m "refactor(frontend): M8 reskin dup/purchase/attendance with tokens"
```

### Step 11: 删除旧 css 文件

```bash
git rm static/css/purchase.css static/css/attendance.css
git commit -m "refactor(frontend): M8 remove legacy purchase.css/attendance.css"
```

---

## Task 9 — M9: 收尾清理 + final 验证

**目标：** 把旧 `index.css`（1 行混杂遗留）清空 / 删除；做完整的页面 walkthrough，确保没有遗漏。

**Files:**
- Delete or empty: `static/css/index.css`
- Modify: `templates/index.html`（移除旧 link）

- [ ] **Step 1: 检查旧 `static/css/index.css` 还剩什么**

```bash
cat static/css/index.css
```

Expected: 经过 M1-M8 后，文件应已经空 / 几乎空。如还剩规则，逐条判断：能合到 `components / page-main / widget` 的合过去，无家可归的删（说明已废弃）。

- [ ] **Step 2: `git rm` 旧 `index.css`，移除 `<link>`**

```bash
git rm static/css/index.css
```

`templates/index.html` 删除：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/index.css') }}">
```

- [ ] **Step 3: 全量 walkthrough**

启动 Flask + B 端（如有），从头跑一遍：

1. 打开 A 端 → 标签处理：
   - 顶部 action bar：drop + "开始处理"
   - 异常处理面板（左主区）
   - 文件管理面板（右上）：上传 / 继续 / 下载 / 复制 / 重置 按钮，颜色对
   - Stockpile 面板（右下）4 个 tab 切换正常
   - 终端日志 FAB（右下）展开 / 收起，pulse 正常
   - 文件互传 FAB（右上）抽屉滑入 / 滑出，文件 + 文字双向工作
2. 切到 查重：drop + 结果表
3. 切到 采购：DOM 渲染正常，按钮 / 表格 / 模态等
4. 切到 考勤：DOM 渲染正常
5. 移动模拟（DevTools 1024px 以下）：transfer drawer 仍可用，terminal-log 自适应
6. 浏览器 console 全程无错误

- [ ] **Step 4: 跑后端测试套件确保无副作用**

```bash
pytest tests/
```

Expected: 全绿（前端重构理论上不影响后端）。

- [ ] **Step 5: 最终检查**

```bash
grep -rn 'style="' templates/ static/js/ | wc -l   # 应为 0
ls static/css/                                       # 应只剩新文件
```

- [ ] **Step 6: Commit + （如需要）push**

```bash
git add -u
git commit -m "refactor(frontend): M9 cleanup legacy index.css + final pass"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Plan task |
|---|---|
| §3 Token | Task 1 |
| §4 CSS 文件结构 | Tasks 1-8 分次新建 |
| §5 类名重命名映射 | Task 2 (大部分) + Task 6 (transfer-related) |
| §6.1-6.2 主页 T3 重排 | Tasks 3-6 |
| §6.3 受影响 JS | Tasks 4 (stockpile)、5 (log toggle)、6 (transfer toggle)、7 (inline cleanup) |
| §6.4 不变项 (id 保留) | 全程遵守，每个 task 验证步骤都点旧 id |
| §7 其他 3 页 T2 | Task 8 |
| §8 M1-M9 里程碑 | Tasks 1-9 一一对应 |
| §9 验收 | 每个 task 的"验证"步骤 + Task 9 完整 walkthrough |
| §10 风险（id 保留 / 日志可见性 / B 端待办） | id 全保留；日志 FAB 有 pulse 提示；B 端不动 |
| §11 分支 `refactor/frontend-a-redesign` | 已建（写 plan 之前完成） |

**No gaps detected.**

**Placeholder scan:** 全文 grep "TBD / TODO / 之类"未命中。每个 step 都有具体代码 / 命令。

**Type / 类名一致性：** `tabs__tab / tabs__panel`、`terminal-log / terminal-log__body`、`transfer-drawer / transfer-fab` 命名一致；旧 → 新映射表统一在 Task 2 / Task 6。

---

## 执行选择

Plan 已存到 `docs/superpowers/plans/2026-04-27-frontend-redesign.md`。两种执行模式：

1. **Subagent-Driven（推荐）** — 每个 Task 派一个新 subagent 执行 + 中间 review，迭代快、上下文干净
2. **Inline Execution** — 在当前会话用 `executing-plans` 跑，分批 checkpoint

**选哪个？**
