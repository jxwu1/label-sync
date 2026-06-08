# 补货页 → boson 一键复制（型号,数量）

**日期:** 2026-06-06
**分支:** `feat/restock-boson-copy`
**状态:** 设计已批准，待写实施计划
**来源:** Codex 审查 backlog 第 2 期「补货→采购衔接」断线（见 memory `project_codex_review_backlog`）

## 背景

第 2 期盘点结论：补货推荐与采购流程之间存在「手工 CSV 中转」断线。但澄清后发现真实工作流比想象简单——**最终采购订单是在外部 boson ERP 里下的，不在 label-sync 内**。

操作员当前的真实操作链：

1. 补货页「导出 CSV」（17 列宽表 + 一列 `ERP导入 (型号,数量)`）
2. 打开下载的文件，**逐行看 + 手改数量**（筛除一批、个别调整）
3. **复制「型号,数量」那一列**
4. 粘贴进 boson 的输入框/表格下采购单

痛点是第 2~3 步的摩擦：下载文件 → 开 Excel → 在 17 列里找到那一列 → 改数量 → 复制单列。

boson 侧约束（操作员确认）：导入必须是 `型号,数量` 这种格式，**粘贴进输入框**接收（不是上传文件）。

## 目标

把「下载 → Excel 改数量 → 复制单列」压缩到补货页内一站完成：**页面里就地改数量 → 一键复制 boson 格式到剪贴板 → 直接粘进 boson**。

## 非目标（YAGNI）

- 不在 label-sync 内建采购单（PurchaseOrder）—— 采购单在 boson 下。
- 不持久化编辑后的数量（刷新即重置回推荐值）。
- 不下载文件（boson 走粘贴，剪贴板足够）。
- 不记录补货决策（复制 ≠ 下单决策；现有「标已下单」另走）。
- 不做 drawer 单条复制（操作是批量的，单条价值低）。
- 不新增 toast 组件（沿用现有 `alert`，避免扩大 CSS/DOM 范围）。

## 范围

**纯前端改动**，三个文件：

- `static/js/restock.js`
- `templates/partials/_page_restock.html`
- `static/css/components.css`（p98 列内联输入框样式，见组件 1）

零后端、零数据库、零 Alembic 迁移、零部署风险。

## 设计

### 组件 1：p98 列就地可编辑

- `renderRow()`（`restock.js:394`）的 p98 单元格从 `<span>` 改为数字输入框：
  ```html
  <input type="number" inputmode="numeric" class="rs-qty-input"
         data-bc="${escapeHtml(it.barcode)}"
         value="${escapeHtml(getBosonQty(it))}">
  ```
  - `data-bc` 与 `value` 都经 `escapeHtml`，与文件现有模板风格一致（即便 qty 是数字也保持统一）。
- 新增前端状态 `state.editedQty: {}`（`barcode → 用户改后的数量字符串`）。
- 新增 helper `getBosonQty(it)`：返回 `state.editedQty[it.barcode] ?? it.restock_qty_p98`，供 input 的初始 `value` 和复制逻辑共用。
- 输入事件用 `oninput`（事件委托，挂在 tbody 上按 `.rs-qty-input` 命中）**只写 `state.editedQty`，不触发整表 render**，避免重绘导致输入框失焦/光标跳动。
- **不持久化**：`editedQty` 不进 localStorage，刷新页面后清空，p98 列回到原始推荐值。
- 排序不受影响：表头 `data-sort="restock_qty_p98"` 仍按原始 `it.restock_qty_p98` 排序，编辑值不参与排序。
- **CSS（`components.css`，rs-table 段 ~2068 行附近）**：`<input type=number>` 浏览器默认样式（边框/padding/撑满宽度/spinner 箭头/左对齐）在窄表格列里会错位难看，需加 `.rs-qty-input` 内联编辑样式——透明/无边框（focus 时给细边框或底色提示）、右对齐对齐同列 `.rs-num`、限定宽度（约 56–64px）、`::-webkit-inner-spin-button { display:none }` + `-moz-appearance:textfield` 去掉数字 spinner。复用现有 `--mono` / `--accent` 等变量。

### 组件 2：「复制 boson 格式」按钮 ×2

