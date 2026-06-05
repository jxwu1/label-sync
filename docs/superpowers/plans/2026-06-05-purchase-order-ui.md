# 采购订单跟踪 UI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在采购页内新增「订单跟踪」面板，让单操作员能看到已下采购单并标到货 / 改下单日期 / 作废。

**Architecture:** 新增独立前端模块 `static/js/purchase_orders.js`（导出 `initPurchaseOrders(container)`），由 `purchase.js` 在 `init()` 末尾调用一次注入到 `pagePurchase` 模板新增的 `<section id="purOrders">`。后端 4 个路由（list/arrival/update/void）已就绪，无改动。状态用白名单映射，所有接口字段经 `shared.js` 的 `esc` 转义。

**Tech Stack:** Vanilla JS（ES module，事件委托）+ 手写 CSS（`components.css`，复用 `.pnl` / `.pnl--clps` 折叠）+ Flask 后端（已存在）。

> **测试说明：** 本仓库无 JS 单测框架，引入它属本任务范围外（YAGNI）。验证方式为**本地浏览器手测 + Playwright 截图**，符合 spec 与用户「前端改动本地测试后再 push」约定。每个 Task 的验证步骤给出明确的预期观察点。

---

## 文件结构

- **Create** `static/js/purchase_orders.js` — 订单跟踪模块。单一职责：拉取订单、渲染表格、行内操作（事件委托）。
- **Modify** `static/js/purchase.js` — 顶部 import；`pagePurchase` 模板加 `<section id="purOrders">`；`init()` 末尾调 `initPurchaseOrders(...)`。
- **Modify** `static/css/components.css` — `#purOrders` 面板布局（`flex-shrink:0` + 内部滚动）、表格、行内 date 编辑器、操作按钮样式。

---

## 准备：本地起服务 + 造一张测试订单

执行任何验证前，先有一张 placed 订单可看（订单平时由 `/purchase/export` 副作用创建；测试时直接 seed 一张省去走 Excel 流程）。

- [ ] **起本地开发服务（热重载）**

Run: `./dev.ps1`（本地 PG + `LABEL_SYNC_DEBUG=1` 热重载；改 JS/CSS 刷新即生效）。浏览器开 `http://127.0.0.1:5000`，进采购页。

- [ ] **确认 create_app 入口路径**

Run: `grep -rn "def create_app" server.py app/`，确认入口（已知在 `server.py` 顶层：`from server import create_app`）。

- [ ] **Seed 一张 placed 订单 + 一张 arrived 订单**

Run（另开终端）：
```powershell
.venv\Scripts\python.exe -c "from server import create_app; from app.models import PurchaseOrder, Supplier, get_session; from sqlalchemy import insert; import contextlib; app=create_app();
with get_session() as s:
    with contextlib.suppress(Exception):
        s.execute(insert(Supplier).values(supplier_id='S-DEMO', supplier_name='演示供应商<b>')); s.commit()
with get_session() as s:
    s.execute(insert(PurchaseOrder).values(supplier_id='S-DEMO', order_date='2026-05-01', status='placed', total_qty=144, total_amount=1240.0, source_file='demo.xlsx'));
    s.execute(insert(PurchaseOrder).values(supplier_id='S-DEMO', order_date='2026-04-20', arrival_date='2026-04-28', status='arrived', total_qty=200, total_amount=3580.0, source_file='demo2.xlsx'));
    s.commit()
print('seeded')"
```
Expected: 打印 `seeded`。（供应商名故意含 `<b>` 以便后面验证转义。）

---

## Task 1: CSS — #purOrders 面板与表格样式

**Files:**
- Modify: `static/css/components.css`（在文件末尾追加，紧邻其它 `#pur*` 规则风格）

- [ ] **Step 1: 追加 #purOrders 样式块**

在 `static/css/components.css` 末尾追加（复用现有 token / `.pnl` / `.pnl--clps` 折叠机制；关键约束 `flex-shrink:0` + 内部 `max-height` 滚动）：

