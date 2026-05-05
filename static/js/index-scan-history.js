// 货号历史 - 扫描批次 module
"use strict";

const $ = (id) => document.getElementById(id);

let _allBatches = [];
let _isInitialized = false;

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

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
  document.querySelectorAll('#historyTabs [data-history-tab="scan"]').forEach((btn) => {
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
    ? `<div class="sh-file">
         <span class="sh-file__icon">📄</span>
         <span class="sh-file__name">${escapeHtml(b.csv_filename)}</span>
         <span class="sh-file__size">${b.csv_rows} 行 · ${formatBytes(b.csv_size_bytes)}</span>
         <a class="pur-btn-dl" href="/scan_history/batches/${encodeURIComponent(b.batch_id)}/download/csv">下载</a>
       </div>`
    : `<div class="sh-file"><span class="sh-file__icon">📄</span><span class="sh-file__name" style="color:var(--c-text-muted);">CSV 缺失</span></div>`;

  const xlsxLines = (b.xlsx_files || []).map((f) =>
    `<div class="sh-file">
       <span class="sh-file__icon">📊</span>
       <span class="sh-file__name">${escapeHtml(f.name)}</span>
       <span class="sh-file__size">${formatBytes(f.size_bytes)}</span>
       <a class="pur-btn-dl" href="/scan_history/batches/${encodeURIComponent(b.batch_id)}/files/${encodeURIComponent(f.name)}">下载</a>
     </div>`
  ).join("");

  const csvSummary = b.csv_rows !== null && b.csv_rows !== undefined ? `${b.csv_rows} 行` : "无 CSV";
  const xlsxCount = (b.xlsx_files || []).length;
  const xlsxSummary = xlsxCount > 0 ? `${xlsxCount} 个 xlsx` : "";
  const meta = [csvSummary, xlsxSummary].filter(Boolean).join(" · ");

  return `
    <div class="sh-row" data-batch-id="${escapeHtml(b.batch_id)}">
      <div class="sh-row__head">
        <span class="sh-row__time">${escapeHtml(b.scanned_at)}</span>
        <span class="sh-row__employee">${escapeHtml(b.employee)}</span>
        <span class="sh-row__meta">${escapeHtml(meta)}</span>
        <span class="sh-row__chevron">▶</span>
      </div>
      <div class="sh-row__detail">
        ${csvLine}
        ${xlsxLines}
      </div>
    </div>
  `;
}

function attachRowToggleHandlers() {
  document.querySelectorAll("#scanHistoryList .sh-row__head").forEach((head) => {
    head.addEventListener("click", () => {
      head.parentElement.classList.toggle("is-open");
    });
  });
}

document.addEventListener("DOMContentLoaded", setupTabHook);
