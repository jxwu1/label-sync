# Filing Cabinet 主题第一轮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** 全站从 slate+indigo 暗色换为 Filing Cabinet 浅暖色（暖灰底 + 浅蓝纸 + 黑墨字 + 折角 tab 文件夹），仅顶部 chrome 重排，各页面内部布局保留以降低风险。

**Architecture:** 通过 token 替换 + chrome 重构推送视觉，**不动**任何 JS 逻辑、不改任何后端、不重排 panel 内部布局。

**Tech Stack:** 纯 CSS + HTML 模板。

**已确认设计：**
- 配色：参考 `C:\Users\jxwu2002\Desktop\filing_style_mockup.html` 的 token 体系
- 顶部：删除 `.app-header` + 左侧 `.app-nav`，改为顶部一行折角 tab（4 个：标签 / 查重 / 采购 / 考勤）
- 浮动按钮（终端日志 / 文件互传）保留位置但适配新色
- 各页（主页 / 重复检查 / 采购 / 考勤）布局保留，仅靠新 token 自动变浅色
- 出现"暖底+暗色组件"的过渡丑是预期的，本轮不修

**Mockup 参考：** `C:\Users\jxwu2002\Desktop\filing_style_mockup.html`

---

## File Structure

| 文件 | 操作 | 说明 |
|---|---|---|
| `static/css/tokens.css` | 全量改写 | 全套从暗 slate 改为浅 filing 暖灰 + 蓝灰，accent 用墨黑代替 indigo |
| `static/css/layout.css` | 重写 | `.app-header` 删除、`.app-nav` 改为顶部 tabs（折角文件夹） |
| `templates/index.html` | 改 chrome | 删除 `.app-header` 整个 `<div>` 和侧栏 nav 的当前结构，改为顶部 tabs |
| `static/css/components.css` | 局部调整 | 仅修改与 token 失配的硬编码（如 panel 边框假定深底） |
| `static/css/page-main.css` | 不动（除非过渡明显丑）| 内部布局保留 |
| `static/css/page-attendance.css` | 不动 | 已用 token，自动跟随 |
| `static/css/page-purchase.css` | 不动 | 同上 |
| `static/css/page-dup.css` | 不动 | 同上 |
| `static/js/index.js` | 不动 | `switchPage` 逻辑不依赖 nav class，HTML 改 tab 后仍工作 |
| `static/js/*.js` | 不动 | 全部 |
| `*.py` | 不动 | 全部 |

---

## Verification Strategy

1. `pytest` 全过（不应受影响，零 Python 改动）。
2. 浏览器 `python server.py` 打开每个 tab 都能跳转、没有 console 报错。
3. 视觉与 mockup A 套合理一致：浅蓝页面 + 暖灰卡片 + 折角 tab + 黑墨字。
4. 用户视觉验证后决定 keep / rollback。

---

## Task 1: 重写 tokens.css 为 Filing 浅色调色板

**Files:**
- Modify: `static/css/tokens.css`（全量替换）

- [ ] **Step 1：备份当前 tokens.css** — 仅当前会话工作记忆，不入库

```bash
cp static/css/tokens.css /tmp/tokens.css.dark-bak 2>/dev/null || cp static/css/tokens.css static/css/tokens.css.bak
```

- [ ] **Step 2：用以下内容完全替换 `static/css/tokens.css`**

```css
:root {
  /* 表面（Filing 浅暖色调） */
  --c-bg: #d8e0ec;            /* 页面浅蓝 */
  --c-surface: #ebe7da;       /* 卡片暖灰纸 */
  --c-surface-elev: #e3dece;  /* 略深暖灰，hover/elev 用 */
  --c-surface-deep: #d6d0bf;  /* 选中/最深 */
  --c-border: #c8c1ac;        /* 主边框 */
  --c-border-subtle: #d8d2bd; /* 次边框 */

  /* 文字（黑墨为主） */
  --c-text: #1a1a1a;
  --c-text-muted: #555555;
  --c-text-dim: #888888;
  --c-text-faint: #aaaaaa;
  --c-text-mute2: #4a443c;

  /* 强调（黑墨代替 indigo） */
  --c-accent: #1a1a1a;
  --c-accent-hover: #000000;
  --c-accent-soft: #ddd8c8;
  --c-accent-fg: #1a1a1a;

  /* 状态（暖底匹配） */
  --c-info: #2563b0;
  --c-info-bg: #cdd9e8;
  --c-success: #2f6f3a;
  --c-success-bg: #cfdfd0;
  --c-warn: #b56a00;
  --c-warn-strong: #a3520a;
  --c-warn-bg: #ecdcb6;
  --c-warn-bg-strong: #e3c994;
  --c-danger: #a82c1a;
  --c-danger-bg: #e8c8c0;
  --c-danger-border: #893821;

  /* 代码色 */
  --c-code: #b56a00;
  --c-loc: #2563b0;

  /* 间距（保持） */
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px;
  --sp-4: 16px; --sp-5: 20px; --sp-6: 24px;

  /* 圆角（保持） */
  --r-sm: 6px; --r-md: 8px; --r-lg: 10px; --r-xl: 14px; --r-pill: 999px;

  /* 字号（保持） */
  --fs-xs: 10px; --fs-sm: 11px; --fs-md: 12px; --fs-base: 13px; --fs-lg: 15px;

  /* 字体（保持） */
  --ff-sans: "Inter", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
  --ff-mono: "JetBrains Mono", "Cascadia Code", "Consolas", ui-monospace, monospace;

  /* 阴影（浅底用更轻的阴影） */
  --sh-fab: 0 4px 14px rgba(20,30,50,.12);
  --sh-overlay: 0 12px 36px rgba(20,30,50,.18);

  /* 动效（保持） */
  --t-fast: .12s ease;
  --t-base: .2s ease;
}
```

