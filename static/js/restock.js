// 补货决策面板（pageRestock）
// 数据源 /analytics/list（扩字段后包含 qty_total / weekly_velocity /
// weeks_of_cover / urgency_score / urgency_breakdown / is_truly_discontinued / origin）。
// 浏览器侧 filter + sort，导出走 /analytics/sales/top（透传 origin / 排除停用）。
"use strict";

const $ = (id) => document.getElementById(id);

const AUTO_CN = {
  new: "新品",
  seasonal: "季节性",
  declining: "衰退",
  stable: "稳定",
  unclassified: "未分类",
};

const LS_KEY_ORDERED = "restock_ordered_v1";
const ORDERED_EXPIRY_DAYS = 30;

const state = {
  items: [],
  filter: {
    origin: "FOREIGN",
    view: "active",
    auto: "",
    coverMax: 4,
    supplier: null,        // 供应商筛选 (点击表里 supplier_id 触发)
    show_ordered: false,   // 显示已下单
  },
  sort: { key: "urgency_score", dir: "desc" },
  selected: new Set(),     // 当前勾选的 barcode
  ordered: {},             // {barcode: {marked_at: ISO}}; 从 localStorage 加载
  orderedHistory: [],      // 撤销栈: 每次「标已下单」推入 [bc1, bc2, ...]
};

function loadOrdered() {
  try {
    const raw = localStorage.getItem(LS_KEY_ORDERED);
    if (!raw) return {};
    const data = JSON.parse(raw);
    const cutoff = Date.now() - ORDERED_EXPIRY_DAYS * 86400000;
    const cleaned = {};
    for (const [bc, v] of Object.entries(data || {})) {
      if (v && v.marked_at && Date.parse(v.marked_at) >= cutoff) cleaned[bc] = v;
    }
    return cleaned;
  } catch (_) {
    return {};
  }
}

function saveOrdered() {
  try {
    localStorage.setItem(LS_KEY_ORDERED, JSON.stringify(state.ordered));
  } catch (_) { /* ignore quota */ }
}

function autoClearOrderedByPurchase() {
  // 货到后 inventory_events 出现新 purchase → last_purchase_at 更新 → 自动 unmark
  let changed = false;
  for (const bc of Object.keys(state.ordered)) {
    const it = state.items.find((x) => x.barcode === bc);
    if (!it || !it.last_purchase_at) continue;
    const last = Date.parse(it.last_purchase_at);
    const marked = Date.parse(state.ordered[bc].marked_at);
    if (Number.isFinite(last) && last > marked) {
      delete state.ordered[bc];
      changed = true;
    }
  }
  if (changed) saveOrdered();
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fmt(n, digits = 0) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtDays(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1) return "今天";
  if (n < 30) return `${n} 天前`;
  if (n < 365) return `${Math.round(n / 30)} 月前`;
  return `${(n / 365).toFixed(1)} 年前`;
}

function originBadge(origin) {
  if (origin === "FOREIGN") return '<span class="rs-origin rs-origin--fo">🇬🇷</span>';
  if (origin === "CN") return '<span class="rs-origin rs-origin--cn">🇨🇳</span>';
  return '<span class="rs-origin rs-origin--unk">?</span>';
}

function urgencyCell(it) {
  if (it.urgency_score === null || it.urgency_score === undefined) {
    return '<span class="rs-urgency rs-urgency--none">—</span>';
  }
  const score = it.urgency_score;
  const cls =
    score >= 70 ? "rs-urgency--hot" :
    score >= 40 ? "rs-urgency--warm" :
    "rs-urgency--cold";
  const bd = it.urgency_breakdown;
  let tip = `紧迫分 ${score}`;
  if (bd) {
    tip += `\n  销速(50): ${bd.velocity}（origin 分位 ${(bd.velocity_pctile * 100).toFixed(0)}%）`;
    tip += `\n  库存(30): ${bd.cover}（${it.weeks_of_cover === null ? "无库存数据" : it.weeks_of_cover + " 周可撑"}）`;
    tip += `\n  距进货(20): ${bd.recency}（${fmtDays(it.last_purchase_days_ago)}）`;
  }
  return `<span class="rs-urgency ${cls}" title="${escapeHtml(tip)}">${score}</span>`;
}

