# 前端重构（A 端 · 视觉与布局）— 设计文档

**Date:** 2026-04-27
**Scope:** A 端 (`templates/index.html` + 4 子页) 视觉与布局重构。功能逻辑零改动。B 端后续复用同一套设计语言（不在本 spec 范围）。

## 1. 目标与非目标

**目标**

- 把现有"被压成 1 行的 CSS + 散落 inline style + 短类名（`.u/.r/.bc`）"的前端，重构成可读、可维护、可扩展的 CSS 体系。
- 视觉上演进当前深色主题（`#0f1117` 系），统一间距 / 圆角 / 字号 / 配色，提升层级感与呼吸感。
- 标签处理主页结构性重排，提高主任务可见性、降低视觉拥挤。
- 留下 design token，B 端下次重构直接复用。

**非目标**

- 不引入构建工具（无 npm / vite / postcss），保持纯 Flask + 静态资源。
- 不引入框架（无 React / Vue）。
- 不改后端、不改路由、不改任何 JS 业务逻辑。
- 不重排"重复检查 / 采购订单 / 考勤"三页的 DOM 结构（仅换皮）。
- 不动 B 端 (`admin.html` / `admin.css`)。

## 2. 关键决策（已与用户确认）

| # | 决策 | 选择 |
|---|---|---|
| 1 | 范围 | A 端先做，B 端后续复用同套 token |
| 2 | 视觉方向 | 现代深色 Dashboard（演进当前 `#0f1117` 风格） |
| 3 | 重构深度 | T3：标签处理主页结构重排；其他 3 页 T2 仅换皮 |
| 4 | 构建工具 | 不引入，原生 CSS 变量做 token |
| 5 | 类名 | 短类名（`.u/.r/.c/.bc/.bd/...`）重命名为语义化（`.btn-secondary/.btn-primary/...`） |
| 6 | inline style | 全量清理（`index.html` 15 处、`index.js` 12、`index-warnings.js` 10、`attendance.js` 12、`purchase.js` 3） |

## 3. 设计 Token

集中在 `static/css/tokens.css`，CSS 自定义属性挂在 `:root`：

```css
:root {
  /* 颜色 — 表面 */
  --c-bg: #0f1117;
  --c-surface: #161a25;        /* panel 背景 */
  --c-surface-elev: #1a1d27;   /* header / 浮层 */
  --c-surface-deep: #13151f;   /* nav / 输入框 */
  --c-border: #232838;
  --c-border-subtle: #1f2433;

  /* 颜色 — 文字 */
  --c-text: #e2e8f0;
  --c-text-muted: #94a3b8;
  --c-text-dim: #64748b;
  --c-text-faint: #4a5568;

  /* 颜色 — 强调 */
  --c-accent: #4f46e5;          /* 主操作 */
  --c-accent-hover: #4338ca;
  --c-accent-soft: #1e1b4b;
  --c-accent-fg: #818cf8;

  --c-info: #60a5fa;
  --c-success: #4ade80;
  --c-warn: #fbbf24;
  --c-warn-strong: #fb923c;
  --c-danger: #f87171;

  /* 间距 */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px;
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

## 4. CSS 文件结构

替换现有"`index.css` 1 行 + `purchase.css` 53 + `attendance.css` 26"的散乱结构：

```
static/css/
├── tokens.css        # :root 变量
├── base.css          # reset + body + 通用排版
├── components.css    # .btn / .panel / .badge / .drop / .tabs / .form-input ...
├── layout.css        # .header / .nav / .layout / .pages 主框架
├── page-main.css     # 标签处理页（T3 重排）
├── page-dup.css      # 重复检查页（T2 换皮）
├── page-purchase.css # 采购订单页（T2 换皮，原 purchase.css 重写）
├── page-attendance.css # 考勤页（T2 换皮，原 attendance.css 重写）
└── widgets/
    ├── terminal-log.css   # 浮动终端日志抽屉
    └── transfer-drawer.css # 文件互传抽屉