- **批量栏**（选中行时浮现，`_page_restock.html:96` 区域）新增按钮：`⧉ 复制 boson` —— 作用于勾选的行。
- **更多菜单**（`_page_restock.html:17-19`）新增项：`⧉ 复制 boson (可见)` —— 作用于当前过滤+排序后的可见行（上限 500，与现有「导出 CSV (可见)」一致）。
- 范围语义与现有两个导出按钮完全对应（选中 / 可见）。

### 纯函数契约：`buildBosonText(items, editedQty)`

把拼接 + 过滤逻辑抽成一个独立纯函数，便于肉眼审与将来加测试。

**输入：** `items`（行对象数组）、`editedQty`（barcode→值的 map）

**每行处理：**
1. 型号：**只取 `it.model`**（不是 `name_zh || model`——boson 要的是型号）。
2. 数量：`raw = getBosonQty(it)`（与 input 初值同一真源，内部即 `editedQty[it.barcode] ?? it.restock_qty_p98`），然后 `qty = Math.round(Number(raw))`。
3. 跳过该行的条件（满足任一）：
   - `!it.model`（型号缺失）
   - `!Number.isFinite(Number(raw))`（数量非数字/空）
   - `qty <= 0`
4. 保留行输出一行字符串：`` `${it.model},${qty}` ``（半角逗号）。

**输出：** `{ text, kept, skipped }`
- `text`：保留行用 `\n` 连接（无表头）。
- `kept` / `skipped`：计数，供 alert 文案用。

> 数量取整用 `Math.round`（非 `trunc`）：p98 是推荐补货量，出现小数时按最接近整数更合理。

### 数据流

```
补货推荐(restock_qty_p98)
  → 预填 input(getBosonQty)
  → [操作员逐行手改数量，写 state.editedQty]
  → 点「复制 boson」
  → buildBosonText(行集, editedQty)  // 跳过型号缺失 / 数量≤0或非数字
  → navigator.clipboard.writeText(text)
  → alert("已复制 N 行" + (M>0 ? "，M 行因型号缺失或数量无效跳过" : ""))
  → 操作员粘贴进 boson
```

### 错误 / 边界处理

- **行集为空**：`alert("没有可复制的行")`，不写剪贴板。
- **有行被跳过**：alert 文案带「M 行因型号缺失或数量无效跳过」。
- **clipboard 写入失败**（罕见，非 secure context）：catch 兜底——创建临时 `<textarea>`、填入 text、`select()`，再 `alert("浏览器未允许自动复制，请按 Ctrl+C")`。**不建复杂 modal。** 生产 https + 本地 127.0.0.1 都是 secure context，正常路径用不到。

## 测试 / 验证

- 纯前端，项目无 JS 单测框架 → **以本地人工验证为主**：
  1. `python server.py` 打开补货页。
  2. 改几行数量（含一行清空、一行填 0、一行填小数如 3.6）。
  3. 勾选若干行点「⧉ 复制 boson」→ 粘到记事本核对：格式为多行 `型号,数量`；改过的数量生效；清空/0 的行被跳过；3.6 → 4。
  4. 不勾选，用更多菜单「复制 boson (可见)」→ 核对作用于可见行。
  5. alert 文案的 N / M 计数正确。
- `buildBosonText` 为纯函数，将来若引入 JS 测试设施可直接覆盖（本期不强制）。

## 验收标准

- [ ] 补货页 p98 列为可编辑输入框，默认显示原 p98 推荐量。
- [ ] 改数量不触发整表重绘、不丢焦点；刷新后回到原推荐值。
- [ ] 批量栏「⧉ 复制 boson」复制勾选行；更多菜单「⧉ 复制 boson (可见)」复制可见行。
- [ ] 复制内容为多行 `型号,数量`（半角逗号、无表头），数量取编辑值优先、否则 p98，`Math.round` 取整。
- [ ] 型号缺失 / 数量 ≤0 或非数字的行被跳过，alert 报告复制与跳过行数。
- [ ] clipboard 失败有 textarea + alert 兜底，不新建 modal。
- [ ] p98 输入框样式与表格融合（右对齐、无 spinner、宽度合适），不破坏 rs-table 行高/对齐。
- [ ] 改动仅限 `restock.js` + `_page_restock.html` + `components.css`，无后端/DB/迁移变更。
- [ ] 全量 `pytest tests/` 仍通过（不应受纯前端改动影响）。
