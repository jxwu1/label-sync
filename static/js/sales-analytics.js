// 销售分析列表页（PR 5.2c）
// 拉一次性全 SKU 指标，浏览器侧 filter + sort + 渲染。
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
  filter: { auto: "", manual: "", cust: "", warn: "" },
  sort: { key: "total_qty", dir: "desc" },
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

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return String(n);
}

function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n}%`;
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

function renderRow(it) {
  const autoBadge = it.auto_category
    ? `<span class="cat-badge cat-${escapeHtml(it.auto_category)}">${escapeHtml(AUTO_CN[it.auto_category] || it.auto_category)}</span>`
    : "—";
  const manualBadge = it.manual_category
    ? `<span class="cat-badge cat-manual">${escapeHtml(it.manual_category)}</span>`
    : "";
  const trend = it.trend_slope_pct_per_week;
  const trendCls = trend === null || trend === undefined ? "" : trend > 0 ? "sa-up" : trend < 0 ? "sa-down" : "";
  const warn = it.is_grade_inconsistent
    ? '<span class="grade-warn">⚠</span>'
    : "";
  const nameCell = it.name_zh
    ? `${escapeHtml(it.model)}<br><span class="sa-name">${escapeHtml(it.name_zh)}</span>`
    : escapeHtml(it.model);
  return `
    <tr class="sa-row" data-bc="${escapeHtml(it.barcode)}">
      <td class="sa-bc">${escapeHtml(it.barcode)}</td>
      <td>${nameCell}</td>
      <td>${autoBadge}${manualBadge}</td>
      <td class="sa-num">${fmt(it.total_qty)}</td>
      <td class="sa-num">${fmt(it.lifespan_days)}</td>
      <td class="sa-num ${trendCls}">${fmtPct(trend)}</td>
      <td class="sa-num">${fmt(it.cn_qty)}</td>
      <td class="sa-num">${fmt(it.fo_qty)}</td>
      <td class="sa-num">${fmt(it.manual_grade)}</td>
      <td>${warn}</td>
    </tr>
  `;
}

function render() {
  const filtered = applyFilter(state.items);
  const sorted = applySort(filtered);
  const visible = sorted.slice(0, 500); // 一次最多渲染 500 行
  const tbody = $("saTbody");
  if (visible.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty">无匹配项</td></tr>';
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
}

async function load() {
  const tbody = $("saTbody");
  tbody.innerHTML = '<tr><td colspan="10" class="empty">加载中…</td></tr>';
  try {
    const resp = await fetch("/analytics/list");
    const data = await resp.json();
    if (!data.ok) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty">加载失败：${escapeHtml(data.msg || "")}</td></tr>`;
      return;
    }
    state.items = data.items;
    $("saStatTotal").textContent = `共 ${data.total} 个 SKU`;
    render();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty">网络错误：${escapeHtml(err.message)}</td></tr>`;
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

  // 排序
  $("saSort").addEventListener("change", () => {
    const [key, dir] = $("saSort").value.split(":");
    state.sort = { key, dir };
    render();
  });
}

init();