- [ ] **Step 3：删除备份**

```bash
rm -f static/css/tokens.css.bak
```

- [ ] **Step 4：浏览器粗扫**

```bash
python server.py
```

打开 `http://localhost:5000`，**预期画面是混乱的**（暖底 + 暗组件），但应该没有 JS 报错，可以切 tab。如果页面完全空白或报 CSS 解析错误，看控制台 → 修。

- [ ] **Step 5：Commit**

```bash
git add static/css/tokens.css
git commit -m "refactor(theme): tokens 切换到 Filing Cabinet 浅暖色调色板"
```

---

## Task 2: 重写 layout.css + 改 templates/index.html，顶部折角 tab 替代侧栏

**Files:**
- Modify: `static/css/layout.css`（全量替换）
- Modify: `templates/index.html`（行 19-34 部分替换）

- [ ] **Step 1：用以下内容完全替换 `static/css/layout.css`**

```css
/* ========== App layout（Filing Cabinet 风） ========== */
.app-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
  padding: 24px 28px 0;
  gap: 0;
}

/* 顶部 tabs（折角文件夹标签） */
.app-nav {
  display: flex;
  gap: 0;
  padding-left: 28px;
  margin-bottom: -8px;
  position: relative;
  z-index: 2;
  align-items: flex-end;
  height: 50px;
}
.app-nav.hide { display: none; }

.app-nav__item {
  background: var(--c-surface-deep);
  color: var(--c-text-muted);
  padding: 11px 28px 18px;
  font-size: var(--fs-base);
  font-weight: 500;
  cursor: pointer;
  border-radius: var(--r-lg) var(--r-lg) 0 0;
  border: none;
  margin-right: -10px;
  transition: background var(--t-fast), color var(--t-fast);
  user-select: none;
  position: relative;
  height: 38px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.app-nav__item::before, .app-nav__item::after {
  content: '';
  position: absolute;
  bottom: 0;
  width: 10px;
  height: 100%;
  background: inherit;
}
.app-nav__item::before { left: -8px; border-radius: var(--r-lg) 0 0 0; transform: skewX(-12deg); transform-origin: bottom left; }
.app-nav__item::after  { right: -8px; border-radius: 0 var(--r-lg) 0 0; transform: skewX(12deg);  transform-origin: bottom right; }
.app-nav__item:hover { background: var(--c-surface-elev); color: var(--c-text); }
.app-nav__item.active {
  background: var(--c-surface);
  color: var(--c-text);
  font-weight: 600;
  z-index: 3;
  height: 44px;
}
.app-nav__icon { font-size: 14px; line-height: 1; }

/* 主区：占满剩余空间，承载所有 page */
.app-main {
  flex: 1;
  display: flex;
  overflow: hidden;
  background: var(--c-surface);
  border-radius: var(--r-md);
  box-shadow: 0 4px 20px rgba(20,30,50,.08);
  position: relative;
  z-index: 1;
}
.app-pages {
  flex: 1;
  padding: var(--sp-4);
  overflow: hidden;
  min-height: 0;
}
.page { display: none; height: 100%; }
.page.active { display: grid; gap: var(--sp-4); overflow-y: auto; min-height: 0; }
```

- [ ] **Step 2：修改 `templates/index.html` 顶部 chrome**

定位：当前 `templates/index.html` 行 18-35 是：

```html
<body>
<div class="app-header"><button class="btn-mini" id="hamb">☰</button><div class="app-header__title">A端 - 双端处理</div><span class="badge badge-idle" id="badge">空闲</span></div>
<div class="app-layout">
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
  <div class="app-main">
```

替换为：

