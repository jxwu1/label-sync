// 货号历史 - 扫描批次 module
"use strict";

import { escapeHtml, byId as $ } from "./shared.js";

let _allBatches = [];
let _isInitialized = false;

function formatBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

async function fetchJson(url) {
  const resp = await fetch(url);
  const data = await resp.json();
  if (!data.ok) throw new Error(data.msg || "未知错误");
  return data;
}

// 进入 scan sub-tab 时首次加载（懒加载）。
// 注：sub-tab 的 active class 切换由 index-recent-changes.js 的 setupTabs 统一处理；
// 这里只挂载"首次激活时拉数据"的 hook。
function setupTabHook() {
  document.querySelectorAll('#historyTabs [data-history-tab="batch"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!_isInitialized) {
        _isInitialized = true;
        loadBatches();
      }
    });
  });
}

async function loadBatches() {
  const list = $("scanHistoryList");
  list.innerHTML = '<div class="sh-empty">加载中...</div>';
  try {
    const data = await fetchJson("/scan_history/batches");
    _allBatches = data.batches;
    renderEmployeeOptions(data.employees);
    renderList();
  } catch (err) {
    list.innerHTML = `<div class="sh-empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

function renderEmployeeOptions(employees) {
  const sel = $("scanHistoryEmployee");
  // 保留首项"全部员工"，重建其余
  while (sel.options.length > 1) sel.remove(1);
  employees.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  sel.onchange = renderList;
}

function renderList() {
  const list = $("scanHistoryList");
  const filter = $("scanHistoryEmployee").value;
  const filtered = filter ? _allBatches.filter((b) => b.employee === filter) : _allBatches;

  if (filtered.length === 0) {
    list.innerHTML = '<div class="sh-empty">暂无批次</div>';
    return;
  }

  list.innerHTML = filtered.map(renderRow).join("");
  attachRowToggleHandlers();
}

function renderRow(b) {
  const csvLine = b.csv_filename
    ? `<div class="sh-file">📄 ${escapeHtml(b.csv_filename)} · ${b.csv_rows} 行 · ${formatBytes(b.csv_size_bytes)}
         <a class="sh-file-dl" href="/scan_history/batches/${encodeURIComponent(b.batch_id)}/download/csv">下载</a>
       </div>`
    : `<div class="sh-file" style="color:var(--ink-3);">📄 CSV 缺失</div>`;

  const xlsxLines = (b.xlsx_files || []).map((f) =>
    `<div class="sh-file">📊 ${escapeHtml(f.name)} · ${formatBytes(f.size_bytes)}
       <a class="sh-file-dl" href="/scan_history/batches/${encodeURIComponent(b.batch_id)}/files/${encodeURIComponent(f.name)}">下载</a>
     </div>`
  ).join("");

  const csvSummary = b.csv_rows !== null && b.csv_rows !== undefined ? `${b.csv_rows} 行` : "无 CSV";
  const xlsxCount = (b.xlsx_files || []).length;
  const xlsxSummary = xlsxCount > 0 ? `${xlsxCount} 个 xlsx` : "";
  const meta = [csvSummary, xlsxSummary].filter(Boolean).join(" · ");

  return `
    <div class="sh-row" data-batch-id="${escapeHtml(b.batch_id)}">
      <div class="sh-row-head">
        <span class="sh-time">${escapeHtml(b.scanned_at)}</span>
        <span class="sh-emp">${escapeHtml(b.employee)}</span>
        <span class="sh-meta">${escapeHtml(meta)}</span>
        <span class="sh-chevron">▶</span>
      </div>
      <div class="sh-detail">
        ${csvLine}
        ${xlsxLines}
      </div>
    </div>
  `;
}

function attachRowToggleHandlers() {
  document.querySelectorAll("#scanHistoryList .sh-row-head").forEach((head) => {
    head.addEventListener("click", () => {
      head.parentElement.classList.toggle("open");
    });
  });
}

document.addEventListener("DOMContentLoaded", setupTabHook);
