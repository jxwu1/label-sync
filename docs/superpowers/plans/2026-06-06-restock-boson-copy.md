# 补货页 → boson 一键复制 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在补货页内就地编辑 p98 推荐量并一键复制 `型号,数量`（boson 导入格式）到剪贴板，消除「下载 CSV→Excel 改数量→找列复制」的手工摩擦。

**Architecture:** 纯前端。`restock.js` 加取数 helper + 纯拼接函数 + 复制逻辑；p98 列从 `<span>` 改为内联数字输入框（编辑值存 `state.editedQty`，不持久化）；`components.css` 加输入框样式；`_page_restock.html` 加两个复制按钮。零后端/DB/迁移。

**Tech Stack:** Vanilla JS（Alpine 页面壳，restock 表格是手写 render）、Tailwind v4 + 自定义 `components.css`、Flask 模板 partial。

**测试策略:** 项目无 JS 单测框架，验证分两层——(a) 纯函数 `buildBosonText` 用浏览器 DevTools console 断言（可执行）；(b) 交互行为本地 `python server.py` 浏览器人工走查。后端不变，最后跑 `pytest tests/` 确认无回归。

**spec:** `docs/superpowers/specs/2026-06-06-restock-to-boson-copy-design.md`

---

## 文件结构

| 文件 | 改动 |
|---|---|
| `static/js/restock.js` | 加 `pickQty`/`getBosonQty`/`buildBosonText`/`copyBosonText`/`copyBosonSelected`/`copyBosonVisible`；`state` 加 `editedQty`；`renderRow` p98 单元格改 input；render 绑定区加 input 事件；init 区加按钮绑定 |
| `templates/partials/_page_restock.html` | 批量栏加「⧉ 复制 boson」按钮；更多菜单加「⧉ 复制 boson (可见)」项 |
| `static/css/components.css` | 加 `.rs-qty-input` 内联编辑样式 |

---

## Task 1: 取数 helper + boson 拼接纯函数

**Files:**
- Modify: `static/js/restock.js`（在 `CSV_COLS` 定义之后，约 `restock.js:539` 之后插入）

- [ ] **Step 1: 加 `pickQty` / `getBosonQty` / `buildBosonText`**

在 `restock.js` 的 `_downloadRestockCsv` 函数之前（约第 540 行，`CSV_COLS` 数组之后）插入：

```javascript
// 取某行当前补货数量: 用户编辑值优先, 否则 p98 推荐量. 纯函数 (editedQty 显式传入).
function pickQty(it, editedQty) {
  const e = editedQty[it.barcode];
  return e !== undefined ? e : it.restock_qty_p98;
}

// input 初值 / 单行展示用: 读全局 state.editedQty.
function getBosonQty(it) {
  return pickQty(it, state.editedQty);
}

// 行集 → boson 导入文本: 多行 "型号,数量". 跳过型号缺失 / 数量非数字 / 数量<=0.
// 纯函数 (editedQty 显式传入), 返回 {text, kept, skipped}.
function buildBosonText(items, editedQty) {
  const lines = [];
  let skipped = 0;
  for (const it of items) {
    const model = it.model;
    const raw = pickQty(it, editedQty);
    const num = Number(raw);
    if (!model || !Number.isFinite(num)) { skipped++; continue; }
    const qty = Math.round(num);
    if (qty <= 0) { skipped++; continue; }
    lines.push(`${model},${qty}`);
  }
  return { text: lines.join("\n"), kept: lines.length, skipped };
}
```

- [ ] **Step 2: 浏览器 console 验证纯函数**

`python server.py` → 打开补货页（无需加载数据）→ DevTools console 执行：

```javascript
buildBosonText(
  [
    { barcode: "a", model: "AB12", restock_qty_p98: 3.6 },   // 保留 → AB12,4 (round)
    { barcode: "b", model: "",     restock_qty_p98: 5 },     // 跳过: 型号空
    { barcode: "c", model: "CD34", restock_qty_p98: 0 },     // 跳过: qty<=0
    { barcode: "d", model: "EF56", restock_qty_p98: null },  // 跳过: Number(null)=0 → <=0
    { barcode: "e", model: "GH78", restock_qty_p98: 12 },    // 保留 → GH78,12
  ],
  { a: "7" }   // 编辑值覆盖: a 用 7 而非 3.6 → AB12,7
)
```

Expected: `{ text: "AB12,7\nGH78,12", kept: 2, skipped: 3 }`

- [ ] **Step 3: Commit**

```bash
git add static/js/restock.js
git commit -m "feat(restock): boson 拼接纯函数 + 取数 helper (pickQty/getBosonQty/buildBosonText)"
```

---

## Task 2: p98 列改为内联输入框 + editedQty 状态

**Files:**
- Modify: `static/js/restock.js`（`state` 字面量约 `:48`；`renderRow` 约 `:394`；render 绑定区约 `:961`）

- [ ] **Step 1: `state` 加 `editedQty`**