```

`templates/index.html` 的 `<link>` 顺序：tokens → base → components → layout → page-* → widgets。

## 5. 类名重命名映射

| 旧 | 新 | 说明 |
|---|---|---|
| `.u` | `.btn-secondary` | 灰按钮（上传） |
| `.r` | `.btn-primary` | 主按钮（开始处理） |
| `.c` | `.btn-warning` | 橙按钮（继续） |
| `.d` | `.btn-success` | 绿按钮（下载） |
| `.m` | `.btn-info` | 青按钮（复制） |
| `.x` | `.btn-ghost` | 透明按钮（清空） |
| `.bc` | `.btn-s.is-warn` | 小按钮 + 警示色变体 |
| `.bd` | `.btn-s.is-danger` |  |
| `.bi` | `.btn-s.is-ghost` |  |
| `.bf` | `.btn-s.is-warn-solid` |  |
| `.bg` | `.btn-s.is-success` |  |
| `.cx` | `.btn-s.is-ghost-strong` |  |
| `.tt` | `.section-label` |  |
| `.tf` | `.transfer-file` |  |
| `.mi` | `.message` |  |
| `.tbod` / `.term` / `.th` / `.ttl` | `.terminal-log__body / .terminal-log / .terminal-log__head / .terminal-log__title` | 终端日志组件采用 BEM |

短类名仅在内部组件保留（`.row / .col / .code / .loc / .sub` 等已经是语义清楚的）。

## 6. 标签处理主页布局重排（T3）

### 6.1 整体结构

```
┌─ header (52px) ──────────────────────────────────────────────┐
├─ nav (56px, 图标+短文字) ─┬─ 主区 ─────────────────────────┤
│ 📋 标签                  │  ┌─ 顶部 action bar ──────────┐│
│ 🔍 查重                  │  │ [拖入区]            [开始]│ │
│ 📦 采购                  │  └────────────────────────────┘│
│ 🕐 考勤                  │  ┌─ 异常处理 ──┐ ┌─ Stockpile ┐│
│                          │  │ (主区, 撑满) │ │ (tabs) ──── ││
│                          │  │              │ │ 状态/初始化/││
│                          │  │              │ │ 比对/搜索  ││
│                          │  └──────────────┘ └────────────┘│
└─────────────────────────┴────────────────────────────────────┘
                                                  📨 互传 ●
                                                  ▸ 日志 (12)
```

### 6.2 关键变化

1. **侧导航瘦身**：`170px → 56px`，图标 + 2 字。`.nav.hide` 仍可全收。
2. **顶部 action bar**：`drop` 区 + 主操作按钮（开始处理）从原右栏抬到主区顶部，水平排布。
3. **异常处理**占主区主格 `1fr`，垂直撑满（不再被 200px 终端日志切走下半）。
4. **Stockpile 4 子块 → tab 面板**（状态 / 初始化 / 月度比对 / 搜索）：
   - tab 切换在 `static/js/index-stockpile.js` 局部状态管理（不影响 stockpile 后端 API）。
   - DOM 一次渲染所有 tab 面板，CSS `display:none` 切换，避免重新绑定事件。
5. **终端日志 → 浮动 FAB + 抽屉**：
   - 默认右下胶囊按钮 `▸ 日志 (N)`。
   - 点击展开 `.terminal-log` 浮层（CSS 已有 `.term` 浮动容器，复用并改造）。
   - `clearLog()` API 不变，只重写宿主容器。
6. **文件互传 → 右上 FAB + 滑出抽屉**：
   - 原 300px 常驻侧栏 → 右上胶囊 `📨 文件互传 · B 端 ●`（红点表示新文件 / 新消息）。
   - 点击右滑抽屉，内容（文件 drop / 列表 / 文字 textarea / 消息列表）原封搬入抽屉。
   - 移动断点 `@media (max-width:1100px)` 下原本就 `display:none`，逻辑一致。

### 6.3 受影响 JS 文件

- `static/js/index.js`：`switchPage` 不变；新增"日志抽屉开关""互传抽屉开关"两个 toggle。
- `static/js/index-warnings.js`：clean inline style → 类名。
- `static/js/transfer.js` / `messaging.js`：DOM 选择器不变，仅宿主容器的父级从 `.transfer` 改为 `.transfer-drawer__body`，selector 仍用现有 id。
- `static/js/index-stockpile.js`（新文件，从 `index.js` 中拆出 stockpile 相关代码 + 加 tab 切换）。**注意：本 spec 主要是视觉重构，stockpile 拆文件属于顺手清理；如果不希望动 JS 模块边界，可保留在 `index.js`。** → **决策：拆出**（文件已大，长期维护更清楚）。

### 6.4 不变项

- 所有 fetch endpoint、所有事件名、所有 polling 逻辑、`waitMsg / renderReview / handleStatus`：零改动。
- 所有 `id="..."` 保留（`#warnBox`、`#tbod`、`#drop`、`#fileInput`、`#upload`、`#run`、`#cont`、`#download`、`#copyModels`、`#reset`、`#status`、`#spStatus`、`#spInitDrop` ...）。
- `window.switchPage / window.clearLog / window.rmFile` 等全局函数保留。

