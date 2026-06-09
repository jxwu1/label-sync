// 销售分析列表页（PR 5.2c + PR-FE-3 视觉换皮）
// 拉一次性全 SKU 指标，浏览器侧 filter + sort + 渲染。
"use strict";

import { escapeHtml, byId as $ } from "./shared.js";

const AUTO_CN = {
  new: "新品",
  seasonal: "季节性",
  declining: "衰退",
  stable: "稳定",
  unclassified: "未分类",
};

const state = {
  items: [],
  filter: { auto: "", manual: "", cust: "", warn: "" },
  sort: { key: "total_qty", dir: "desc" },
};


function fmt(n) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function customerEnd(item) {
  // 主导判定：哪一端 ≥ 80% 视为主导
  const total = (item.cn_qty || 0) + (item.fo_qty || 0);
  if (total === 0) return "none";
  const cnRatio = item.cn_qty / total;
  if (cnRatio >= 0.8) return "cn";
  if (cnRatio <= 0.2) return "fo";
  return "balanced";
}

function applyFilter(items) {
  return items.filter((it) => {
    if (state.filter.auto && it.auto_category !== state.filter.auto) return false;
    if (state.filter.manual === "__none" && it.manual_category) return false;
    if (state.filter.manual === "__set" && !it.manual_category) return false;
    if (state.filter.cust && customerEnd(it) !== state.filter.cust) return false;
    if (state.filter.warn === "1" && !it.is_grade_inconsistent) return false;
    return true;
  });
}

function applySort(items) {
  const { key, dir } = state.sort;
  const mul = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    // null 总放最后
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (av < bv) return -1 * mul;
    if (av > bv) return 1 * mul;
    return 0;
  });
}

// 用 SKU 总销量 + 趋势模拟一组 12 周 sparkline 值（无后端 timeline 时占位）
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
  return `<span class="sa-spark">` +
    values.map((v, i) => {
      const h = Math.max(2, Math.round((v / max) * 100));
      const op = (0.4 + (i / values.length) * 0.6).toFixed(2);
      return `<span class="sa-spark__bar" style="height:${h}%;background:${color};opacity:${op}"></span>`;
    }).join("") +
    `</span>`;
}

// 等级 1-10 → 4 档颜色：A 8-10 (accent) / B 4-7 (warn) / C 2-3 (info) / D 0-1 (error)
function gradeBadge(g) {
  if (g === null || g === undefined) return '<span class="sa-grade sa-grade--none">—</span>';
  const tier =
    g >= 8 ? "a" :
    g >= 4 ? "b" :
    g >= 2 ? "c" : "d";
  return `<span class="sa-grade sa-grade--${tier}">${g}</span>`;
}

function renderRow(it) {
  const autoBadge = it.auto_category
    ? `<span class="cat-badge cat-${escapeHtml(it.auto_category)}">${escapeHtml(AUTO_CN[it.auto_category] || it.auto_category)}</span>`
    : "—";
  const manualBadge = it.manual_category
    ? `<span class="cat-badge cat-manual">${escapeHtml(it.manual_category)}</span>`
    : "";
  const trend = it.trend_slope_pct_per_week;
  const trendCls = trend === null || trend === undefined ? "" : trend > 0 ? "sa-up" : trend < 0 ? "sa-down" : "";
  const trendArrow = trend === null || trend === undefined ? "" : trend > 0 ? "▲" : trend < 0 ? "▼" : "";
  const warn = it.is_grade_inconsistent
    ? '<span class="grade-warn" title="高等级低销量 / 低等级高销量">⚠</span>'
    : '<span class="sa-dot-empty">·</span>';
  const nameCell = it.name_zh
    ? `<span class="sa-model">${escapeHtml(it.model)}</span><span class="sa-name">${escapeHtml(it.name_zh)}</span>`
    : `<span class="sa-model">${escapeHtml(it.model)}</span>`;
  const sparkColor = trend > 0 ? "var(--accent)" : trend < 0 ? "var(--error)" : "var(--ink-3)";
  return `
    <tr class="sa-row" data-bc="${escapeHtml(it.barcode)}">
      <td class="sa-bc">${escapeHtml(it.barcode)}</td>
      <td class="sa-name-cell">${nameCell}</td>
      <td>${autoBadge}${manualBadge}</td>
      <td class="sa-num sa-num--bold">${fmt(it.total_qty)}</td>
      <td class="sa-num">${fmt(it.lifespan_days)}</td>
      <td class="sa-num ${trendCls}">${trendArrow ? `<span class="sa-trend-arrow">${trendArrow}</span>` : ""}${fmtPct(trend)}</td>
      <td class="sa-num">${sparkline(fakeBars(it), sparkColor)}</td>
      <td class="sa-num sa-cn">${fmt(it.cn_qty)}</td>
      <td class="sa-num sa-gr">${fmt(it.fo_qty)}</td>
      <td class="sa-num sa-grade-cell">${gradeBadge(it.manual_grade)}</td>
      <td class="sa-warn-cell">${warn}</td>
    </tr>
  `;
}