```css
/* ── 采购订单跟踪面板 ───────────────────────────────── */
/* 固定视口布局下不抢 02 解析区弹性空间，内部独立滚动 */
#purOrders.pnl { flex-shrink: 0; }
#purOrders .po-body { max-height: 260px; overflow-y: auto; }
#purOrders .po-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
#purOrders .po-table th,
#purOrders .po-table td { padding: var(--sp-2) var(--sp-3); text-align: left; border-bottom: 1px solid var(--line-soft); white-space: nowrap; }
#purOrders .po-table th { position: sticky; top: 0; background: var(--bg-1); color: var(--ink-3); font-weight: 600; font-size: var(--fs-xs); text-transform: uppercase; z-index: 1; }
#purOrders .po-table td.po-num { text-align: right; font-variant-numeric: tabular-nums; }
#purOrders .po-row--void { opacity: 0.5; }
#purOrders .po-badge { display: inline-block; padding: 1px 8px; border-radius: var(--r-sm); font-size: var(--fs-xs); font-weight: 600; }
#purOrders .po-badge--placed { background: var(--bg-2); color: var(--ink-2); }
#purOrders .po-badge--arrived { background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); }
#purOrders .po-badge--void { background: var(--bg-2); color: var(--ink-3); }
#purOrders .po-badge--unknown { background: var(--bg-2); color: var(--ink-3); }
#purOrders .po-acts { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: nowrap; }
#purOrders .po-btn { cursor: pointer; border: 1px solid var(--line-soft); background: var(--bg-1); color: var(--ink-2); border-radius: var(--r-sm); padding: 2px 8px; font-size: var(--fs-xs); }
#purOrders .po-btn:hover { background: var(--bg-2); }
#purOrders .po-btn--danger:hover { color: var(--error); border-color: var(--error); }
#purOrders .po-date-input { font-size: var(--fs-xs); padding: 1px 4px; }
#purOrders .po-status { font-size: var(--fs-sm); color: var(--ink-2); }
#purOrders .po-status.error { color: var(--error); }
```

- [ ] **Step 2: 提交**

```bash
git add static/css/components.css
git commit -m "feat(purchase-ui): #purOrders 面板与表格样式(flex-shrink + 内部滚动)"
```

> CSS 单独无法在浏览器验证，留到 Task 2 接上模块后一起看。

---

## Task 2: purchase_orders.js 模块（只读列表）+ 接线

**Files:**
- Create: `static/js/purchase_orders.js`
- Modify: `static/js/purchase.js`（import + 模板 section + init 调用）

- [ ] **Step 1: 创建模块（fetch + 渲染 + 白名单 + 转义 + 金额 + 空/错态 + 折叠）**

创建 `static/js/purchase_orders.js`，完整内容：