## 7. 其他 3 页处理（T2）

### 7.1 重复检查（`#pageDup`）

- HTML 已写在 `index.html`，DOM 不变。
- CSS 重写 `page-dup.css`：`.dup-top` / `.dup-res` / `.sum` / 表格风格改用 token。

### 7.2 采购订单（`#pagePurchase`，DOM 由 `purchase.js` 渲染）

- `purchase.css` 53 行重写为 `page-purchase.css`，使用 token。
- `purchase.js` 内部 3 处 inline style 清理为类名。
- 不重排页面骨架。

### 7.3 考勤（`#pageAttendance`，DOM 由 `attendance.js` 渲染）

- `attendance.css` 26 行重写为 `page-attendance.css`，使用 token。
- `attendance.js` 内部 12 处 inline style 清理为类名。
- 不重排页面骨架。

## 8. 实施顺序与里程碑

可按下面顺序拆 PR / 拆 commit，每一步都能独立运行：

1. **M1 / 设计 token + 基础**：新增 `tokens.css / base.css`，引入 `index.html`。验收：页面外观无明显变化（token 与现有取值一致），但 CSS 已模块化。
2. **M2 / 类名重命名 + components.css**：把 `.btn` 体系、`.panel`、`.badge`、`.drop` 抽出为语义类。验收：所有按钮 / 面板视觉与现状一致。
3. **M3 / layout.css + 侧导航瘦身 + 顶部 action bar**：主框架层重排。验收：4 个子页都能正常切换，标签处理顶部出现 action bar。
4. **M4 / Stockpile tab 化 + index-stockpile.js 拆出**。验收：状态 / 初始化 / 比对 / 搜索 4 个 tab 切换正常。
5. **M5 / 终端日志浮动 FAB + 抽屉**。验收：日志可展开 / 收起，`clearLog` 仍可用。
6. **M6 / 文件互传抽屉**。验收：上传、列表、消息发送、删除、复制全部仍工作。
7. **M7 / inline style 清零**：扫 `index.html` + 4 个 JS 文件，剩余 `style="..."` 应为 0（用 grep 验证）。
8. **M8 / 其他 3 页换皮**：`page-dup.css / page-purchase.css / page-attendance.css` 全部用 token。验收：4 页视觉统一，行为不变。
9. **M9 / 清理与压缩**：删除旧 `index.css / purchase.css / attendance.css` 中已被替换的内容；旧 1 行 CSS 删除。

每个里程碑独立合入 main 都安全（未完成的步骤暂保留旧样式回退）。

## 9. 验收（verify）

每个里程碑执行：

- 启动 Flask，浏览器手动跑：标签处理 → 上传 → 开始处理 → 异常面板 → 复制型号 → 下载 → reset，全程无 JS 错误。
- 重复检查页 → 上传 csv → 看结果。
- 采购订单页 → 渲染正常。
- 考勤页 → 渲染正常。
- 文件互传：发送文件 / 文字消息到 B 端，B 端可见。
- 终端日志：扫描过程中日志正常追加，clear 可用。
- `grep -rn 'style="' templates/ static/js/ | wc -l` 在 M7 后应为 0。
- 既有 pytest 套件全部通过（前端重构不影响后端 API，但要确认）。

## 10. 风险与回退

- **风险 1：DOM 重排破坏事件绑定**。缓解：所有 `id` 保留；selector 主要用 `#id` 而非层级选择器，移动宿主容器不会失效。
- **风险 2：终端日志由"固定面板"变"浮动抽屉"后，扫描时看不到日志，操作员困惑**。缓解：默认有 unread badge，新日志推上去时 FAB 闪一下；保留"展开"为默认状态的选项（可由 localStorage 记忆）。
- **风险 3：B 端没动，A/B 设计语言不一致一段时间**。可接受：B 端后续重构会使用同一份 `tokens.css`，这是预期。
- **回退**：每个 M 步骤独立 commit，发现问题可 `git revert` 单步而不影响整体。

## 11. 分支命名

`refactor/frontend-a-redesign`（主分支）。如果按里程碑拆 PR，可用 `refactor/frontend-a-m1-tokens` 之类的子分支。