function render() {
  const filtered = applyFilter(state.items);
  const sorted = applySort(filtered);
  const visible = sorted.slice(0, 500); // 一次最多渲染 500 行
  const tbody = $("saTbody");
  if (visible.length === 0) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty">无匹配项</td></tr>';
  } else {
    tbody.innerHTML = visible.map(renderRow).join("");
    for (const tr of tbody.querySelectorAll(".sa-row")) {
      tr.addEventListener("click", () => {
        if (typeof window.historySearch === "function") {
          window.Alpine?.store("nav")?.switch("history");
          // 等 nav 切完
          setTimeout(() => window.historySearch(tr.dataset.bc), 50);
        }
      });
    }
  }
  $("saStatShowing").textContent =
    visible.length < sorted.length
      ? `显示前 ${visible.length} / ${sorted.length}（按当前筛选）`
      : `${sorted.length} 条`;

  // 同步表头排序指示
  for (const th of document.querySelectorAll(".sa-th-sort")) {
    const ind = th.querySelector(".sa-sort-ind");
    if (!ind) continue;
    if (th.dataset.sort === state.sort.key) {
      ind.textContent = state.sort.dir === "asc" ? "↑" : "↓";
      th.classList.add("sa-th-sort--active");
    } else {
      ind.textContent = "";
      th.classList.remove("sa-th-sort--active");
    }
  }
}

async function load() {
  const tbody = $("saTbody");
  tbody.innerHTML = '<tr><td colspan="11" class="empty">加载中…</td></tr>';
  try {
    const resp = await fetch("/analytics/list");
    const data = await resp.json();
    if (!data.ok) {
      tbody.innerHTML = `<tr><td colspan="11" class="empty">加载失败：${escapeHtml(data.msg || "")}</td></tr>`;
      return;
    }
    state.items = data.items;
    $("saStatTotal").textContent = `共 ${data.total} 个 SKU`;
    render();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty">网络错误：${escapeHtml(err.message)}</td></tr>`;
  }
}

function init() {
  if (!$("pageSalesAnalytics")) return;

  $("saRefresh").addEventListener("click", load);

  // chip 切换
  for (const btn of document.querySelectorAll(".sa-chip")) {
    btn.addEventListener("click", () => {
      const filter = btn.dataset.filter;
      const value = btn.dataset.value;
      state.filter[filter] = value;
      // 同组的 chip 取消激活，本身激活
      for (const b of document.querySelectorAll(`.sa-chip[data-filter="${filter}"]`)) {
        b.classList.toggle("sa-chip--active", b === btn);
      }
      render();
    });
  }

  // 列头点击排序（替代旧 dropdown）
  for (const th of document.querySelectorAll(".sa-th-sort")) {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        // 同列再点 → 翻方向
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        // 跨列 → 重置 desc
        state.sort = { key, dir: "desc" };
      }
      render();
    });
  }
}

init();

// 首次切到销售分析页时自动 load 一次（省去用户点刷新一步）
window.Alpine?.store?.("nav")?.onFirstActivate?.("sales_analytics", load);