```javascript
import { esc } from "./shared.js";

// 状态白名单：中文标签 + 允许的操作集。
// 未命中 → 显示转义后的原始 status，不给任何操作（防后端将来加状态时误判）。
const STATUS = {
  placed:  { label: "已下单", badge: "placed",  actions: ["arrival", "edit", "void"] },
  arrived: { label: "已到货", badge: "arrived", actions: ["edit"] },
  void:    { label: "已作废", badge: "void",    actions: [] },
};

const today = () => new Date().toISOString().slice(0, 10);
const fmtMoney = (v) =>
  (v == null ? 0 : Number(v)).toLocaleString("el-GR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

export function initPurchaseOrders(container) {
  if (!container) return;
  // 幂等：清空 + 单一事件委托（不给每行单独绑），重复 init 不累积监听器
  container.innerHTML = "";
  let orders = [];
  let editing = null; // { id, field: 'arrival' | 'order_date' }

  container.className = "pnl pnl--clps";
  container.innerHTML = `
    <div class="pnl-hd">
      <span class="pnl-code">04</span>
      <span class="pnl-title" role="heading" aria-level="2">订单跟踪</span>
      <span class="pnl-sub" id="poSub">—</span>
      <span class="pnl-spacer"></span>
      <span class="po-status" id="poStatus"></span>
      <button class="btn btn--ghost" id="poRefresh" type="button">↻ 刷新</button>
    </div>
    <div class="pnl-bd po-body"><div class="po-list" id="poList"></div></div>
  `;

  const listEl = container.querySelector("#poList");
  const subEl = container.querySelector("#poSub");
  const statusEl = container.querySelector("#poStatus");

  function setStatus(msg, isError = false) {
    statusEl.textContent = msg || "";
    statusEl.className = "po-status" + (isError ? " error" : "");
  }

  function rowHtml(o) {
    const meta = STATUS[o.status];
    const label = meta ? meta.label : esc(String(o.status ?? "?"));
    const badgeCls = meta ? meta.badge : "unknown";
    const voidCls = o.status === "void" ? " po-row--void" : "";
    const arrival = o.arrival_date ? esc(o.arrival_date) : "—";
    const actsHtml =
      editing && editing.id === o.id
        ? editorHtml(o)
        : (meta ? meta.actions : [])
            .map((a) => actionBtn(a, o.id))
            .join("");
    return `
      <tr class="po-row${voidCls}" data-id="${o.id}">
        <td>${esc(o.supplier_name || o.supplier_id || "—")}</td>
        <td>${esc(o.order_date || "—")}</td>
        <td>${arrival}</td>
        <td><span class="po-badge po-badge--${badgeCls}">${label}</span></td>
        <td class="po-num">${fmtMoney(o.total_amount)}</td>
        <td><div class="po-acts">${actsHtml}</div></td>
      </tr>`;
  }

  function actionBtn(act, id) {
    const map = {
      arrival: `<button class="po-btn" data-act="arrival" data-id="${id}">标到货</button>`,
      edit:    `<button class="po-btn" data-act="edit" data-id="${id}">改期</button>`,
      void:    `<button class="po-btn po-btn--danger" data-act="void" data-id="${id}">作废</button>`,
    };
    return map[act] || "";
  }

  function editorHtml(o) {
    const val = editing.field === "arrival" ? today() : (o.order_date || today());
    return `
      <input type="date" class="po-date-input" value="${esc(val)}" aria-label="日期">
      <button class="po-btn" data-act="confirm" data-id="${o.id}">确认</button>
      <button class="po-btn" data-act="cancel" data-id="${o.id}">取消</button>`;
  }

  function render() {
    if (!orders.length) {
      listEl.innerHTML = `<div class="pnl-empty">暂无采购订单（导出采购订单后出现在这里）</div>`;
      subEl.textContent = "0 单";
      return;
    }
    subEl.textContent = `${orders.length} 单`;
    listEl.innerHTML = `
      <table class="po-table">
        <thead><tr>
          <th>供应商</th><th>下单日</th><th>到货日</th><th>状态</th><th class="po-num">金额€</th><th>操作</th>
        </tr></thead>
        <tbody>${orders.map(rowHtml).join("")}</tbody>
      </table>`;
  }

  async function load() {
    setStatus("加载中…");
    try {
      const res = await fetch("/purchase/orders");
      const data = await res.json();
      if (!data.ok) { setStatus(data.msg || "加载失败", true); return; }
      orders = data.orders || [];
      editing = null;
      render();
      setStatus("");
    } catch (e) {
      setStatus("加载失败（网络）", true);
    }
  }

  // 单一事件委托：作废 / 标到货 / 改期 / 确认 / 取消（Task 3 填入）
  listEl.addEventListener("click", async (e) => {
    // Task 3 内容
  });

  container.querySelector("#poRefresh").addEventListener("click", load);

  load();
}
```

- [ ] **Step 2: purchase.js 顶部加 import**

在 `static/js/purchase.js:1`（现有 import 行之后）添加：

```javascript
import { initPurchaseOrders } from "./purchase_orders.js";
```

