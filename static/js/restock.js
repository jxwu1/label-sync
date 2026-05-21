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

const state = {
  items: [],
  filter: {
    origin: "FOREIGN",
    view: "active",
    auto: "",
    coverMax: 4,
  },
  sort: { key: "urgency_score", dir: "desc" },
};

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
    if (state.filter.origin && it.origin !== state.filter.origin) return false;
    if (state.filter.view === "active") {
      if (it.is_truly_discontinued) return false;
      if (it.is_new_item) return false;
    } else if (state.filter.view === "new") {
      if (!it.is_new_item) return false;
    }
    if (state.filter.auto && it.auto_category !== state.filter.auto) return false;
    if (state.filter.coverMax !== null && state.filter.view === "active") {
      // null 代表 "无 snapshot 数据"，不当作"不缺货"过滤掉
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
  return `
    <tr class="rs-row" data-bc="${escapeHtml(it.barcode)}">
      <td class="rs-bc">${escapeHtml(it.barcode)}${disc}${newTag}</td>
      <td class="rs-name-cell">${nameCell}</td>
      <td>${originBadge(it.origin)}</td>
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

function updateExportLink() {
  const params = new URLSearchParams();
  const origin = state.filter.origin || "all";
  params.set("origin", origin);
  params.set("weeks", "26");
  params.set("limit", "5000");
  params.set("exclude_discontinued", state.filter.view === "all" ? "false" : "true");
  params.set("format", "csv");
  $("rsExportCsv").href = `/analytics/sales/top?${params.toString()}`;
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
}

function render() {
  const filtered = applyFilter(state.items);
  const sorted = applySort(filtered);
  const visible = sorted.slice(0, 500);
  const tbody = $("rsTbody");
  if (visible.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty">无匹配项</td></tr>';
  } else {
    tbody.innerHTML = visible.map(renderRow).join("");
    for (const tr of tbody.querySelectorAll(".rs-row")) {
      tr.addEventListener("click", () => {
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
  updateExportLink();
}

async function load() {
  const tbody = $("rsTbody");
  tbody.innerHTML = '<tr><td colspan="10" class="empty">加载中…</td></tr>';
  try {
    const resp = await fetch("/analytics/list");
    const data = await resp.json();
    if (!data.ok) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty">加载失败：${escapeHtml(data.msg || "")}</td></tr>`;
      return;
    }
    state.items = data.items;
    $("rsStatTotal").textContent = `共 ${data.total} 个 SKU`;
    render();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty">网络错误：${escapeHtml(err.message)}</td></tr>`;
  }
}

function init() {
  if (!$("pageRestock")) return;

  $("rsRefresh").addEventListener("click", load);

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