function weeksOfCoverCell(woc) {
  if (woc === null || woc === undefined) return "—";
  const cls =
    woc <= 2 ? "rs-woc--crit" :
    woc <= 4 ? "rs-woc--warn" :
    woc >= 20 ? "rs-woc--cold" :
    "";
  const label = woc === 0 ? "🔥 已断" : `${woc.toFixed(1)} 周`;
  return `<span class="rs-woc ${cls}">${label}</span>`;
}

function fakeBars(it) {
  const seed = (it.total_qty || 0) % 100;
  const trend = it.trend_slope_pct_per_week || 0;
  return Array.from({ length: 12 }, (_, i) => {
    const noise = Math.sin(i * 0.7 + seed) + 1.4;
    const trendAdj = trend ? (trend / 5) * i : 0;
    return Math.max(1, Math.round(noise * (it.total_qty / 200) + trendAdj));
  });
}

function sparkline(values, color) {
  const max = Math.max(...values, 1);
  return `<span class="rs-spark">` +
    values.map((v, i) => {
      const h = Math.max(2, Math.round((v / max) * 100));
      const op = (0.4 + (i / values.length) * 0.6).toFixed(2);
      return `<span class="rs-spark__bar" style="height:${h}%;background:${color};opacity:${op}"></span>`;
    }).join("") +
    `</span>`;
}

function applyFilter(items) {
  return items.filter((it) => {
    const isOrdered = it.barcode in state.ordered;
    if (state.filter.show_ordered) {
      if (!isOrdered) return false;
      // 已下单视图: 不应用其它筛, 让用户看到全部 ordered 历史
      return true;
    }
    if (isOrdered) return false; // 默认隐藏已下单
    if (state.filter.origin && it.origin !== state.filter.origin) return false;
    if (state.filter.supplier && it.supplier_id !== state.filter.supplier) return false;
    if (state.filter.view === "active") {
      if (it.is_truly_discontinued) return false;
      if (it.is_new_item) return false;
    } else if (state.filter.view === "new") {
      if (!it.is_new_item) return false;
    }
    if (state.filter.auto && it.auto_category !== state.filter.auto) return false;
    if (state.filter.coverMax !== null && state.filter.view === "active") {
      // null = 无 snapshot 数据, 不当 "不缺货" 过滤
      if (it.weeks_of_cover !== null && it.weeks_of_cover !== undefined
          && it.weeks_of_cover > state.filter.coverMax) return false;
    }
    return true;
  });
}

function applySort(items) {
  const { key, dir } = state.sort;
  const mul = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
}