- [ ] **Step 3: pagePurchase 模板最底部加容器**

在 `static/js/purchase.js` 的 `page.innerHTML = \`...\`` 模板里，**03 新条码面板 `</section>` 之后、模板字符串结束反引号之前**（即所有现有 section 之后，约 `:248` 的 `</div>\`;` 前），加入：

```html
      <!-- 04 订单跟踪 -->
      <section class="pnl" id="purOrders"></section>
```

- [ ] **Step 4: init() 末尾调用**

在 `static/js/purchase.js` 的 `init()` 函数末尾（约 `:275` 之后、`init` 闭合 `}` 之前，最后一个 `addEventListener` 之后）添加：

```javascript
    initPurchaseOrders(document.getElementById('purOrders'));
```

- [ ] **Step 5: 浏览器验证只读列表 + 布局**

刷新采购页，确认：
- `#purOrders` 面板出现在 03 之后，标题「04 订单跟踪」，右侧有「↻ 刷新」。
- 表格列出 seed 的 2 单：演示供应商 / 日期 / 状态徽章（已下单、已到货）/ 金额（`1.240`、`3.580` 千分位）。
- **转义验证**：供应商名显示为字面 `演示供应商<b>`（`<b>` 不被解析成粗体）。
- **布局**：面板高度固定，订单多时面板内部滚动，不挤压 02 解析区；点面板头可折叠/展开。
- 点「↻ 刷新」列表重新加载无报错。

Expected: 列表正常、转义生效、布局不裂。控制台无错误。

- [ ] **Step 6: 提交**

```bash
git add static/js/purchase_orders.js static/js/purchase.js
git commit -m "feat(purchase-ui): 订单跟踪只读列表(白名单状态+转义+折叠面板)"
```

---

## Task 3: 行内操作（作废 / 标到货 / 改期）

**Files:**
- Modify: `static/js/purchase_orders.js`（填入 Task 2 留空的事件委托 + 加 `postAction` / `focusDate`）

- [ ] **Step 1: 填入事件委托逻辑**

把 `static/js/purchase_orders.js` 里 Task 2 留的：

```javascript
  // 单一事件委托：作废 / 标到货 / 改期 / 确认 / 取消（Task 3 填入）
  listEl.addEventListener("click", async (e) => {
    // Task 3 内容
  });
```

替换为：

```javascript
  // 单一事件委托：作废 / 标到货 / 改期 / 确认 / 取消
  listEl.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const act = btn.dataset.act;

    if (act === "void") {
      if (!window.confirm("确认作废该采购单？作废后不计入前置期统计")) return;
      await postAction(`/purchase/orders/${id}/void`, {});
      return;
    }
    if (act === "arrival") { editing = { id, field: "arrival" }; render(); focusDate(); return; }
    if (act === "edit")    { editing = { id, field: "order_date" }; render(); focusDate(); return; }
    if (act === "cancel")  { editing = null; render(); return; }
    if (act === "confirm") {
      const input = listEl.querySelector(".po-date-input");
      const val = input && input.value;
      if (!val) { setStatus("请填日期", true); return; }
      if (editing.field === "arrival") {
        await postAction(`/purchase/orders/${id}/arrival`, { arrival_date: val });
      } else {
        await postAction(`/purchase/orders/${id}/update`, { order_date: val });
      }
    }
  });

  function focusDate() {
    const input = listEl.querySelector(".po-date-input");
    if (input) input.focus();
  }

  async function postAction(url, body) {
    setStatus("提交中…");
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!data.ok) { setStatus(data.msg || "操作失败", true); return; }
      editing = null;
      await load();           // 成功 → 重新拉列表重渲染
    } catch (e) {
      setStatus("操作失败（网络）", true);
    }
  }
```

> 说明：`postAction` 不用 `shared.js` 的 `postJSON`，因为要分辨 HTTP 错误体里的 `msg`（400/404 也返回 JSON）。错误 `msg` 经 `textContent`（`setStatus`）渲染，不裸拼 HTML。

