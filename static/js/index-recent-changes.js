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

async function refreshBatch() {
  if (!_currentBatchId) return;
  // 后续 task 会加 loadSummary / loadChanges
  $("rcSummary").innerHTML = `<div class="rc-empty">已选批次 ${_currentBatchId}（summary 待 Task 10 实现）</div>`;
  $("rcList").innerHTML = "";
}

document.addEventListener("DOMContentLoaded", setupTabs);
