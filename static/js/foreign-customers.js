// 老外客人月度记录 tab
"use strict";

const $ = (id) => document.getElementById(id);

let currentMonth = "";
let cachedCustomers = []; // 客户下拉数据
let editingId = null; // null = 新增，否则是要更新的 record id

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function fmtMoney(amt) {
  if (amt === null || amt === undefined) return "—";
  return Number(amt).toFixed(2);
}

function fmtDate(d) {
  return d || "—";
}

async function loadCustomers() {
  try {
    const res = await fetch("/foreign-customers/customers");
    const body = await res.json();
    cachedCustomers = body.customers || [];
  } catch (e) {
    cachedCustomers = [];
  }
}

function renderCustomerSelect() {
  const sel = $("fcModalCustomer");
  if (!sel) return;
  // 用 optgroup 按 type 分组
  const groups = { foreign: [], mixed: [], unknown: [], chinese: [] };
  for (const c of cachedCustomers) {
    (groups[c.customer_type] || groups.unknown).push(c);
  }
  const labelMap = { foreign: "老外", mixed: "混合（中希）", unknown: "未归类", chinese: "中国" };
  let html = "";
  for (const type of ["foreign", "mixed", "unknown", "chinese"]) {
    if (!groups[type].length) continue;
    html += `<optgroup label="${labelMap[type]} (${groups[type].length})">`;
    for (const c of groups[type]) {
      html += `<option value="${escapeHtml(c.customer_id)}">${escapeHtml(c.customer_name)} (${escapeHtml(c.customer_id)})</option>`;
    }
    html += "</optgroup>";
  }
  sel.innerHTML = html;
}

async function loadMonth() {
  if (!currentMonth) return;
  await Promise.all([loadSummary(), loadRecords()]);
}

async function loadSummary() {
  try {
    const res = await fetch(`/foreign-customers/summary/${currentMonth}`);
    const body = await res.json();
    if (!body.ok) {
      $("fcSummary").textContent = "加载失败";
      return;
    }
    const s = body.summary;
    $("fcSummary").innerHTML = `
      <div class="fc-stat-row">
        <div class="fc-stat"><div class="fc-stat-k">记录数</div><div class="fc-stat-v">${s.record_count}</div></div>
        <div class="fc-stat"><div class="fc-stat-k">总欠款</div><div class="fc-stat-v">€${fmtMoney(s.total_amount_due)}</div></div>
        <div class="fc-stat"><div class="fc-stat-k">已付</div><div class="fc-stat-v fc-paid">${s.paid_count}</div></div>
        <div class="fc-stat"><div class="fc-stat-k">未付</div><div class="fc-stat-v fc-unpaid">${s.unpaid_count}</div></div>
        <div class="fc-stat"><div class="fc-stat-k">已托运</div><div class="fc-stat-v">${s.shipped_count}</div></div>
      </div>
    `;
  } catch (e) {
    $("fcSummary").textContent = `加载失败：${e.message}`;
  }
}

async function loadRecords() {
  try {
    const res = await fetch(`/foreign-customers/records?month=${encodeURIComponent(currentMonth)}`);
    const body = await res.json();
    if (!body.ok) {
      $("fcRecordsBody").innerHTML = `<tr><td colspan="7" class="empty">加载失败：${escapeHtml(body.msg || "")}</td></tr>`;
      return;
    }
    renderRecords(body.records);
  } catch (e) {
    $("fcRecordsBody").innerHTML = `<tr><td colspan="7" class="empty">网络错误：${escapeHtml(e.message)}</td></tr>`;
  }
}