找到 `state` 对象字面量（含 `expandedBarcode: null`，约 `restock.js:48`），在其中新增一行（与 `expandedBarcode` 同级）：

```javascript
  editedQty: {},   // barcode -> 用户改后的 p98 数量(字符串); 不持久化, 刷新清空
```

- [ ] **Step 2: `renderRow` p98 单元格改 input**

把 `renderRow` 里这一行（`restock.js:394`）：

```javascript
      <td class="rs-num rs-rec-g" title="安全量"><span class="rs-rec-v">${it.restock_qty_p98 != null ? it.restock_qty_p98 : '—'}</span></td>
```

替换为：

```javascript
      <td class="rs-num rs-rec-g" title="安全量"><input type="number" inputmode="numeric" class="rs-qty-input" data-bc="${escapeHtml(it.barcode)}" value="${escapeHtml(getBosonQty(it))}"></td>
```

（`escapeHtml` 在 `restock.js:89` 已对 null/undefined 返回 `""`，故 p98 为 null 的行 input 显示空，安全。）

- [ ] **Step 3: render 绑定区加 input 事件**

在 `render()` 的事件绑定区，行点击委托之前（`restock.js:953` 那段 `// 行其他位置点击` 之前）插入：

```javascript
    // p98 数量输入: 改值只写 state, 不重绘(避免失焦); click 阻断冒泡防触发 row→drawer.
    for (const inp of tbody.querySelectorAll(".rs-qty-input")) {
      inp.addEventListener("input", () => {
        state.editedQty[inp.dataset.bc] = inp.value;
      });
      inp.addEventListener("click", (e) => e.stopPropagation());
    }
```

- [ ] **Step 4: 本地浏览器验证编辑 + render 保留**

`python server.py` → 补货页「刷新」加载数据：

1. p98 列显示为可编辑输入框，默认值 = 原 p98 推荐量。
2. 改某行数量（如改成 99）→ 焦点移出，不展开 drawer、不整表重绘。
3. **关键回归点（用户要求）**：改完数量后点表头「p50/紧迫分」排序，或切「紧急 ≥70」band 筛选 → 触发 render → 该行输入框仍显示刚才改的 99（因 `getBosonQty` 从 `state.editedQty` 读回）。
4. 刷新整个页面（F5）→ editedQty 清空，p98 回到原推荐值。

- [ ] **Step 5: Commit**

```bash
git add static/js/restock.js
git commit -m "feat(restock): p98 列改内联输入框 + editedQty 状态(不持久化)"
```

---

## Task 3: 输入框样式（components.css）

**Files:**
- Modify: `static/css/components.css`（`.rs-rec-v--hi` 之后，约 `:2069`）

- [ ] **Step 1: 加 `.rs-qty-input` 样式**

在 `components.css:2069`（`.rs-rec-v--hi { color: var(--accent); }`）之后插入：

```css
/* p98 列内联数量编辑框: 融入表格(透明/右对齐/无 spinner) */
.rs-qty-input {
  width: 58px;
  font-family: var(--mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--accent);
  text-align: right;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 3px;
  padding: 1px 4px;
  -moz-appearance: textfield;
}
.rs-qty-input:hover { border-color: var(--line-soft); }
.rs-qty-input:focus { outline: none; border-color: var(--accent); background: var(--bg-1); }
.rs-qty-input::-webkit-outer-spin-button,
.rs-qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
```

- [ ] **Step 2: 本地浏览器验证样式**

刷新补货页 → p98 输入框：右对齐、与同列 `.rs-num` 对齐；无上下数字 spinner 箭头；hover 出细边框、focus 出 accent 边框；不破坏 rs-table 行高。

- [ ] **Step 3: Commit**

```bash
git add static/css/components.css
git commit -m "style(restock): p98 内联输入框样式(透明/右对齐/去 spinner)"
```

---

## Task 4: 复制按钮（模板 + 逻辑 + 绑定）

**Files:**
- Modify: `templates/partials/_page_restock.html`（批量栏 `:96`；更多菜单 `:19`）
- Modify: `static/js/restock.js`（复制逻辑加在 `exportVisibleCsv` 之后约 `:581`；绑定加在 init 区 `:1056` / `:1074`）

- [ ] **Step 1: 模板加两个按钮**

批量栏：在 `_page_restock.html:96`（`<button ... id="rsBtnExport" ...>⇣ 导出选中</button>`）之后插入：

```html
            <button class="btn btn--ghost" id="rsBtnCopyBoson" type="button">⧉ 复制 boson</button>
```

更多菜单：在 `_page_restock.html:19`（`<button ... id="rsMenuExport" ...>⇣ 导出 CSV (可见)</button>`）之后插入：

```html
                <button class="act-more-item" id="rsMenuCopyBoson" type="button">⧉ 复制 boson (可见)</button>
```

- [ ] **Step 2: 加复制逻辑**

在 `restock.js` 的 `exportVisibleCsv` 函数之后（约 `:581`）插入：