function renderRow(it) {
  const autoBadge = it.auto_category
    ? `<span class="cat-badge cat-${escapeHtml(it.auto_category)}">${escapeHtml(AUTO_CN[it.auto_category] || it.auto_category)}</span>`
    : "—";
  const nameCell = it.name_zh
    ? `<span class="rs-model">${escapeHtml(it.model)}</span><span class="rs-name">${escapeHtml(it.name_zh)}</span>`
    : `<span class="rs-model">${escapeHtml(it.model)}</span>`;
  const trend = it.trend_slope_pct_per_week;
  const sparkColor = trend > 0 ? "var(--accent)" : trend < 0 ? "var(--error)" : "var(--ink-3)";
  const disc = it.is_truly_discontinued ? '<span class="rs-tag rs-tag--disc">停用</span>' : "";
  const newTag = it.is_new_item ? '<span class="rs-tag rs-tag--new">新品</span>' : "";
  const ordered = it.barcode in state.ordered;
  const orderedTag = ordered
    ? `<span class="rs-tag rs-tag--ordered" title="标已下单 ${escapeHtml(state.ordered[it.barcode].marked_at.slice(0,10))}">已下单</span>`
    : "";
  const checked = state.selected.has(it.barcode) ? "checked" : "";
  const checkboxCol = state.filter.show_ordered
    ? "" // 已下单视图不让勾选
    : `<input type="checkbox" class="rs-check" data-bc="${escapeHtml(it.barcode)}" ${checked}>`;
  const supplierCell = it.supplier_id
    ? `<button class="rs-supplier" data-supplier="${escapeHtml(it.supplier_id)}" title="筛选同供应商 SKU">${escapeHtml(it.supplier_id)}</button>`
    : '<span class="rs-supplier rs-supplier--none">—</span>';
  return `
    <tr class="rs-row" data-bc="${escapeHtml(it.barcode)}">
      <td class="rs-check-cell">${checkboxCol}</td>
      <td class="rs-bc">${escapeHtml(it.barcode)}${disc}${newTag}${orderedTag}</td>
      <td class="rs-name-cell">${nameCell}</td>
      <td>${originBadge(it.origin)}</td>
      <td>${supplierCell}</td>
      <td class="rs-num">${fmt(it.qty_total)}</td>
      <td class="rs-num">${fmt(it.weekly_velocity, 1)}</td>
      <td class="rs-num">${weeksOfCoverCell(it.weeks_of_cover)}</td>
      <td class="rs-num">${sparkline(fakeBars(it), sparkColor)}</td>
      <td class="rs-num">${fmtDays(it.last_purchase_days_ago)}</td>
      <td>${autoBadge}</td>
      <td class="rs-num">${urgencyCell(it)}</td>
    </tr>
  `;
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  const s = String(v);
  if (/[,"\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function exportSelectedCsv() {
  if (state.selected.size === 0) {
    alert("请先勾选要导出的行");
    return;
  }
  const cols = [
    ["barcode", "条码"],
    ["model", "型号"],
    ["name_zh", "品名"],
    ["origin", "Origin"],
    ["supplier_id", "供应商"],
    ["qty_total", "当前库存"],
    ["weekly_velocity", "周销速"],
    ["weeks_of_cover", "可撑周数"],
    ["last_purchase_days_ago", "距上次进货 (天)"],
    ["auto_category", "分类"],
    ["urgency_score", "紧迫分"],
  ];
  const head = cols.map((c) => c[1]).join(",");
  const rows = state.items
    .filter((it) => state.selected.has(it.barcode))
    .sort((a, b) => (b.urgency_score || 0) - (a.urgency_score || 0))
    .map((it) => cols.map((c) => csvCell(it[c[0]])).join(","));
  const csv = "﻿" + head + "\n" + rows.join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const ts = new Date().toISOString().slice(0, 16).replace(/[:T-]/g, "");
  a.href = url;
  a.download = `restock_${state.selected.size}_${ts}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function markSelectedOrdered() {
  if (state.selected.size === 0) {
    alert("请先勾选要标记的行");
    return;
  }
  const now = new Date().toISOString();
  const newBatch = [];
  for (const bc of state.selected) {
    if (!(bc in state.ordered)) {
      state.ordered[bc] = { marked_at: now };
      newBatch.push(bc);
    }
  }
  if (newBatch.length > 0) state.orderedHistory.push(newBatch);
  state.selected.clear();
  saveOrdered();
  render();
}

function undoMarkRecent() {
  const batch = state.orderedHistory.pop();
  if (!batch || batch.length === 0) {
    alert("没有可撤销的标记");
    return;
  }
  for (const bc of batch) delete state.ordered[bc];
  saveOrdered();
  render();
}

function syncChipActive() {
  for (const btn of document.querySelectorAll("#pageRestock .rs-chip[data-filter]")) {
    const f = btn.dataset.filter;
    const v = btn.dataset.value;
    btn.classList.toggle("rs-chip--active", String(state.filter[f] ?? "") === String(v));
  }
  const v = state.filter.coverMax;
  $("rsCoverVal").textContent = v === null ? "已禁用" : `${v} 周`;
  $("rsCoverOff").classList.toggle("rs-chip--active", v === null);
  $("rsCoverRange").disabled = v === null;
  if (v !== null) $("rsCoverRange").value = String(v);

  // 供应商筛选标签
  const supEl = $("rsSupplierTag");
  if (supEl) {
    if (state.filter.supplier) {
      supEl.style.display = "";
      supEl.querySelector(".rs-supplier-tag-val").textContent = state.filter.supplier;
    } else {
      supEl.style.display = "none";
    }
  }

  // 已下单工具栏
  $("rsBtnExport").textContent = `↓ 导出选中 (${state.selected.size})`;
  $("rsBtnMark").textContent = `✓ 标已下单 (${state.selected.size})`;
  $("rsBtnExport").disabled = state.selected.size === 0;
  $("rsBtnMark").disabled = state.selected.size === 0;
  $("rsBtnUndo").disabled = state.orderedHistory.length === 0;
  const orderedN = Object.keys(state.ordered).length;
  const showOrderedChip = $("rsShowOrderedChip");
  showOrderedChip.textContent = state.filter.show_ordered
    ? `← 返回主表`
    : `✓ 显示已下单 (${orderedN})`;
  showOrderedChip.classList.toggle("rs-chip--active", state.filter.show_ordered);
}

function render() {
  const filtered = applyFilter(state.items);
  const sorted = applySort(filtered);
  const visible = sorted.slice(0, 500);
  const tbody = $("rsTbody");
  if (visible.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" class="empty">无匹配项</td></tr>';
  } else {
    tbody.innerHTML = visible.map(renderRow).join("");
    // checkbox 勾选状态
    for (const cb of tbody.querySelectorAll(".rs-check")) {
      cb.addEventListener("click", (e) => {
        e.stopPropagation();
        const bc = cb.dataset.bc;
        if (cb.checked) state.selected.add(bc);
        else state.selected.delete(bc);
        syncChipActive();
      });
    }
    // 供应商点击 → 设置筛选
    for (const sup of tbody.querySelectorAll(".rs-supplier[data-supplier]")) {
      sup.addEventListener("click", (e) => {
        e.stopPropagation();
        state.filter.supplier = sup.dataset.supplier;
        render();
      });
    }
    // 行点击 → 跳货号历史 (排除 checkbox / supplier 子元素)
    for (const tr of tbody.querySelectorAll(".rs-row")) {
      tr.addEventListener("click", (e) => {
        if (e.target.closest(".rs-check, .rs-supplier")) return;
        if (typeof window.historySearch === "function") {
          window.Alpine?.store("nav")?.switch("history");
          setTimeout(() => window.historySearch(tr.dataset.bc), 50);
        }
      });
    }
  }
  $("rsStatShowing").textContent =
    visible.length < sorted.length
      ? `显示前 ${visible.length} / ${sorted.length}`
      : `${sorted.length} 条`;

  for (const th of document.querySelectorAll(".rs-th-sort")) {
    const ind = th.querySelector(".rs-sort-ind");
    if (!ind) continue;
    if (th.dataset.sort === state.sort.key) {
      ind.textContent = state.sort.dir === "asc" ? "↑" : "↓";
      th.classList.add("rs-th-sort--active");
    } else {
      ind.textContent = "";
      th.classList.remove("rs-th-sort--active");
    }
  }
  syncChipActive();
}

async function load() {
  const tbody = $("rsTbody");
  tbody.innerHTML = '<tr><td colspan="12" class="empty">加载中…</td></tr>';
  try {
    const resp = await fetch("/analytics/list");
    const data = await resp.json();
    if (!data.ok) {
      tbody.innerHTML = `<tr><td colspan="12" class="empty">加载失败：${escapeHtml(data.msg || "")}</td></tr>`;
      return;
    }
    state.items = data.items;
    // 货到后自动 unmark
    autoClearOrderedByPurchase();
    $("rsStatTotal").textContent = `共 ${data.total} 个 SKU`;
    render();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="12" class="empty">网络错误：${escapeHtml(err.message)}</td></tr>`;
  }
}

function init() {
  if (!$("pageRestock")) return;

  // 启动时先把 localStorage 里 ordered 加载进来 (含 30 天过期清理)
  state.ordered = loadOrdered();

  $("rsRefresh").addEventListener("click", load);
  $("rsBtnExport").addEventListener("click", exportSelectedCsv);
  $("rsBtnMark").addEventListener("click", markSelectedOrdered);
  $("rsBtnUndo").addEventListener("click", undoMarkRecent);
  $("rsShowOrderedChip").addEventListener("click", () => {
    state.filter.show_ordered = !state.filter.show_ordered;
    state.selected.clear();
    render();
  });
  $("rsSupplierClear").addEventListener("click", () => {
    state.filter.supplier = null;
    render();
  });

  for (const btn of document.querySelectorAll("#pageRestock .rs-chip[data-filter]")) {
    btn.addEventListener("click", () => {
      const filter = btn.dataset.filter;
      const value = btn.dataset.value;
      state.filter[filter] = value;
      render();
    });
  }

  $("rsCoverRange").addEventListener("input", (e) => {
    state.filter.coverMax = Number(e.target.value);
    render();
  });

  $("rsCoverOff").addEventListener("click", () => {
    state.filter.coverMax = state.filter.coverMax === null ? 4 : null;
    render();
  });

  for (const th of document.querySelectorAll("#pageRestock .rs-th-sort")) {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort = { key, dir: "desc" };
      }
      render();
    });
  }
}

init();

window.Alpine?.store?.("nav")?.onFirstActivate?.("restock", load);