function renderRecords(records) {
  $("fcRecordCount").textContent = records.length ? `(${records.length})` : "";
  if (!records.length) {
    $("fcRecordsBody").innerHTML = `<tr><td colspan="7" class="empty">本月暂无记录</td></tr>`;
    return;
  }
  $("fcRecordsBody").innerHTML = records
    .map((r) => {
      const paidCls = r.payment_date ? "fc-row-paid" : "fc-row-unpaid";
      return `<tr class="${paidCls}" data-id="${r.id}">
        <td>${escapeHtml(r.customer_name)}</td>
        <td class="fc-num">€${fmtMoney(r.amount_due)}</td>
        <td>${escapeHtml(r.tax_number) || "—"}</td>
        <td>${fmtDate(r.payment_date)}</td>
        <td>${fmtDate(r.shipping_date)}</td>
        <td class="fc-notes">${escapeHtml(r.notes) || "—"}</td>
        <td class="fc-ops">
          <button class="btn-mini fc-edit-btn" data-id="${r.id}">编辑</button>
          <button class="btn-mini fc-del-btn" data-id="${r.id}">删除</button>
        </td>
      </tr>`;
    })
    .join("");
  // bind ops
  for (const btn of $("fcRecordsBody").querySelectorAll(".fc-edit-btn")) {
    btn.addEventListener("click", () => openEditModal(parseInt(btn.dataset.id, 10), records));
  }
  for (const btn of $("fcRecordsBody").querySelectorAll(".fc-del-btn")) {
    btn.addEventListener("click", () => deleteRecord(parseInt(btn.dataset.id, 10)));
  }
}

function openAddModal() {
  editingId = null;
  $("fcModalTitle").textContent = "新增记录";
  $("fcModalMonth").value = currentMonth;
  $("fcModalMonth").disabled = false;
  $("fcModalCustomer").disabled = false;
  $("fcModalCustomer").value = cachedCustomers[0]?.customer_id || "";
  $("fcModalAmount").value = "";
  $("fcModalTax").value = "";
  $("fcModalPayment").value = "";
  $("fcModalShipping").value = "";
  $("fcModalNotes").value = "";
  $("fcModalOverlay").style.display = "flex";
}

function openEditModal(id, records) {
  const rec = records.find((r) => r.id === id);
  if (!rec) return;
  editingId = id;
  $("fcModalTitle").textContent = `编辑记录 #${id}`;
  $("fcModalMonth").value = rec.record_month;
  $("fcModalMonth").disabled = true; // 月份不可改
  $("fcModalCustomer").value = rec.customer_id;
  $("fcModalCustomer").disabled = true; // 客户不可改
  $("fcModalAmount").value = rec.amount_due ?? "";
  $("fcModalTax").value = rec.tax_number ?? "";
  $("fcModalPayment").value = rec.payment_date ?? "";
  $("fcModalShipping").value = rec.shipping_date ?? "";
  $("fcModalNotes").value = rec.notes ?? "";
  $("fcModalOverlay").style.display = "flex";
}

function closeModal() {
  $("fcModalOverlay").style.display = "none";
}

async function submitModal() {
  const payload = {
    amount_due: $("fcModalAmount").value === "" ? null : parseFloat($("fcModalAmount").value),
    tax_number: $("fcModalTax").value.trim(),
    payment_date: $("fcModalPayment").value,
    shipping_date: $("fcModalShipping").value,
    notes: $("fcModalNotes").value.trim(),
  };
  let url, method;
  if (editingId === null) {
    payload.customer_id = $("fcModalCustomer").value;
    payload.record_month = $("fcModalMonth").value;
    if (!payload.customer_id || !payload.record_month) {
      alert("请选择客户和月份");
      return;
    }
    url = "/foreign-customers/records";
    method = "POST";
  } else {
    url = `/foreign-customers/records/${editingId}`;
    method = "PUT";
  }
  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!body.ok) {
      alert(body.msg || "保存失败");
      return;
    }
    closeModal();
    await loadMonth();
  } catch (e) {
    alert("网络错误：" + e.message);
  }
}

async function deleteRecord(id) {
  if (!confirm(`删除这条记录？`)) return;
  try {
    const res = await fetch(`/foreign-customers/records/${id}`, { method: "DELETE" });
    const body = await res.json();
    if (!body.ok) {
      alert(body.msg || "删除失败");
      return;
    }
    await loadMonth();
  } catch (e) {
    alert("网络错误：" + e.message);
  }
}

async function init() {
  if (!$("fcMonth")) return; // 不在该 tab
  $("fcMonth").value = new Date().toISOString().slice(0, 7);
  currentMonth = $("fcMonth").value;
  $("fcMonth").addEventListener("change", () => {
    currentMonth = $("fcMonth").value;
    loadMonth();
  });
  $("fcRefresh").addEventListener("click", loadMonth);
  $("fcAddBtn").addEventListener("click", openAddModal);
  $("fcModalSubmit").addEventListener("click", submitModal);
  $("fcModalCancel").addEventListener("click", closeModal);

  await loadCustomers();
  renderCustomerSelect();
  await loadMonth();
}

init();
