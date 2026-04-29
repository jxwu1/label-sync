// 货号历史 - 最近改动 module
"use strict";

const $ = (id) => document.getElementById(id);

const FIELD_CN = {
  stockpile_location: "库位",
  product_model: "型号",
  product_barcode: "条码",
  is_active: "上下架",
};

const CHANGE_TYPE_CN = {
  update: "更新",
  insert: "新增",
  deactivate: "下架",
  reactivate: "上架",
};

let _currentBatchId = null;
let _currentMode = "collapsed";
let _currentFilter = { field: null, change_type: null };
let _lastSummary = null;
let _isInitialized = false;

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

async function fetchJson(url) {
  const resp = await fetch(url);
  const data = await resp.json();
  if (!data.ok) throw new Error(data.msg || "未知错误");
  return data;
}

// === sub-tab 切换 ===
function setupTabs() {
  document.querySelectorAll('#historyTabs [data-history-tab]').forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.historyTab;
      document.querySelectorAll('#historyTabs [data-history-tab]').forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
      document.querySelectorAll('[data-history-tab-panel]').forEach((p) => {
        p.classList.toggle("active", p.dataset.historyTabPanel === target);
      });
      if (target === "recent" && !_isInitialized) {
        loadInitial();
        _isInitialized = true;
      }
    });
  });
}

async function loadInitial() {
  try {
    const data = await fetchJson("/recent_changes/imports");
    populateBatchDropdown(data.imports);
    if (data.imports.length === 0) {
      $("rcSummary").innerHTML = '<div class="rc-empty">还没有 import 记录</div>';
      return;
    }
    _currentBatchId = data.imports[0].batch_id;
    await refreshBatch();
  } catch (e) {
    $("rcSummary").innerHTML = `<div class="rc-error">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function populateBatchDropdown(imports) {
  const sel = $("rcBatchSelect");
  sel.innerHTML = imports.map((b) =>
    `<option value="${b.batch_id}">${escapeHtml(b.taken_at)} （${b.total_local} 条 / 改动 ${b.affected_barcodes} 个货号）</option>`
  ).join("");
  sel.onchange = () => {
    _currentBatchId = parseInt(sel.value, 10);
    _currentFilter = { field: null, change_type: null };
    refreshBatch();
  };
}

// === Task 10: Summary 卡片 ===

async function loadSummary() {
  try {
    const data = await fetchJson(`/recent_changes/${_currentBatchId}/summary`);
    _lastSummary = data.summary;
    renderSummary(data.summary);
  } catch (e) {
    $("rcSummary").innerHTML = `<div class="rc-error">${escapeHtml(e.message)}</div>`;
  }
}

function renderSummary(s) {
  const card = (icon, label, n, filterKey, filterValue) => `
    <button class="rc-summary-cell" data-filter-key="${filterKey || ""}" data-filter-value="${filterValue || ""}">
      <div class="rc-summary-icon">${icon}</div>
      <div class="rc-summary-num">${n}</div>
      <div class="rc-summary-label">${label}</div>
    </button>`;
  $("rcSummary").innerHTML = `
    <div class="rc-summary-grid">
      ${card("📦", "库位变更", s.location_changes, "field", "stockpile_location")}
      ${card("🏷", "型号变更", s.model_changes, "field", "product_model")}
      ${card("➕", "新增", s.inserts, "change_type", "insert")}
      ${card("❌", "失效", s.deactivates, "change_type", "deactivate")}
      ${card("♻️", "重新上架", s.reactivates, "change_type", "reactivate")}
    </div>
    <div class="rc-summary-foot">
      🔁 来回波动 ${s.roundtrip_count} 组
      <span class="rc-tip">（同 barcode+字段终态==起始态的折叠剔除噪音）</span>
    </div>`;
  document.querySelectorAll(".rc-summary-cell").forEach((cell) => {
    cell.addEventListener("click", () => {
      const k = cell.dataset.filterKey, v = cell.dataset.filterValue;
      if (!k || !v) return;
      _currentFilter = { field: null, change_type: null };
      _currentFilter[k] = v;
      loadChanges();
    });
  });
}

// === Task 11: Collapsed 列表 + 行下钻 ===

async function loadChanges() {
  if (!_currentBatchId) return;
  const params = new URLSearchParams({ mode: _currentMode });
  if (_currentFilter.field) params.set("field", _currentFilter.field);
  if (_currentFilter.change_type) params.set("change_type", _currentFilter.change_type);
  try {
    const data = await fetchJson(`/recent_changes/${_currentBatchId}/changes?${params}`);
    if (_currentMode === "collapsed") {
      renderCollapsedList(data.changes);
    } else {
      renderRawList(data.changes);
    }
  } catch (e) {
    $("rcList").innerHTML = `<div class="rc-error">${escapeHtml(e.message)}</div>`;
  }
}

function renderCollapsedList(rows) {
  if (rows.length === 0) {
    $("rcList").innerHTML = '<div class="rc-empty">该批次无实质变更</div>';
    return;
  }
  const body = rows.map((r) => {
    const changeText = renderChangeCell(r);
    return `
      <tr class="rc-row" data-barcode="${escapeHtml(r.barcode)}">
        <td>${escapeHtml(r.barcode)}</td>
        <td>${escapeHtml(r.model || "")}</td>
        <td>${changeText}</td>
        <td class="rc-time">${escapeHtml((r.latest_at || "").slice(11, 19))}</td>
      </tr>`;
  }).join("");
  $("rcList").innerHTML = `
    <table class="rc-table">
      <thead><tr><th>货号</th><th>型号</th><th>变化</th><th>时间</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;
  document.querySelectorAll(".rc-row").forEach((tr) => {
    tr.addEventListener("click", () => drillToBarcode(tr.dataset.barcode));
  });
}

function renderRawList(rows) {
  // Task 12 will implement; stub to avoid runtime ReferenceError
  $("rcList").innerHTML = '<div class="rc-empty">raw 视图待 Task 12 实现</div>';
}

function renderChangeCell(r) {
  const fieldCn = FIELD_CN[r.field] || r.field;
  if (r.change_type === "insert") {
    return `<span class="rc-tag rc-tag--insert">➕ 新货号</span>`;
  }
  if (r.change_type === "deactivate") {
    return `<span class="rc-tag rc-tag--del">❌ 失效</span>`;
  }
  if (r.change_type === "reactivate") {
    return `<span class="rc-tag rc-tag--ok">♻️ 重新上架</span>`;
  }
  return `${fieldCn} <code>${escapeHtml(r.from_value || "")}</code> → <code>${escapeHtml(r.to_value || "")}</code>`;
}

function drillToBarcode(barcode) {
  document.querySelector('[data-history-tab="search"]').click();
  if (window.historySearch) {
    window.historySearch(barcode);
  }
}

// === refreshBatch (Task 10 + 11 wired up) ===

async function refreshBatch() {
  if (!_currentBatchId) return;
  await Promise.all([loadSummary(), loadChanges()]);
}

document.addEventListener("DOMContentLoaded", setupTabs);