```html
<body>
<div class="app-layout">
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
    <span style="flex:1"></span>
    <span class="badge badge-idle" id="badge" style="margin-bottom: 14px; align-self: flex-end;">空闲</span>
  </div>
  <div class="app-main">
```

**变更要点：**
- 删除整个 `.app-header` div（含汉堡按钮、标题、badge）
- 把 badge 移到 tabs 行右侧（仍能用作状态指示）
- 删除汉堡按钮（filing 风格不需要折叠侧栏，因为没侧栏了）
- `static/js/index.js:47` 行有 `$("#hamb").onclick = () => $("#nav").classList.toggle("hide");` — 这行会因 `#hamb` 不存在而 throw。需要在 JS 中**注释掉这行**

- [ ] **Step 3：注释掉 `static/js/index.js:47` 的 `$("#hamb").onclick`**

定位：`static/js/index.js` 第 47 行。注释掉整行：

```js
// $("#hamb").onclick = () => $("#nav").classList.toggle("hide");  // 删除：filing 主题已移除侧栏汉堡按钮
```

- [ ] **Step 4：浏览器验证**

```bash
python server.py
```

- [ ] 顶部出现 4 个折角 tab，主页 tab 默认选中（前突 + 颜色与卡片一致）
- [ ] 点其他 tab 可切换，活动 tab 视觉与卡片"焊接"
- [ ] Console 无报错（特别注意 `#hamb` 不再访问）
- [ ] badge 显示"空闲"，位置在 tabs 行右侧（可能不完美，下一步微调）

- [ ] **Step 5：Commit**

```bash
git add static/css/layout.css templates/index.html static/js/index.js
git commit -m "refactor(theme): 顶部 chrome 改为 Filing Cabinet 折角 tab，移除侧栏与汉堡按钮"
```

---

## Task 3: components.css 局部修复（panel 边框、按钮在浅底下的可读性）

**Files:**
- Modify: `static/css/components.css`

**说明：** 暗主题下 `.panel` / `.btn` / `.drop` 等组件大量假设深底 + 浅文字。换浅底后大部分能跟着 token 走，但少数硬编码会出问题。本 task **不重写 components.css**，只查找硬编码并修。

- [ ] **Step 1：定位硬编码的颜色值（grep）**

```bash
grep -nE "#(fff|FFF|ffffff|FFFFFF|000|000000|1e1e|1f1|0a0a|fafa|f5f5)" static/css/components.css
```

如果列出来的硬编码：
- 是按钮文字（如 `color: #fff`）→ 用 token 替换为 `color: var(--c-surface)` 或 `color: #fff` 看场景
- 是阴影颜色（如 `rgba(0,0,0,.x)`）→ 通常不动，浅底也适用
- 是边框（`border-color: #...`）→ 替换为 `var(--c-border)`

让 implementer 自行判断哪些需要改。**重点检查这几类：**
- 主按钮的背景 / 文字色（确保 accent 改成黑墨后按钮仍可见）
- 输入框背景（暗主题假设深，浅主题需要白或更浅暖灰）
- panel header 与 body 的色差是否还能区分

- [ ] **Step 2：浏览器全 4 页快速过一遍，记录视觉问题**

```bash
python server.py
```

打开每个 tab，随便点几下，记录"看不见"或"明显错位"的元素。**只修危及可用性的**（如按钮文字看不见、输入框看不见输入），不修美观问题。

- [ ] **Step 3（如有改动）：Commit**

```bash
git add static/css/components.css
git commit -m "fix(theme): 浅底下组件硬编码颜色调整（仅可用性修复）"
```

如果没改动，跳过 commit。

---

## Task 4: 视觉验证 + 截图（用户确认）

**Files:** 无修改。

- [ ] **Step 1：完整跑一次浏览器**

```bash
python server.py
```

打开主页、查重、采购、考勤 4 个 tab，分别截图保存到桌面：
- `theme_main.png`
- `theme_dup.png`
- `theme_purchase.png`
- `theme_attendance.png`

- [ ] **Step 2：等用户人工确认**

询问用户：
- 整体观感是否符合 filing cabinet mockup
- 折角 tab 是否到位
- 哪些过渡态丑得不能忍（决定下一轮是否继续投入）
- 决定 keep / rollback / 部分调整后 keep

- [ ] **Step 3：清理截图**

```bash
rm /c/Users/jxwu2002/Desktop/theme_*.png
```

- [ ] **Step 4：跑全测试**

```bash
python -m pytest tests/ -q
```

预期：全过（零 Python 改动）。

---

## 完成判据

4 个 Task 完成、`pytest` 全过、用户决定 keep。如果 rollback：

```bash
git checkout main
git branch -D refactor/filing-cabinet-theme
```

