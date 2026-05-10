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
  setupModeToggle();
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
  sel.innerHTML = imports.map((b) => {
    if (b.is_open) {
      // 开放批次：上次 import 之后到现在的零散改动（标签修改 / 单条修正等）
      return `<option value="${b.batch_id}">🔄 进行中（上次 import 之后） — 改动 ${b.affected_barcodes} 个货号 · 最近 ${escapeHtml(b.taken_at || "—")}</option>`;
    }
    return `<option value="${b.batch_id}">${escapeHtml(b.taken_at)} （${b.total_local} 条 / 改动 ${b.affected_barcodes} 个货号）</option>`;
  }).join("");
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
  // PR 9 · 5 stat box grid，tone 按 count 0/>0 切（默认/accent/info/warn/error）
  const cell = (label, n, filterKey, filterValue, baseTone) => {
    const tone = n > 0 ? baseTone : "default";
    return `
      <button class="rc-summary-cell" data-tone="${tone}"
              data-filter-key="${filterKey || ""}" data-filter-value="${filterValue || ""}">
        <div class="rc-summary-num">${n}</div>
        <div class="rc-summary-label">${label}</div>
      </button>`;
  };
  $("rcSummary").innerHTML = `
    <div class="rc-summary-grid">
      ${cell("库位变更", s.location_changes, "field", "stockpile_location", "default")}
      ${cell("型号变更", s.model_changes,    "field", "product_model",      "info")}
      ${cell("新增",     s.inserts,          "change_type", "insert",       "accent")}
      ${cell("失效",     s.deactivates,      "change_type", "deactivate",   "error")}
      ${cell("重新上架", s.reactivates,      "change_type", "reactivate",   "warn")}
    </div>
    <div class="rc-roundtrip-note">
      来回波动 <b>${s.roundtrip_count}</b> 组 · 同 barcode + 字段终态==起始态的折叠剔除噪音
    </div>`;
  document.querySelectorAll(".rc-summary-cell").forEach((cell) => {
    cell.addEventListener("click", () => {
      const k = cell.dataset.filterKey, v = cell.dataset.filterValue;
      if (!k || !v) return;
      _currentFilter = { field: null, change_type: null };
      _currentFilter[k] = v;
      loadChanges();
      renderChips();
    });
  });
}

function renderChips() {
  // 用 _lastSummary 算每个 chip 的 count（无 summary 时省略 count 数字）
  const s = _lastSummary || {};
  const total = (s.location_changes || 0) + (s.model_changes || 0)
              + (s.inserts || 0) + (s.deactivates || 0) + (s.reactivates || 0);
  const chips = [
    { label: "全部",   n: total,                  filter: { field: null, change_type: null } },
    { label: "仅库位", n: s.location_changes || 0, filter: { field: "stockpile_location", change_type: null } },
    { label: "仅型号", n: s.model_changes || 0,    filter: { field: "product_model", change_type: null } },
    { label: "仅新增", n: s.inserts || 0,          filter: { field: null, change_type: "insert" } },
    { label: "仅失效", n: s.deactivates || 0,      filter: { field: null, change_type: "deactivate" } },
  ];
  if (_currentMode === "raw") {
    chips.push({ label: "仅 update", n: 0, filter: { field: null, change_type: "update" } });
    chips.push({ label: "仅 reactivate", n: s.reactivates || 0, filter: { field: null, change_type: "reactivate" } });
  }
  const html = chips.map((c) => {
    const active = c.filter.field === _currentFilter.field
                && c.filter.change_type === _currentFilter.change_type;
    const countSpan = _lastSummary
      ? `<span class="rc-chip-count">${c.n}</span>`
      : "";
    return `<button class="rc-chip${active ? " rc-chip--active" : ""}"
              data-filter='${JSON.stringify(c.filter)}'>${escapeHtml(c.label)}${countSpan}</button>`;
  }).join("");
  $("rcChips").innerHTML = html;
  document.querySelectorAll(".rc-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      _currentFilter = JSON.parse(chip.dataset.filter);
      loadChanges();
      renderChips();
    });
  });
}

function setupModeToggle() {
  $("rcModeToggle").addEventListener("click", () => {
    _currentMode = _currentMode === "collapsed" ? "raw" : "collapsed";
    const btn = $("rcModeToggle");
    btn.dataset.mode = _currentMode;
    btn.textContent = _currentMode === "collapsed" ? "展开 raw 事件" : "折叠净效应";
    loadChanges();
    renderChips();
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
  if (rows.length === 0) {
    $("rcList").innerHTML = '<div class="rc-empty">该批次无变更事件</div>';
    return;
  }
  const body = rows.map((r) => {
    const fieldCn = FIELD_CN[r.field] || r.field;
    const typeCn = CHANGE_TYPE_CN[r.change_type] || r.change_type;
    return `
      <tr class="rc-row" data-barcode="${escapeHtml(r.barcode)}">
        <td>${escapeHtml(r.barcode)}</td>
        <td>${escapeHtml(r.model || "")}</td>
        <td>${fieldCn}</td>
        <td><code>${escapeHtml(r.old_value ?? "")}</code></td>
        <td><code>${escapeHtml(r.new_value ?? "")}</code></td>
        <td><span class="rc-tag">${typeCn}</span></td>
        <td class="rc-time">${escapeHtml((r.created_at || "").slice(11, 19))}</td>
      </tr>`;
  }).join("");
  $("rcList").innerHTML = `
    <table class="rc-table">
      <thead><tr><th>货号</th><th>型号</th><th>字段</th><th>旧值</th><th>新值</th><th>类型</th><th>时间</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;
  document.querySelectorAll(".rc-row").forEach((tr) => {
    tr.addEventListener("click", () => drillToBarcode(tr.dataset.barcode));
  });
}

function renderChangeCell(r) {
  if (r.change_type === "insert") {
    return `<span class="rc-tag rc-tag--insert"><span class="rc-tag-glyph">+</span>新货号 → ${escapeHtml(r.to_value || r.barcode)}</span>`;
  }
  if (r.change_type === "deactivate") {
    return `<span class="rc-tag rc-tag--del"><span class="rc-tag-glyph">✕</span>失效</span>`;
  }
  if (r.change_type === "reactivate") {
    return `<span class="rc-tag rc-tag--ok"><span class="rc-tag-glyph">↺</span>重新上架</span>`;
  }
  // 库位 / 型号 变更：from → to（带颜色 to）
  const isLoc = r.field === "stockpile_location";
  const isModel = r.field === "product_model";
  const fieldLabel = isLoc ? "库位" : isModel ? "型号" : (FIELD_CN[r.field] || r.field);
  const toCls = isLoc ? "rc-change-to rc-change-to--loc"
              : isModel ? "rc-change-to rc-change-to--model"
              : "rc-change-to";
  const fromHtml = r.from_value
    ? `<span class="rc-change-from">${escapeHtml(r.from_value)}</span><span class="rc-change-arrow">→</span>`
    : "";
  return `<span class="${isLoc ? "rc-change-loc" : isModel ? "rc-change-model" : ""}">${fieldLabel} ${fromHtml}<span class="${toCls}">${escapeHtml(r.to_value || "")}</span></span>`;
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
  renderChips();
  await Promise.all([loadSummary(), loadChanges()]);
}

document.addEventListener("DOMContentLoaded", setupTabs);