- [ ] **Step 2: 浏览器验证三种操作**

刷新采购页，对 placed 的「演示供应商」单：
- **作废**：点「作废」→ confirm 弹窗 → 确认 → 该行变灰、状态「已作废」、无操作按钮。
- 重新 seed 一张 placed（重跑准备步骤的 seed 命令）。
- **标到货**：点「标到货」→ 行内出现 date 输入（默认今天）→ 改成某天 → 「确认」→ 状态变「已到货」、到货日列显示该日、操作只剩「改期」。
- **改期**：对任一单点「改期」→ date 输入预填当前下单日 → 改日期 → 「确认」→ 下单日列更新。
- **取消**：点「标到货」再点「取消」→ 回到按钮态，无副作用。
- **错误态（400）**：console 手动 `fetch('/purchase/orders/<id>/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({arrival_date:'2026-01-01'})}).then(r=>r.json()).then(console.log)` → 应得 `{ok:false}` 且 HTTP 400（验证后端守卫，UI 不会发这种请求）。

Expected: 三种操作都生效并即时重渲染；确认/取消行为正确；错误 msg 显示在面板红条。

- [ ] **Step 3: 提交**

```bash
git add static/js/purchase_orders.js
git commit -m "feat(purchase-ui): 行内作废/标到货/改期(事件委托+错误红条)"
```

---

## Task 4: 布局回归 + 主题截图 + 收尾

**Files:** 无（纯验证）

- [ ] **Step 1: 三态布局回归**

在以下三种采购页状态下，确认 `#purOrders` 都可见且不挤坏 02/03/04：
1. **空态**：未上传采购 Excel（02 显示「上传供应商 Excel 后自动解析」）。
2. **已解析态**：上传一个供应商 Excel，02 有数据。
3. **新条码面板展开态**：上传含新条码的文件，03 显示。

每种状态下 `#purOrders` 面板应在最底部、内部滚动、可折叠，且不把 02 压到不可用。

Expected: 三态布局均不裂，订单面板始终可达。

- [ ] **Step 2: 暗色/亮色截图核对**

切换主题（页面右上 theme-switch），对 `#purOrders` 面板暗色 + 亮色各截一张，确认徽章/按钮/边框在两主题下对比度正常。

- [ ] **Step 3: 清理测试数据（如需要）**

如果 seed 的演示订单不想留在本地库：
```powershell
.venv\Scripts\python.exe -c "from server import create_app; from app.models import PurchaseOrder, get_session; from sqlalchemy import delete; app=create_app();
with get_session() as s: s.execute(delete(PurchaseOrder).where(PurchaseOrder.source_file.in_(['demo.xlsx','demo2.xlsx']))); s.commit(); print('cleaned')"
```

- [ ] **Step 4: 完成开发分支**

调用 superpowers:finishing-a-development-branch 决定合并方式（按项目约定：squash merge 回 main；push main 触发生产部署由用户手动执行）。

---

## Self-Review（计划自检）

- **Spec 覆盖**：列表（Task 2）/ 标到货+改期+作废（Task 3）/ 布局 flex-shrink+内部滚动+折叠（Task 1+2）/ 白名单状态（Task 2 STATUS）/ 转义（Task 2 esc + Task 3 textContent）/ 三态布局验证（Task 4）/ 刷新（Task 2 #poRefresh）—— 全覆盖。
- **占位符**：除 Task 2 故意留空的事件委托（Task 3 Step 1 明确填入）外无 TBD；每个改码步骤都给了完整代码。
- **类型/命名一致**：`initPurchaseOrders` / `STATUS` / `editing{id,field}` / `load` / `render` / `postAction` / `setStatus` 跨 Task 一致；`data-act` 值（arrival/edit/void/confirm/cancel）与 `actionBtn`/委托分支一致；`field` 值（arrival/order_date）与 editor/confirm 分支一致。
