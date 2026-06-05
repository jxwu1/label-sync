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

  // 单一事件委托：作废 / 标到货 / 改期 / 确认 / 取消
  listEl.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const act = btn.dataset.act;
    if (!Number.isFinite(id)) return;

    if (act === "void") {
      if (!window.confirm("确认作废该采购单？作废后不计入前置期统计")) return;
      await postAction(`/purchase/orders/${id}/void`, {});
      return;
    }
    if (act === "arrival") { editing = { id, field: "arrival" }; render(); focusDate(); return; }
    if (act === "edit")    { editing = { id, field: "order_date" }; render(); focusDate(); return; }
    if (act === "cancel")  { editing = null; render(); return; }
    if (act === "confirm") {
      if (!editing) return;
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
      await load();
    } catch (e) {
      setStatus("操作失败（网络）", true);
    }
  }

  container.querySelector("#poRefresh").addEventListener("click", load);

  // 点面板头折叠/展开；但头部里的刷新按钮不触发折叠
  container.querySelector(".pnl-hd").addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    container.classList.toggle("is-collapsed");
  });

  load();
}