```javascript
// 复制 boson 格式到剪贴板: 主路径 navigator.clipboard, 失败回退 textarea+execCommand.
async function copyBosonText(items) {
  const { text, kept, skipped } = buildBosonText(items, state.editedQty);
  if (kept === 0) {
    alert("没有可复制的行" + (skipped ? `（${skipped} 行因型号缺失或数量无效跳过）` : ""));
    return;
  }
  const msg = `已复制 ${kept} 行` + (skipped ? `，${skipped} 行因型号缺失或数量无效跳过` : "");
  try {
    await navigator.clipboard.writeText(text);
    alert(msg);
  } catch (_e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_e2) { ok = false; }
    document.body.removeChild(ta);
    alert(ok ? msg : "浏览器未允许自动复制，请重试或手动复制");
  }
}

// 批量栏「复制 boson」: 勾选行 (按紧迫分降序, 与导出选中一致).
function copyBosonSelected() {
  if (state.selected.size === 0) { alert("请先勾选要复制的行"); return; }
  const sel = state.items
    .filter((it) => state.selected.has(it.barcode))
    .sort((a, b) => (b.urgency_score || 0) - (a.urgency_score || 0));
  copyBosonText(sel);
}

// 更多菜单「复制 boson (可见)」: 当前过滤+排序后可见行 (上限 500, 与导出可见一致).
function copyBosonVisible() {
  const visible = applySort(applyFilter(state.items)).slice(0, 500);
  if (visible.length === 0) { alert("当前筛选范围内没有可复制的行"); return; }
  copyBosonText(visible);
}
```

- [ ] **Step 3: init 区加按钮绑定**

在 `restock.js:1056`（`$("rsBtnExport").addEventListener("click", exportSelectedCsv);`）之后插入：

```javascript
  $("rsBtnCopyBoson")?.addEventListener("click", copyBosonSelected);
```

在 `restock.js:1074`（`$("rsMenuExport")?.addEventListener(...)`）之后插入：

```javascript
  $("rsMenuCopyBoson")?.addEventListener("click", () => { actMore?.classList.remove("open"); copyBosonVisible(); });
```

- [ ] **Step 4: 本地浏览器端到端验证**

`python server.py` → 补货页「刷新」：

1. 改几行数量（含一行清空、一行填 `0`、一行填 `3.6`）。
2. 勾选若干行（含上面改过的）→ 批量栏点「⧉ 复制 boson」→ 粘到记事本：多行 `型号,数量`；改过的行用编辑值；清空/0 的行不在；3.6 → 4；alert 报「已复制 N 行，M 行…跳过」。
3. 不勾选 → 「⋯ 更多」→「⧉ 复制 boson (可见)」→ 作用于可见行，菜单自动收起。
4. 一行都没有可复制（如清空全部勾选行的数量）→ alert「没有可复制的行（…跳过）」，不写剪贴板。

- [ ] **Step 5: Commit**

```bash
git add static/js/restock.js templates/partials/_page_restock.html
git commit -m "feat(restock): 复制 boson 格式按钮(选中/可见) + clipboard 兜底"
```

---

## Task 5: 全量验收 + 回归

**Files:** 无新增改动，走查 spec 验收清单 + 后端回归。

- [ ] **Step 1: 对照 spec 验收清单逐条走查**

打开 `docs/superpowers/specs/2026-06-06-restock-to-boson-copy-design.md` 的「验收标准」，逐条在浏览器确认全部勾选通过（含 render 保留、输入框样式融合、clipboard 兜底）。

- [ ] **Step 2: 后端回归（确认纯前端改动没碰坏后端）**

Run: `pytest tests/ -q`
Expected: 全量通过（数量与改动前一致，不应受前端改动影响）。

- [ ] **Step 3: 确认改动面**

Run: `git diff --stat main...feat/restock-boson-copy`
Expected: 仅 `static/js/restock.js`、`templates/partials/_page_restock.html`、`static/css/components.css`（+ docs/specs、docs/plans）。无后端/models/alembic 文件。

- [ ] **Step 4: 收尾**

实现完成后走 `superpowers:finishing-a-development-branch` 决定合并方式（按用户 git 规范：feat 分支 → squash merge 回 main）。

---

## Self-Review（plan 作者自检）

- **Spec coverage:** 组件1(p98 input)→Task2+3；组件2(两按钮)→Task4；buildBosonText 契约→Task1；错误/边界(空集/跳过/clipboard 兜底)→Task1+4；render 保留验证→Task2 Step4 + Task5；范围(三文件)→各 Task + Task5 Step3。全覆盖。
- **Placeholder scan:** 无 TBD/TODO，所有代码步骤含完整代码。
- **Type consistency:** `pickQty(it, editedQty)` / `getBosonQty(it)` / `buildBosonText(items, editedQty)→{text,kept,skipped}` / `copyBosonText(items)` / `copyBosonSelected()` / `copyBosonVisible()` 跨任务命名一致；`state.editedQty`、`.rs-qty-input`、`#rsBtnCopyBoson`、`#rsMenuCopyBoson` 在定义与引用处一致。
