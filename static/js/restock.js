// 补货决策面板（pageRestock）
// 数据源 /analytics/list（扩字段后包含 qty_total / weekly_velocity (件/周) /
// weekly_revenue (€/周, P1 起加入) / weeks_of_cover / margin_pct (P2 起加入) /
// last_purchase_unit_price / urgency_score / urgency_breakdown {velocity, cover,
// recency, margin, velocity_pctile, margin_pctile, margin_missing} /
// is_truly_discontinued / origin）。
//
// 紧迫分公式 (P2 起, E 方案): v_pctile*30 + cover*30 + recency*10 + m_pctile*30
// v_pctile 按 weekly_revenue 排名; m_pctile 按 margin_pct 排名; 缺 margin 时 m=0.
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
const SUPPLIER_OVERVIEW_HOT = 70;     // ≥70 紧迫分计入概览
const SUPPLIER_OVERVIEW_TOP = 5;       // 默认显示前 5 家

const OVERSTOCK_WEEKS = 20;  // weeks_of_cover >= 此值算压货
const HOT_URGENCY = 70;      // urgency_score >= 此值算紧急

const state = {
  items: [],
  filter: {
    origin: "FOREIGN",
    view: "active",
    coverMax: 4,
    supplier: null,        // 供应商筛选 (点击表里 supplier_id 触发)
    show_ordered: false,   // 显示已下单
    kpi: null,             // null | 'hot' | 'overstock' (KPI 条 toggle)
  },
  sort: { key: "urgency_score", dir: "desc" },
  selected: new Set(),     // 当前勾选的 barcode
  ordered: {},             // {barcode: {marked_at: ISO}}; 从 localStorage 加载
  orderedHistory: [],      // 撤销栈: 每次「标已下单」推入 [bc1, bc2, ...]
  supplierOverviewExpanded: false, // 概览展开 / 折叠
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
    tip += `\n  销额(30): ${bd.velocity}（€/周分位 ${(bd.velocity_pctile * 100).toFixed(0)}%）`;
    tip += `\n  库存(30): ${bd.cover}（${it.weeks_of_cover === null ? "无库存数据" : it.weeks_of_cover + " 周可撑"}）`;
    tip += `\n  距进货(10): ${bd.recency}（${fmtDays(it.last_purchase_days_ago)}）`;
    const marginInfo = bd.margin_missing
      ? "缺进货价"
      : `毛利 ${it.margin_pct}% / 分位 ${(bd.margin_pctile * 100).toFixed(0)}%`;
    tip += `\n  毛利(30): ${bd.margin}（${marginInfo}）`;
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

function marginCell(it) {
  const m = it.margin_pct;
  if (m === null || m === undefined) {
    return '<span class="rs-margin rs-margin--none" title="缺进货价 (待下次进货抓取)">—</span>';
  }
  const cls =
    m >= 50 ? "rs-margin--great" :
    m >= 30 ? "rs-margin--good" :
    m >= 10 ? "rs-margin--meh" :
    "rs-margin--bad";
  const pp = it.last_purchase_unit_price != null ? `进价 €${it.last_purchase_unit_price}` : "";
  const sp = it.sale_net_avg != null ? `售净 €${it.sale_net_avg}` : "";
  const tip = `毛利 ${m}%\n${sp}\n${pp}`;
  return `<span class="rs-margin ${cls}" title="${escapeHtml(tip)}">${m.toFixed(1)}%</span>`;
}

function realBars(it) {
  // 后端 weekly_qty_12w 是 12 周净销量数组, 最近一周在末尾
  return Array.isArray(it.weekly_qty_12w) && it.weekly_qty_12w.length === 12
    ? it.weekly_qty_12w
    : new Array(12).fill(0);
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

function _filterPredicate(it, opts = {}) {
  const isOrdered = it.barcode in state.ordered;
  if (state.filter.show_ordered) {
    if (!isOrdered) return false;
    return true;
  }
  if (isOrdered) return false;
  if (state.filter.origin && it.origin !== state.filter.origin) return false;
  if (!opts.skipSupplier && state.filter.supplier && it.supplier_id !== state.filter.supplier) return false;
  if (state.filter.view === "active") {
    if (it.is_truly_discontinued) return false;
    if (it.is_new_item) return false;
  } else if (state.filter.view === "new") {
    if (!it.is_new_item) return false;
  }
  // KPI 模式覆盖 coverMax: 'hot' 只看 urgency>=70, 'overstock' 只看 cover>=20
  if (state.filter.kpi === "hot") {
    if ((it.urgency_score ?? -1) < HOT_URGENCY) return false;
  } else if (state.filter.kpi === "overstock") {
    if (it.weeks_of_cover === null || it.weeks_of_cover === undefined) return false;
    if (it.weeks_of_cover < OVERSTOCK_WEEKS) return false;
  } else if (state.filter.coverMax !== null && state.filter.view === "active") {
    // null = 无 snapshot 数据, 不当 "不缺货" 过滤
    if (it.weeks_of_cover !== null && it.weeks_of_cover !== undefined
        && it.weeks_of_cover > state.filter.coverMax) return false;
  }
  return true;
}

function applyFilter(items) {
  return items.filter((it) => _filterPredicate(it));
}

function applyFilterExceptSupplier(items) {
  return items.filter((it) => _filterPredicate(it, { skipSupplier: true }));
}

function applySort(items) {
  // 压货模式: 默认按"压货金额" = weekly_revenue × weeks_of_cover desc, 锁最多现金的在顶.
  // 解决"资金流通"痛点: 顶部 = 最该清的库存.
  // 用户点表头会切回 state.sort.key (sort key 改成非默认即取代).
  if (state.filter.kpi === "overstock" && state.sort.key === "urgency_score") {
    return [...items].sort((a, b) => {
      const lockedA = (a.weekly_revenue ?? 0) * (a.weeks_of_cover ?? 0);
      const lockedB = (b.weekly_revenue ?? 0) * (b.weeks_of_cover ?? 0);
      return lockedB - lockedA;
    });
  }
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
  const nameCell = it.name_zh
    ? `<span class="rs-model">${escapeHtml(it.model)}</span><span class="rs-name">${escapeHtml(it.name_zh)}</span>`
    : `<span class="rs-model">${escapeHtml(it.model)}</span>`;
  const trend = it.trend_slope_pct_per_week;
  const sparkColor = trend > 0 ? "var(--accent)" : trend < 0 ? "var(--error)" : "var(--ink-3)";
  const bars = realBars(it);
  const hasSparkData = bars.some((v) => v > 0);
  const sparkCell = hasSparkData
    ? sparkline(bars, sparkColor)
    : '<span class="rs-spark-empty" title="近 12 周无销售">—</span>';
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
      <td class="rs-num" title="周销额 = 折后净销售额 / 有销售周数 (近 26 周)">€${fmt(it.weekly_revenue, 1)}</td>
      <td class="rs-num">${marginCell(it)}</td>
      <td class="rs-num">${weeksOfCoverCell(it.weeks_of_cover)}</td>
      <td class="rs-num">${sparkCell}</td>
      <td class="rs-num">${fmtDays(it.last_purchase_days_ago)}</td>
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
    ["weekly_velocity", "周销 件"],
    ["weekly_revenue", "周销额 €"],
    ["margin_pct", "毛利 %"],
    ["last_purchase_unit_price", "上次进价 €"],
    ["weeks_of_cover", "可撑周数"],
    ["last_purchase_days_ago", "距上次进货 (天)"],
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

const BUNDLE_HOT_THRESHOLD = 70;
const BUNDLE_FALLBACK_FLOOR = 30;
const BUNDLE_TARGET_COUNT = 20;

function _bundleCandidates() {
  // 当前 filter 后, 按 urgency_score desc 内部排序 (不依赖 UI sort).
  // 行为分两态:
  //   - supplier filter 已选 → "凑单模式": 取该 supplier 内 score>=70 全部
  //     (不 cap; 该 supplier 内 SKU 数自然有上限, 一单凑齐方便)
  //   - 无 supplier filter → "扫描模式": 强制 cap 在 BUNDLE_TARGET_COUNT
  //     防止 876+ 个 ≥70 全选拍上去 (按 default filter, FOREIGN/active/cover<=4
  //     的 ≥70 在线上有 876 个)
  // 不足 BUNDLE_TARGET_COUNT 时 fallback top N, 跳过 <30 避免凑死货.
  const filtered = applyFilter(state.items);
  const sortedByUrgency = [...filtered].sort(
    (a, b) => (b.urgency_score ?? -Infinity) - (a.urgency_score ?? -Infinity)
  );
  const hot = sortedByUrgency.filter(
    (it) => (it.urgency_score ?? -1) >= BUNDLE_HOT_THRESHOLD
  );
  const inSupplierMode = Boolean(state.filter.supplier);

  if (hot.length >= BUNDLE_TARGET_COUNT) {
    const picks = inSupplierMode ? hot : hot.slice(0, BUNDLE_TARGET_COUNT);
    return { picks, hotMode: true, capped: !inSupplierMode };
  }
  const fallback = sortedByUrgency
    .filter((it) => (it.urgency_score ?? -1) >= BUNDLE_FALLBACK_FLOOR)
    .slice(0, BUNDLE_TARGET_COUNT);
  return { picks: fallback, hotMode: false, capped: false };
}

function smartBundleSelect() {
  const { picks, hotMode } = _bundleCandidates();
  if (picks.length === 0) {
    alert("当前筛选范围内没有紧迫分 ≥30 的 SKU, 没东西可凑");
    return;
  }
  // 清空重选 (用户决策: 简单可预测)
  state.selected = new Set(picks.map((it) => it.barcode));
  render();
  const mode = hotMode ? `≥${BUNDLE_HOT_THRESHOLD} 全选` : `top ${BUNDLE_TARGET_COUNT}`;
  console.log(`[smartBundle] 选了 ${picks.length} 个 (${mode})`);
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

function _supplierSummary() {
  // 当前筛选 (忽略 supplier filter) 后, 按 urgency_score >= SUPPLIER_OVERVIEW_HOT
  // 的 SKU 数 group by supplier_id, 降序排列.
  const pool = applyFilterExceptSupplier(state.items);
  const hot = pool.filter(
    (it) => it.supplier_id && (it.urgency_score ?? -1) >= SUPPLIER_OVERVIEW_HOT
  );
  const byS = new Map();
  for (const it of hot) {
    const key = it.supplier_id;
    if (!byS.has(key)) byS.set(key, { supplier_id: key, count: 0, max: 0 });
    const e = byS.get(key);
    e.count += 1;
    if (it.urgency_score > e.max) e.max = it.urgency_score;
  }
  return Array.from(byS.values()).sort((a, b) => b.count - a.count);
}

function renderSupplierSummary() {
  const root = $("rsSupplierOverview");
  if (!root) return;
  const all = _supplierSummary();
  if (all.length === 0) {
    root.innerHTML = '<div class="rs-sup-empty">当前范围内没有紧迫分 ≥70 的 SKU</div>';
    return;
  }
  const maxCount = Math.max(...all.map((s) => s.count));
  const show = state.supplierOverviewExpanded ? all : all.slice(0, SUPPLIER_OVERVIEW_TOP);
  const hidden = all.length - show.length;

  const rows = show.map((s) => {
    const pct = Math.round((s.count / maxCount) * 100);
    const isActive = state.filter.supplier === s.supplier_id;
    return `
      <button class="rs-sup-row${isActive ? " rs-sup-row--active" : ""}"
              data-supplier="${escapeHtml(s.supplier_id)}"
              title="点击进入凑单模式: 筛 ${escapeHtml(s.supplier_id)} 全部 SKU">
        <span class="rs-sup-name">${escapeHtml(s.supplier_id)}</span>
        <span class="rs-sup-bar"><span class="rs-sup-bar-fill" style="width:${pct}%"></span></span>
        <span class="rs-sup-count">${s.count}</span>
        <span class="rs-sup-max">max ${s.max.toFixed(1)}</span>
      </button>
    `;
  }).join("");

  const expandBtn = hidden > 0
    ? `<button class="rs-sup-expand" id="rsSupExpand">↓ 展开剩余 ${hidden} 家</button>`
    : state.supplierOverviewExpanded && all.length > SUPPLIER_OVERVIEW_TOP
      ? `<button class="rs-sup-expand" id="rsSupExpand">↑ 折叠</button>`
      : "";

  root.innerHTML = `
    <div class="rs-sup-hd">🔥 紧迫供应商 (≥${SUPPLIER_OVERVIEW_HOT}, 共 ${all.length} 家)</div>
    <div class="rs-sup-list">${rows}</div>
    ${expandBtn}
  `;

  for (const btn of root.querySelectorAll(".rs-sup-row[data-supplier]")) {
    btn.addEventListener("click", () => {
      state.filter.supplier = btn.dataset.supplier;
      state.filter.coverMax = null; // 凑单模式
      render();
    });
  }
  const exp = $("rsSupExpand");
  if (exp) {
    exp.addEventListener("click", () => {
      state.supplierOverviewExpanded = !state.supplierOverviewExpanded;
      renderSupplierSummary();
    });
  }
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

  // 智能凑单按钮预览数
  const { picks: bundlePicks, hotMode, capped } = _bundleCandidates();
  const bundleBtn = $("rsBtnBundle");
  if (bundleBtn) {
    let tag;
    if (hotMode && capped) tag = `top${BUNDLE_TARGET_COUNT}/扫描`;
    else if (hotMode) tag = `≥70 凑单`;
    else tag = `top${BUNDLE_TARGET_COUNT}`;
    bundleBtn.textContent = `✓ 智能凑单 (${bundlePicks.length}, ${tag})`;
    bundleBtn.disabled = bundlePicks.length === 0;
    if (capped) {
      bundleBtn.title = `未选供应商: 自动 cap 在 top ${BUNDLE_TARGET_COUNT} 防止全选. 选具体供应商进入凑单模式后才不 cap.`;
    } else if (hotMode) {
      bundleBtn.title = `凑单模式 (供应商=${state.filter.supplier}): 紧迫分 ≥${BUNDLE_HOT_THRESHOLD} 的 SKU 全选`;
    } else {
      bundleBtn.title = `紧迫分 ≥${BUNDLE_HOT_THRESHOLD} 不足 ${BUNDLE_TARGET_COUNT} 个, 退到 top ${BUNDLE_TARGET_COUNT} (≥${BUNDLE_FALLBACK_FLOOR} 才参与, 避免凑死货)`;
    }
  }
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
    // 供应商点击 → 进入"凑单模式": 设供应商筛选 + 自动禁用 cover filter
    // (凑单时要看全这家所有 SKU, 不只是缺货的; 想再筛缺货自己开滑块)
    for (const sup of tbody.querySelectorAll(".rs-supplier[data-supplier]")) {
      sup.addEventListener("click", (e) => {
        e.stopPropagation();
        state.filter.supplier = sup.dataset.supplier;
        state.filter.coverMax = null;  // 自动关闭缺货过滤
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
  const baseStat = visible.length < sorted.length
    ? `显示前 ${visible.length} / ${sorted.length}`
    : `${sorted.length} 条`;
  const sortHint = state.filter.kpi === "overstock" && state.sort.key === "urgency_score"
    ? " · 按压货金额 (周销额×可撑周) desc"
    : "";
  $("rsStatShowing").textContent = baseStat + sortHint;

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
  renderSupplierSummary();
  renderKpi();
}

function renderKpi() {
  // 全表统计仅看活跃 SKU (排除 truly_discontinued + new), 跟紧迫分计算口径一致
  const pool = state.items.filter((it) => !it.is_truly_discontinued && !it.is_new_item);
  const total = pool.length;
  const hot = pool.filter((it) => (it.urgency_score ?? -1) >= HOT_URGENCY).length;
  const over = pool.filter(
    (it) => it.weeks_of_cover !== null && it.weeks_of_cover !== undefined
            && it.weeks_of_cover >= OVERSTOCK_WEEKS,
  ).length;
  const noMargin = pool.filter((it) => it.margin_pct === null || it.margin_pct === undefined).length;
  const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  set("rsKpiTotal", total.toLocaleString());
  set("rsKpiHot", hot.toLocaleString());
  set("rsKpiOverstock", over.toLocaleString());
  set("rsKpiNoMargin", noMargin.toLocaleString());
  const pct = total > 0 ? Math.round(over * 100 / total) : 0;
  set("rsKpiOverstockPct", `(${pct}%)`);
  $("rsKpiHotBtn")?.classList.toggle("rs-kpi__btn--active", state.filter.kpi === "hot");
  $("rsKpiOverstockBtn")?.classList.toggle("rs-kpi__btn--active", state.filter.kpi === "overstock");
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
  $("rsBtnBundle").addEventListener("click", smartBundleSelect);
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

  // KPI 条 toggle: 紧急 / 压货 (互斥, 再点取消)
  $("rsKpiHotBtn")?.addEventListener("click", () => {
    state.filter.kpi = state.filter.kpi === "hot" ? null : "hot";
    render();
  });
  $("rsKpiOverstockBtn")?.addEventListener("click", () => {
    state.filter.kpi = state.filter.kpi === "overstock" ? null : "overstock";
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
