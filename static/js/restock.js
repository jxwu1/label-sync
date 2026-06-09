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
const SKIP_SUPPRESS_DAYS = 14;   // 与后端 restock_decisions.SKIP_SUPPRESS_DAYS 对齐

const state = {
  items: [],
  filter: {
    origin: "FOREIGN",     // 来源分段控件 ""=全部 / FOREIGN / CN / unknown
    views: { active: true, new: false, disc: false }, // 视图多选 (活跃/新品/含停用)
    band: "all",           // 状态 band 过滤: all | urgent(≥70) | watch(40-69) | ok(<40) | flagged
    coverMax: 4,           // 可撑阈值筛选 (cf 弹层); null = 不限
    coverThreshold: 4,     // 可撑微条安全周转阈值 (着色用, 列头齿轮/行内 knob 调)
    supplier: null,        // 供应商筛选 (点击芯片/表里 supplier_id 触发)
    show_ordered: false,   // 已下单项默认隐藏 (无 UI toggle, 货到自动清)
    search: "",            // 模糊搜 supplier_id / model / barcode / name
  },
  sort: { key: "urgency_score", dir: "desc" },
  selected: new Set(),     // 当前勾选的 barcode
  ordered: {},             // {barcode: {marked_at: ISO}}; 从 localStorage 加载
  orderedHistory: [],      // 撤销栈: 每次「标已下单」推入 [bc1, bc2, ...]
  supplierOverviewExpanded: false, // 概览展开 / 折叠
  expandedBarcode: null,   // 当前展开 drawer 的 barcode (一次一个)
  editedQty: {},   // barcode -> 用户改后的 p98 数量(字符串); 不持久化, 刷新清空
  suppressed: {},   // barcode -> {skipped_at, reason, days_left}; 标「不进」后默认隐藏, 后端回流
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

// 紧迫分提示文案 (tooltip + drawer 复用)
function urgencyTip(it) {
  const score = it.urgency_score;
  const bd = it.urgency_breakdown;
  let tip = `紧迫分 ${score}`;
  if (bd) {
    const dv = bd.demand_validity;
    tip += `\n  销额(30): ${bd.velocity}（€/周分位 ${(bd.velocity_pctile * 100).toFixed(0)}%）`;
    const dvTag = (dv != null && dv < 1.0) ? ` · 长尾折扣×${dv}` : "";
    tip += `\n  库存(30): ${bd.cover}（${it.weeks_of_cover === null ? "无库存数据" : it.weeks_of_cover + " 周可撑"}${dvTag}）`;
    tip += `\n  距进货(10): ${bd.recency}（${fmtDays(it.last_purchase_days_ago)}${dvTag}）`;
    let marginInfo;
    if (bd.margin_missing) {
      marginInfo = "缺进货价";
    } else {
      const costTag = bd.margin_source === "master" ? " · 主档进价" : "";
      const priceTag = bd.margin_price_source === "master" ? " · 主档售价" : "";
      marginInfo = `毛利 ${it.margin_pct}% / 分位 ${(bd.margin_pctile * 100).toFixed(0)}%${costTag}${priceTag}`;
    }
    tip += `\n  毛利(30): ${bd.margin}（${marginInfo}）`;
    if (it.retail_qty_26w > 0) {
      tip += `\n  零售(展示): 26 周 ${it.retail_qty_26w} 件 / €${it.retail_revenue_26w}（未进算法）`;
    }
  }
  return tip;
}

// 表格紧迫分单元格: 进度条 + 数字 (设计稿 .urg)。4 维拆解移进 drawer。
function urgencyCell(it) {
  if (it.urgency_score === null || it.urgency_score === undefined) {
    return '<span class="rs-urg-num rs-urg-num--none">—</span>';
  }
  const score = it.urgency_score;
  const lvl = score >= 70 ? "high" : score >= 40 ? "mid" : "low";
  const w = Math.max(0, Math.min(100, score));
  return `<span class="rs-urg" title="${escapeHtml(urgencyTip(it))}">` +
    `<span class="rs-urg-bar"><span class="rs-urg-fill rs-urg-fill--${lvl}" style="width:${w}%"></span></span>` +
    `<span class="rs-urg-num rs-urg-num--${lvl}">${score}</span></span>`;
}

// drawer 紧迫分四段拆解 (销/库/距/利)
function scoreBreakdown(it) {
  const bd = it.urgency_breakdown;
  if (!bd) return "";
  const segs = [
    { val: bd.velocity ?? 0, max: 30, cls: "rs-score-seg--v", label: `销额 ${bd.velocity ?? 0}/30`, dot: "var(--accent)" },
    { val: bd.cover ?? 0,    max: 30, cls: "rs-score-seg--c", label: `库存 ${bd.cover ?? 0}/30`,    dot: "var(--info)" },
    { val: bd.recency ?? 0,  max: 10, cls: "rs-score-seg--r", label: `距进货 ${bd.recency ?? 0}/10`, dot: "var(--warn)" },
    { val: bd.margin ?? 0,   max: 30, cls: "rs-score-seg--m", label: `毛利 ${bd.margin ?? 0}/30`,    dot: "var(--success)" },
  ];
  const bars = segs.map((s) => {
    const fillPct = Math.max(0, Math.min(100, (s.val / s.max) * 100));
    const widthPct = s.max; // 段宽按总分占比 (销30 库30 距10 利30)
    return `<div class="rs-score-seg ${s.cls}" style="width:${widthPct}%;opacity:${(0.35 + fillPct / 100 * 0.65).toFixed(2)}" title="${escapeHtml(s.label)}"></div>`;
  }).join("");
  const legend = segs.map((s) =>
    `<span class="rs-score-legend-item"><span class="rs-score-legend-dot" style="background:${s.dot}"></span>${escapeHtml(s.label)}</span>`
  ).join("");
  return `<div class="rs-score-bar">${bars}</div><div class="rs-score-legend">${legend}</div>`;
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

// 可撑微条 (设计稿 .cover): 数字 + 轨道 + 填充 + 安全线 + hover 可拖 knob
const COVER_CAP = 13.0; // 微条满刻度 (周); 超过即 100%
function coverTone(w, T) {
  if (w === null || w === undefined) return "ok";
  if (w < T * 0.5) return "crit";
  if (w < T) return "low";
  if (w < T * 2) return "ok";
  return "high";
}
function coverCell(it) {
  const w = it.weeks_of_cover;
  if (w === null || w === undefined) return '<span class="rs-cover-num ok">—</span>';
  const T = state.filter.coverThreshold;
  const tone = coverTone(w, T);
  const fillPct = Math.min((w / COVER_CAP) * 100, 100);
  const safePct = Math.min((T / COVER_CAP) * 100, 100);
  return `<span class="rs-cover" data-w="${w}">` +
    `<span class="rs-cover-num ${tone}">${w.toFixed(1)}w</span>` +
    `<span class="rs-cover-track">` +
      `<span class="rs-cover-fill ${tone}" style="width:${fillPct.toFixed(1)}%"></span>` +
      `<span class="rs-cover-safe" style="left:${safePct.toFixed(1)}%"></span>` +
      `<span class="rs-cover-knob" style="left:${safePct.toFixed(1)}%"></span>` +
    `</span></span>`;
}
// 阈值变化只改 DOM 着色 + 安全线/knob 位置, 不整表重渲 (设计稿 setCoverThreshold)
function recolorCover() {
  const T = state.filter.coverThreshold;
  const safePct = Math.min((T / COVER_CAP) * 100, 100).toFixed(1) + "%";
  for (const c of document.querySelectorAll("#rsTbody .rs-cover")) {
    const w = parseFloat(c.dataset.w);
    const tone = coverTone(w, T);
    const num = c.querySelector(".rs-cover-num");
    const fill = c.querySelector(".rs-cover-fill");
    for (const el of [num, fill]) {
      if (el) { el.classList.remove("crit", "low", "ok", "high"); el.classList.add(tone); }
    }
    for (const s of c.querySelectorAll(".rs-cover-safe, .rs-cover-knob")) s.style.left = safePct;
  }
}

function marginCell(it) {
  const m = it.margin_pct;
  if (m === null || m === undefined) {
    return '<span class="rs-margin rs-margin--none" title="缺进货价或售价">—</span>';
  }
  const cls =
    m >= 50 ? "rs-margin--great" :
    m >= 30 ? "rs-margin--good" :
    m >= 10 ? "rs-margin--meh" :
    "rs-margin--bad";
  // 兜底来源标记:
  // cost: master = ERP 总档进价 (精度低), purchase = 实际成交
  // price: master = 主档售价 (稳定), events = 批发事件均价
  const costIsMaster = it.margin_source === "master";
  const priceIsMaster = it.margin_price_source === "master";
  const cost = costIsMaster ? it.master_stock_price_eur : it.last_purchase_unit_price;
  const costLabel = costIsMaster ? "主档参考进价" : "上次进价";
  const salePrice = priceIsMaster ? it.master_sale_price_eur : it.sale_net_avg;
  const saleLabel = priceIsMaster ? "主档售价" : "批发均价";
  const tip = `毛利 ${m}%\n${saleLabel} €${salePrice}\n${costLabel} €${cost}`;
  // 任一端用兜底/参考价就标 ~
  const suffix = (costIsMaster || priceIsMaster)
    ? '<span class="rs-margin__src" title="部分使用主档参考价, 非实际成交">~</span>'
    : "";
  return `<span class="rs-margin ${cls}" title="${escapeHtml(tip)}">${m.toFixed(1)}%${suffix}</span>`;
}

function realBars(it) {
  // 后端 weekly_qty_12w 是 12 周净销量数组, 最近一周在末尾
  return Array.isArray(it.weekly_qty_12w) && it.weekly_qty_12w.length === 12
    ? it.weekly_qty_12w
    : new Array(12).fill(0);
}

// SVG polyline sparkline (设计稿 .spark-cell), viewBox 60×20, 12 周点
function sparkline(values, color) {
  const max = Math.max(...values, 1);
  const n = values.length;
  const pts = values.map((v, i) => {
    const x = (n > 1 ? (i / (n - 1)) * 56 : 28) + 2;
    const y = 18 - (v / max) * 16; // 2(顶) .. 18(底)
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="rs-spark-cell" viewBox="0 0 60 20"><polyline points="${pts}" stroke="${color}" /></svg>`;
}

// 盈亏列 badge (行内简版; drawer 有详版)
function profitBadgeRow(it) {
  const rp = it.realized_profit_eur;
  const inv = it.inventory_cost_value_eur ?? 0;
  if (rp === null || rp === undefined) {
    return '<span class="rs-profit-badge rs-profit-badge--unknown" title="无 cost 数据">缺成本</span>';
  }
  if (rp > 0) return '<span class="rs-profit-badge rs-profit-badge--good">已回本</span>';
  if (rp + inv > 0) return '<span class="rs-profit-badge rs-profit-badge--mid">压货中</span>';
  return '<span class="rs-profit-badge rs-profit-badge--bad">未回本</span>';
}

function _filterPredicate(it, opts = {}) {
  const isOrdered = it.barcode in state.ordered;
  if (state.filter.show_ordered) {
    if (!isOrdered) return false;
    return true;
  }
  if (isOrdered) return false;
  // 决策回流: 非「已跳过」band 隐藏被抑制项; 「已跳过」band 只看被抑制项
  const isSuppressed = it.barcode in state.suppressed;
  if (state.filter.band === "skipped") {
    if (!isSuppressed) return false;
  } else if (isSuppressed) {
    return false;
  }
  if (state.filter.origin && it.origin !== state.filter.origin) return false;
  if (!opts.skipSupplier && state.filter.supplier && it.supplier_id !== state.filter.supplier) return false;
  // 搜索框: 输入命中 supplier_id / barcode / model / name (任一含子串即留)
  if (state.filter.search) {
    const q = state.filter.search.toLowerCase();
    const hay = `${it.supplier_id ?? ''} ${it.barcode ?? ''} ${it.model ?? ''} ${it.name_zh ?? ''}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  // 视图多选: 活跃(非停用非新品) / 新品 / 含停用; 命中任一启用视图即留
  const vw = state.filter.views;
  const isActive = !it.is_truly_discontinued && !it.is_new_item;
  const viewMatch =
    (vw.active && isActive) ||
    (vw.new && it.is_new_item) ||
    (vw.disc && it.is_truly_discontinued);
  if (!viewMatch) return false;
  // 状态 band 过滤 (urgency 区间 / 已标记)
  const score = it.urgency_score ?? -1;
  switch (state.filter.band) {
    case "urgent": if (score < 70) return false; break;
    case "watch":  if (score < 40 || score >= 70) return false; break;
    case "ok":     if (score >= 40) return false; break;
    case "flagged": if (!state.selected.has(it.barcode)) return false; break;
    default: break; // all
  }
  // 可撑阈值筛选 (cf 弹层); null = 不限; 仅活跃视图下有库存数据的过滤
  if (state.filter.coverMax !== null && vw.active) {
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
  const name = it.name_zh || it.model || "";
  const nameCell =
    `<div class="rs-sku">` +
    `<span class="rs-model" title="${escapeHtml(it.model || "")}">${escapeHtml(name)}</span>` +
    `<button class="rs-bc-link rs-name" data-bc="${escapeHtml(it.barcode)}" title="点开货号历史">${escapeHtml(it.barcode)}</button>` +
    `</div>`;
  const trend = it.trend_slope_pct_per_week;
  const sparkColor = trend > 0 ? "var(--success)" : trend < 0 ? "var(--error)" : "var(--ink-3)";
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
  const sup = state.suppressed[it.barcode];
  const skippedTag = sup
    ? `<span class="rs-tag rs-tag--skip" title="已跳过 ${escapeHtml((sup.skipped_at || '').slice(0,10))}${sup.reason ? ' · ' + escapeHtml(sup.reason) : ''} · 剩 ${sup.days_left ?? '?'} 天">已跳过</span>`
    : "";
  const stockoutBadge = it.stockout_zero_weeks_last8 > 0
    ? `<span class="rs-badge-stockout">⚠ 近 ${it.stockout_zero_weeks_last8} 周零销疑因缺货</span>`
    : "";
  const flagged = state.selected.has(it.barcode) ? " is-flagged" : "";
  const flagCol = `<span class="rs-flag${flagged}" data-bc="${escapeHtml(it.barcode)}" title="⚑ 标记 / 取消">⚑</span>`;
  const supplierCell = it.supplier_id
    ? `${originBadge(it.origin)}<button class="rs-supplier" data-supplier="${escapeHtml(it.supplier_id)}" title="筛选同供应商 SKU">${escapeHtml(it.supplier_id)}</button>`
    : `${originBadge(it.origin)}<span class="rs-supplier rs-supplier--none">—</span>`;
  const expanded = state.expandedBarcode === it.barcode ? " rs-row--expanded" : "";
  return `
    <tr class="rs-row${expanded}" data-bc="${escapeHtml(it.barcode)}">
      <td class="rs-check-cell">${flagCol}</td>
      <td>${urgencyCell(it)}</td>
      <td>${nameCell}${disc}${newTag}${orderedTag}${skippedTag}${stockoutBadge}</td>
      <td>${supplierCell}</td>
      <td class="rs-num">${fmt(it.qty_total)}</td>
      <td class="rs-num">${coverCell(it)}</td>
      <td class="rs-num">${fmt(it.weekly_velocity, 1)}</td>
      <td class="rs-num" title="周销额 = 折后净销售额 / 有销售周数 (近 26 周)">€${fmt(it.weekly_revenue, 1)}</td>
      <td class="rs-num">${marginCell(it)}</td>
      <td>${sparkCell}</td>
      <td>${profitBadgeRow(it)}</td>
      <td class="rs-num">${fmtDays(it.last_purchase_days_ago)}</td>
      <td class="rs-num rs-rec-g rs-rec-sep" title="${it.restock_source || '—'}"><span class="rs-rec-v rs-rec-v--hi">${it.restock_qty_p50 != null ? it.restock_qty_p50 : '—'}</span></td>
      <td class="rs-num rs-rec-g" title="安全量"><input type="number" inputmode="numeric" class="rs-qty-input" data-bc="${escapeHtml(it.barcode)}" value="${escapeHtml(getBosonQty(it))}"></td>
      <td class="rs-num rs-rec-g"><span class="rs-rec-v" style="color:var(--ink-2)">${it.last_purchase_qty != null ? it.last_purchase_qty : '—'}</span></td>
    </tr>
  `;
}

function fmtEurOrDash(v, d = 2) {
  return (v === null || v === undefined) ? "—" : `€${fmt(v, d)}`;
}

// drawer DOM: 财务快照 + 库存 + 销售 26w + 紧迫分四维 + 单条操作按钮.
function renderDrawer(it) {
  const bd = it.urgency_breakdown;
  const dv = bd?.demand_validity;
  const dvSuffix = (dv != null && dv < 1.0) ? ` <span class="rs-dv-tag" title="长尾活跃度折扣 (n_active_weeks=${it.n_active_weeks_26w}/4)">×${dv}</span>` : "";
  // 零售价行: observed vs estimate 并排展示, 校对 ×2 假设
  const rpObs = it.retail_price_observed;
  const rpEst = it.retail_price_estimate;
  let retailPriceLine;
  if (rpObs != null && rpEst != null) {
    retailPriceLine = `零售价 <b>${fmtEurOrDash(rpObs)}</b> <span class="rs-drawer-muted">(实际 ${it.retail_qty_26w} 笔均价)</span> · 估算 ${fmtEurOrDash(rpEst)} (×2)`;
  } else if (rpObs != null) {
    retailPriceLine = `零售价 <b>${fmtEurOrDash(rpObs)}</b> <span class="rs-drawer-muted">(实际)</span>`;
  } else if (rpEst != null) {
    retailPriceLine = `零售价 <b>${fmtEurOrDash(rpEst)}</b> <span class="rs-drawer-muted">(批发×2 估算)</span>`;
  } else {
    retailPriceLine = `零售价 —`;
  }
  // 累计盈亏状态: 实现利润 + 库存价值 决定 已回本/压货中/亏损
  let profitBadge, profitLine;
  const rp = it.realized_profit_eur;
  const inv = it.inventory_cost_value_eur ?? 0;
  if (rp === null || rp === undefined) {
    profitBadge = '<span class="rs-profit-badge rs-profit-badge--unknown">缺成本</span>';
    profitLine = '<span class="rs-drawer-muted">无 cost 数据, 无法计算</span>';
  } else if (rp > 0) {
    profitBadge = '<span class="rs-profit-badge rs-profit-badge--good">💚 已回本</span>';
    profitLine = `实现利润 <b>+€${fmt(rp, 0)}</b>`;
  } else if (rp + inv > 0) {
    profitBadge = '<span class="rs-profit-badge rs-profit-badge--mid">🟡 压货中</span>';
    profitLine = `实现利润 <b>€${fmt(rp, 0)}</b> · 库存能补 <b>€${fmt(inv, 0)}</b> 回本`;
  } else {
    profitBadge = '<span class="rs-profit-badge rs-profit-badge--bad">🔴 账面亏损</span>';
    profitLine = `实现利润 <b>€${fmt(rp, 0)}</b> + 库存 <b>€${fmt(inv, 0)}</b> 仍亏 <b>€${fmt(-(rp + inv), 0)}</b>`;
  }
  // 净现金流并列显示 (2026-05-23 A 方案): 大库存差异时 FIFO 乐观, cashflow 保守
  const ncf = it.net_cashflow_eur;
  const imb = it.inventory_imbalance_pct;
  let cashflowLine = "";
  if (ncf !== null && ncf !== undefined) {
    const imbWarn = (imb != null && imb > 30)
      ? ` <span class="rs-trunc-warn" title="进销库存差额 ${imb}% > 30%, FIFO 实现利润可能高估, 实际请看净现金流">⚠️ 不平 ${imb}%</span>`
      : '';
    cashflowLine = `<div>净现金流 <b>${ncf >= 0 ? '+' : ''}€${fmt(ncf, 0)}</b>${imbWarn}</div>`;
  }
  const truncWarn = it.is_history_truncated
    ? ' <span class="rs-trunc-warn" title="该 SKU 第一笔事件早于 ETL 窗口起点 (2021-06-01), 更早期的进/销记录未纳入, 实际累计利润可能与此估算有出入">⚠️ 历史可能不全</span>'
    : '';
  const firstEventLine = it.first_event_at
    ? `<div class="rs-drawer-muted">首笔事件 ${it.first_event_at}${truncWarn}</div>`
    : '';
  // cover/recency 受 dv 折扣的两项, 显示原始值
  const coverScore = bd ? `${bd.cover}${dvSuffix}` : "—";
  const recencyScore = bd ? `${bd.recency}${dvSuffix}` : "—";
  const velocityScore = bd ? `${bd.velocity}` : "—";
  const marginScore = bd ? `${bd.margin}` : "—";
  const skipDisabled = it.is_truly_discontinued ? 'disabled' : '';
  return `
    <tr class="rs-drawer-row" data-bc="${escapeHtml(it.barcode)}">
      <td colspan="15" class="rs-drawer-cell">
        <div class="rs-drawer">
          <div class="rs-drawer-grid">
            <section class="rs-drawer-sec">
              <h4>💰 财务快照</h4>
              <div>批发价 <b>${fmtEurOrDash(it.master_sale_price_eur ?? it.sale_net_avg)}</b> <span class="rs-drawer-muted">(主档)</span></div>
              <div>${retailPriceLine}</div>
              <div>单件进价 <b>${fmtEurOrDash(it.last_purchase_unit_price ?? it.master_stock_price_eur)}</b> <span class="rs-drawer-muted">(${it.margin_source === 'master' ? '主档参考' : it.margin_source === 'purchase' ? '上次成交' : '—'})</span></div>
              <div>单件毛利率 <b>${it.margin_pct != null ? it.margin_pct + '%' : '—'}</b></div>
            </section>
            <section class="rs-drawer-sec">
              <h4>📦 库存</h4>
              <div>当前库存 <b>${fmt(it.qty_total)} 件</b></div>
              <div>库存可销售金额 <b>${fmtEurOrDash(it.inventory_sale_value_eur)}</b></div>
              <div>库存成本 <b>${fmtEurOrDash(it.inventory_cost_value_eur)}</b></div>
              <div>压舱率 <b>${it.weeks_of_cover != null ? it.weeks_of_cover.toFixed(1) + ' 周可撑' : '—'}</b></div>
            </section>
            <section class="rs-drawer-sec">
              <h4>💵 累计盈亏 ${profitBadge}</h4>
              <div>累计投入 <b>${fmtEurOrDash(it.lifetime_invested_eur)}</b> <span class="rs-drawer-muted">(${fmt(it.lifetime_purchase_qty)} 件)</span></div>
              <div>累计销售 <b>€${fmt(it.lifetime_sale_revenue_eur, 0)}</b> <span class="rs-drawer-muted">(${fmt(it.lifetime_sale_qty)} 件)</span></div>
              <div>${profitLine}</div>
              ${cashflowLine}
              ${firstEventLine}
            </section>
            <section class="rs-drawer-sec">
              <h4>📊 销售 (26 周)</h4>
              <div>批发 <b>${fmt(it.total_qty)} 件</b> / €${fmt(it.weekly_revenue * 26, 0)} <span class="rs-drawer-muted">(${fmt(it.n_active_weeks_26w)} 活跃周)</span></div>
              <div>零售 <b>${fmt(it.retail_qty_26w)} 件</b> / €${fmt(it.retail_revenue_26w, 0)} <span class="rs-drawer-muted">(不进算法)</span></div>
              <div>历史零售占比 <b>${(it.retail_share_26w * 100).toFixed(0)}%</b></div>
              <div>周销速 <b>${fmt(it.weekly_velocity, 2)} 件/周</b> · 周销额 <b>€${fmt(it.weekly_revenue, 2)}/周</b></div>
            </section>
            <section class="rs-drawer-sec">
              <h4>🎯 紧迫分 <b>${it.urgency_score ?? '—'}</b></h4>
              ${scoreBreakdown(it)}
              <div>销额(30): <b>${velocityScore}</b></div>
              <div>库存(30): <b>${coverScore}</b></div>
              <div>距进货(10): <b>${recencyScore}</b></div>
              <div>毛利(30): <b>${marginScore}</b></div>
            </section>
          </div>
          <div class="rs-drawer-actions">
            <button class="btn btn--primary rs-btn--ordered-single" data-bc="${escapeHtml(it.barcode)}">✓ 我已下单</button>
            <button class="btn btn--ghost rs-btn--skip-single" data-bc="${escapeHtml(it.barcode)}" ${skipDisabled}>✗ 跳过</button>
            <button class="btn btn--ghost rs-btn--close-drawer" style="margin-left:auto;">收起</button>
          </div>
        </div>
      </td>
    </tr>
  `;
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  const s = String(v);
  if (/[,"\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

const CSV_COLS = [
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
  ["restock_qty_p50", "推荐补货量 (p50)"],
  ["restock_qty_p98", "推荐补货量 (p98)"],
  ["last_purchase_qty", "上次进货量"],
];

// 取某行当前补货数量: 用户编辑值优先, 否则 p98 推荐量. 纯函数 (editedQty 显式传入).
function pickQty(it, editedQty) {
  const e = editedQty[it.barcode];
  return e !== undefined ? e : it.restock_qty_p98;
}

// input 初值 / 单行展示用: 读全局 state.editedQty.
function getBosonQty(it) {
  return pickQty(it, state.editedQty);
}

// 行集 → boson 导入文本: 多行 "型号,数量". 跳过型号缺失 / 数量非数字 / 数量<=0.
// 纯函数 (editedQty 显式传入), 返回 {text, kept, skipped}.
function buildBosonText(items, editedQty) {
  const lines = [];
  let skipped = 0;
  for (const it of items) {
    const model = it.model;
    const raw = pickQty(it, editedQty);
    const num = Number(raw);
    if (!model || !Number.isFinite(num)) { skipped++; continue; }
    const qty = Math.round(num);
    if (qty <= 0) { skipped++; continue; }
    lines.push(`${model},${qty}`);
  }
  return { text: lines.join("\n"), kept: lines.length, skipped };
}

function _downloadRestockCsv(items, namePrefix) {
  const head = CSV_COLS.map((c) => c[1]).join(",") + ",ERP导入 (型号\\,数量)";
  const rows = items.map((it) => {
    const base = CSV_COLS.map((c) => csvCell(it[c[0]])).join(",");
    const qty = it.restock_qty_p98 != null ? it.restock_qty_p98 : "";
    const mdl = String(it.model || "");
    const erp = mdl && qty ? `"=""${mdl},${qty}"""` : "";
    return base + "," + erp;
  });
  const csv = "﻿" + head + "\n" + rows.join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const ts = new Date().toISOString().slice(0, 16).replace(/[:T-]/g, "");
  a.href = url;
  a.download = `${namePrefix}_${items.length}_${ts}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// 批量栏「导出选中」: 勾选的行
function exportSelectedCsv() {
  if (state.selected.size === 0) {
    alert("请先勾选要导出的行");
    return;
  }
  const selected = state.items
    .filter((it) => state.selected.has(it.barcode))
    .sort((a, b) => (b.urgency_score || 0) - (a.urgency_score || 0));
  _downloadRestockCsv(selected, "restock");
}

// 「更多」菜单「导出 CSV / 生成采购单」: 当前过滤+排序后的可见行 (上限 500, 与表格一致)
function exportVisibleCsv() {
  const visible = applySort(applyFilter(state.items)).slice(0, 500);
  if (visible.length === 0) {
    alert("当前筛选范围内没有可导出的行");
    return;
  }
  _downloadRestockCsv(visible, "restock_visible");
}

// 复制 boson 格式到剪贴板: 主路径 navigator.clipboard, 失败回退 textarea+execCommand.
async function copyBosonText(items) {
  const { text, kept, skipped } = buildBosonText(items, state.editedQty);
  if (kept === 0) {
    alert("没有可复制的行" + (skipped ? `（${skipped} 行因型号缺失或数量无效跳过）` : ""));
    return;
  }
  const msg = `已复制 ${kept} 行` + (skipped ? `，${skipped} 行因型号缺失或数量无效跳过` : "");
  try {
    await navigator.clipboard.writeText(text);
    alert(msg);
  } catch (_e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_e2) { ok = false; }
    document.body.removeChild(ta);
    alert(ok ? msg : "浏览器未允许自动复制，请重试或手动复制");
  }
}

// 批量栏「复制 boson」: 勾选行 (按紧迫分降序, 与导出选中一致).
function copyBosonSelected() {
  if (state.selected.size === 0) { alert("请先勾选要复制的行"); return; }
  const sel = state.items
    .filter((it) => state.selected.has(it.barcode))
    .sort((a, b) => (b.urgency_score || 0) - (a.urgency_score || 0));
  copyBosonText(sel);
}

// 更多菜单「复制 boson (可见)」: 当前过滤+排序后可见行 (上限 500, 与导出可见一致).
function copyBosonVisible() {
  const visible = applySort(applyFilter(state.items)).slice(0, 500);
  if (visible.length === 0) { alert("当前筛选范围内没有可复制的行"); return; }
  copyBosonText(visible);
}

function markSelectedOrdered() {
  if (state.selected.size === 0) {
    alert("请先勾选要标记的行");
    return;
  }
  const now = new Date().toISOString();
  const newBatch = [];
  const itemSnapshots = [];
  for (const bc of state.selected) {
    if (!(bc in state.ordered)) {
      state.ordered[bc] = { marked_at: now };
      newBatch.push(bc);
      const it = state.items.find((x) => x.barcode === bc);
      if (it) itemSnapshots.push(it);
    }
  }
  if (newBatch.length > 0) state.orderedHistory.push(newBatch);
  state.selected.clear();
  saveOrdered();
  render();
  // P3 后端记录: ordered 或 overridden (低分硬要进) 自动改判
  if (itemSnapshots.length > 0) recordDecisionsBatch("ordered", itemSnapshots);
}

async function markSelectedSkipped() {
  if (state.selected.size === 0) {
    alert("请先勾选要标记的行");
    return;
  }
  const reason = prompt("跳过原因? (可空, 例: 供应商断货 / 客人未确认 / 等下次活动)") ?? "";
  const items = [];
  for (const bc of state.selected) {
    const it = state.items.find((x) => x.barcode === bc);
    if (it) items.push(it);
  }
  if (items.length === 0) return;
  // 硬约束: 先确认 POST 成功, 再乐观隐藏; 失败不隐藏(防前端假状态)
  const ok = await recordDecisionsBatch("skipped", items, reason || null);
  if (!ok) {
    alert("跳过记录失败, 未隐藏, 请重试");
    return;
  }
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  for (const it of items) {
    state.suppressed[it.barcode] = {
      skipped_at: now,
      reason: reason || null,
      days_left: SKIP_SUPPRESS_DAYS,
    };
  }
  state.selected.clear();
  render();
}

// 单条 drawer 操作: 直接对当前展开行做记号, 不依赖 selection.
function markSingleOrdered(bc) {
  if (bc in state.ordered) return;  // 幂等
  const it = state.items.find((x) => x.barcode === bc);
  if (!it) return;
  state.ordered[bc] = { marked_at: new Date().toISOString() };
  state.orderedHistory.push([bc]);
  state.expandedBarcode = null;
  saveOrdered();
  render();
  recordDecisionsBatch("ordered", [it]);
}

async function markSingleSkipped(bc) {
  const it = state.items.find((x) => x.barcode === bc);
  if (!it) return;
  const reason = prompt("跳过原因? (可空, 例: 供应商断货 / 客人未确认 / 等下次活动)") ?? "";
  const ok = await recordDecisionsBatch("skipped", [it], reason || null);
  if (!ok) {
    alert("跳过记录失败, 未隐藏, 请重试");
    return;
  }
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  state.suppressed[bc] = { skipped_at: now, reason: reason || null, days_left: SKIP_SUPPRESS_DAYS };
  state.expandedBarcode = null;
  render();
}

async function recordDecisionsBatch(decision, items, reason) {
  try {
    const resp = await fetch("/restock/decisions/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, items, reason: reason || null }),
    });
    const data = await resp.json();
    if (data.ok && data.overridden > 0) {
      console.log(`[restock-decisions] ${data.recorded} 条 (含 ${data.overridden} 个低分覆盖)`);
    }
    return !!data.ok;
  } catch (err) {
    console.warn("[restock-decisions] 失败:", err.message);
    return false;
  }
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
  // 紧迫供应商: 有 SKU urgency >= SUPPLIER_OVERVIEW_HOT (默认 70) 的, 按 hot SKU 数 desc.
  const pool = applyFilterExceptSupplier(state.items);
  const byS = new Map();
  for (const it of pool) {
    if (!it.supplier_id || it.urgency_score == null) continue;
    const key = it.supplier_id;
    if (!byS.has(key)) byS.set(key, { supplier_id: key, count: 0, hot_count: 0, max: 0 });
    const e = byS.get(key);
    if (it.urgency_score >= SUPPLIER_OVERVIEW_HOT) e.hot_count += 1;
    e.count += 1;
    if (it.urgency_score > e.max) e.max = it.urgency_score;
  }
  return Array.from(byS.values()).filter((s) => s.hot_count > 0).sort((a, b) => b.hot_count - a.hot_count);
}

function _allSuppliersSummary() {
  // 全量供应商: 展开模式用. 按 max urgency desc 排, 让"次紧迫" (69.5 那种) 露出来.
  const pool = applyFilterExceptSupplier(state.items);
  const byS = new Map();
  for (const it of pool) {
    if (!it.supplier_id || it.urgency_score == null) continue;
    const key = it.supplier_id;
    if (!byS.has(key)) byS.set(key, { supplier_id: key, count: 0, hot_count: 0, max: 0 });
    const e = byS.get(key);
    if (it.urgency_score >= SUPPLIER_OVERVIEW_HOT) e.hot_count += 1;
    e.count += 1;
    if (it.urgency_score > e.max) e.max = it.urgency_score;
  }
  return Array.from(byS.values()).sort((a, b) => b.max - a.max);
}

function renderSupplierSummary() {
  const root = $("rsSupplierOverview");
  if (!root) return;
  // 默认折叠态: 紧迫供应商 (有 SKU >=70). 展开态: 全量供应商 (按 max desc, 含次紧迫).
  const hot = _supplierSummary();
  const all = _allSuppliersSummary();
  const expanded = state.supplierOverviewExpanded;
  const show = expanded ? all : hot.slice(0, SUPPLIER_OVERVIEW_TOP);

  // 无供应商数据 → 整条隐藏 (:empty)
  if (all.length === 0) { root.innerHTML = ""; return; }

  const chips = show.map((s) => {
    const isHot = s.hot_count > 0 || s.max >= SUPPLIER_OVERVIEW_HOT;
    const isActive = state.filter.supplier === s.supplier_id;
    const w = Math.max(4, Math.min(100, Math.round(s.max)));
    return `
      <button class="sup-chip${isHot ? " is-hot" : ""}${isActive ? " is-active" : ""}"
              data-supplier="${escapeHtml(s.supplier_id)}"
              title="点击筛选 ${escapeHtml(s.supplier_id)} 全部 ${s.count} 个 SKU (max ${s.max.toFixed(1)})">
        <span class="sup-chip-name">${escapeHtml(s.supplier_id)}</span>
        <span class="sup-chip-cnt">${s.count}</span>
        <span class="sup-chip-mini"><i style="width:${w}%"></i></span>
        <span class="sup-chip-score">${Math.round(s.max)}</span>
      </button>`;
  }).join("");

  const label = expanded
    ? `<span class="sup-strip-label">全部供应商 <span class="sup-cond">(按紧迫度 · ${all.length} 家)</span></span>`
    : `<span class="sup-strip-label"><span class="sup-fire">🔥</span> 紧迫供应商 <span class="sup-cond">(≥${SUPPLIER_OVERVIEW_HOT} · ${hot.length} 家)</span></span>`;
  const moreBtn = expanded
    ? `<button class="sup-strip-more" id="rsSupExpand">‹ 收起</button>`
    : `<button class="sup-strip-more" id="rsSupExpand">查看全部 ${all.length} 家 ›</button>`;
  const chipsHtml = show.length
    ? `<div class="sup-chips">${chips}</div>`
    : `<div class="sup-chips"><span class="sup-chip-score" style="padding:6px 4px">当前范围无紧迫分 ≥${SUPPLIER_OVERVIEW_HOT} 的供应商</span></div>`;

  root.innerHTML = `${label}${chipsHtml}${moreBtn}`;

  for (const btn of root.querySelectorAll(".sup-chip[data-supplier]")) {
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
  // 状态 band chip
  for (const b of document.querySelectorAll("#pageRestock .rs-chip[data-band]")) {
    b.classList.toggle("rs-chip--active", b.dataset.band === state.filter.band);
  }
  // 来源分段控件
  for (const b of document.querySelectorAll("#rsOriginSeg button[data-origin]")) {
    b.classList.toggle("on", (b.dataset.origin || "") === (state.filter.origin || ""));
  }
  // 视图多选
  for (const b of document.querySelectorAll("#pageRestock .rs-vchip[data-view]")) {
    b.classList.toggle("on", !!state.filter.views[b.dataset.view]);
  }
  syncCfUI();
  syncCoverThresholdUI();

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

  // 批量操作栏: 选中行后浮现 (替换常驻按钮)
  updateBulkBar(state.selected.size);
  if ($("rsStatTotal")) $("rsStatTotal").textContent = `已标记 ${state.selected.size}`;
  $("rsBtnUndo").disabled = state.orderedHistory.length === 0;

  // 智能凑单按钮预览数
  const { picks: bundlePicks, hotMode, capped } = _bundleCandidates();
  const bundleBtn = $("rsBtnBundle");
  if (bundleBtn) {
    bundleBtn.textContent = `✓ 智能凑单 (${bundlePicks.length})`;
    bundleBtn.disabled = bundlePicks.length === 0;
    if (capped) {
      bundleBtn.title = `未选供应商: 自动 cap 在 top ${BUNDLE_TARGET_COUNT} 防止全选. 选具体供应商进入凑单模式后才不 cap.`;
    } else if (hotMode) {
      bundleBtn.title = `凑单模式 (供应商=${state.filter.supplier}): 紧迫分 ≥${BUNDLE_HOT_THRESHOLD} 的 SKU 全选`;
    } else {
      bundleBtn.title = `紧迫分 ≥${BUNDLE_HOT_THRESHOLD} 不足 ${BUNDLE_TARGET_COUNT} 个, 退到 top ${BUNDLE_TARGET_COUNT}`;
    }
  }
}

// 可撑阈值筛选 cf chip UI
function syncCfUI() {
  const cf = $("rsCoverFilter");
  if (!cf) return;
  const set = state.filter.coverMax !== null;
  cf.classList.toggle("is-set", set);
  if (set) {
    $("rsCfVal").textContent = state.filter.coverMax;
    $("rsCfPopNum").textContent = state.filter.coverMax;
    if ($("rsCfRange")) $("rsCfRange").value = String(state.filter.coverMax);
  } else {
    $("rsCfVal").textContent = "∞";
  }
}

// 可撑微条安全阈值 UI (列头齿轮 popover)
function syncCoverThresholdUI() {
  const T = state.filter.coverThreshold;
  if ($("rsCoverThVal")) $("rsCoverThVal").textContent = T.toFixed(1);
  if ($("rsCoverThRange")) $("rsCoverThRange").value = String(T);
}

// 批量操作栏显隐 + 计数
function updateBulkBar(n) {
  const bar = $("rsBulkBar");
  if (!bar) return;
  const nEl = $("rsBulkN");
  if (nEl) nEl.textContent = n;
  bar.classList.toggle("show", n > 0);
}

function render() {
  const filtered = applyFilter(state.items);
  const sorted = applySort(filtered);
  const visible = sorted.slice(0, 500);
  const tbody = $("rsTbody");
  if (visible.length === 0) {
    tbody.innerHTML = '<tr><td colspan="15" class="empty">无匹配项</td></tr>';
  } else {
    // 渲染所有行; 如果某行 barcode == expandedBarcode, 紧接着插入 drawer
    const html = [];
    for (const it of visible) {
      html.push(renderRow(it));
      if (state.expandedBarcode === it.barcode) {
        html.push(renderDrawer(it));
      }
    }
    tbody.innerHTML = html.join("");
    // ⚑ flag 选择 (取代 checkbox): toggle state.selected
    for (const fl of tbody.querySelectorAll(".rs-flag")) {
      fl.addEventListener("click", (e) => {
        e.stopPropagation();
        const bc = fl.dataset.bc;
        if (state.selected.has(bc)) state.selected.delete(bc);
        else state.selected.add(bc);
        fl.classList.toggle("is-flagged");
        syncChipActive();
        renderKpi();
        if (state.filter.band === "flagged") render(); // flagged 视图需重过滤
      });
    }
    // 可撑微条 knob 拖拽 → 临时调全局安全阈值
    for (const knob of tbody.querySelectorAll(".rs-cover-knob")) {
      knob.addEventListener("mousedown", (e) => {
        e.preventDefault(); e.stopPropagation();
        const track = knob.parentElement;
        const onMove = (ev) => {
          const r = track.getBoundingClientRect();
          const pct = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
          state.filter.coverThreshold = Math.max(0.5, Math.round(pct * COVER_CAP * 2) / 2);
          recolorCover();
          syncCoverThresholdUI();
        };
        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    }
    // 供应商点击 → 进入"凑单模式": 设供应商筛选 + 自动禁用 cover filter
    for (const sup of tbody.querySelectorAll(".rs-supplier[data-supplier]")) {
      sup.addEventListener("click", (e) => {
        e.stopPropagation();
        state.filter.supplier = sup.dataset.supplier;
        state.filter.coverMax = null;
        render();
      });
    }
    // barcode 列点击 → 跳货号历史 (仅此列)
    for (const link of tbody.querySelectorAll(".rs-bc-link")) {
      link.addEventListener("click", (e) => {
        e.stopPropagation();
        const bc = link.dataset.bc;
        if (typeof window.historySearch === "function") {
          window.Alpine?.store("nav")?.switch("history");
          setTimeout(() => window.historySearch(bc), 50);
        }
      });
    }
    // p98 数量输入: 改值只写 state, 不重绘(避免失焦); click 阻断冒泡防触发 row→drawer.
    for (const inp of tbody.querySelectorAll(".rs-qty-input")) {
      inp.addEventListener("input", () => {
        state.editedQty[inp.dataset.bc] = inp.value;
      });
      inp.addEventListener("click", (e) => e.stopPropagation());
    }
    // 行其他位置点击 → toggle drawer (排除 flag / supplier / barcode link / 可撑微条)
    for (const tr of tbody.querySelectorAll(".rs-row")) {
      tr.addEventListener("click", (e) => {
        if (e.target.closest(".rs-flag, .rs-supplier, .rs-bc-link, .rs-cover-track")) return;
        const bc = tr.dataset.bc;
        state.expandedBarcode = (state.expandedBarcode === bc) ? null : bc;
        render();
      });
    }
    // drawer 内部按钮: 我已下单 / 跳过 / 收起
    for (const btn of tbody.querySelectorAll(".rs-btn--ordered-single")) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        markSingleOrdered(btn.dataset.bc);
      });
    }
    for (const btn of tbody.querySelectorAll(".rs-btn--skip-single")) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        markSingleSkipped(btn.dataset.bc);
      });
    }
    for (const btn of tbody.querySelectorAll(".rs-btn--close-drawer")) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.expandedBarcode = null;
        render();
      });
    }
    // drawer 自身点击不冒泡 (避免点 drawer 内部触发 row click)
    for (const dr of tbody.querySelectorAll(".rs-drawer-row")) {
      dr.addEventListener("click", (e) => e.stopPropagation());
    }
  }
  const baseStat = visible.length < sorted.length
    ? `显示前 ${visible.length} / ${sorted.length} 项`
    : `显示 ${sorted.length} 项`;
  $("rsStatShowing").textContent = baseStat;
  $("rsStatTotal").textContent = `已标记 ${state.selected.size}`;

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
  // stat 卡片: 紧急(≥70)/关注(40-69)/充足(<40) 看活跃 SKU; 已标记=选中数; 本周补货额=Σ可见行 p50×成本
  // 排除已下单 / 已跳过(决策回流): 已处理的 SKU 不该再计入"紧急"等噪音, 与默认列表隐藏一致
  const pool = state.items.filter(
    (it) =>
      !it.is_truly_discontinued &&
      !it.is_new_item &&
      !(it.barcode in state.ordered) &&
      !(it.barcode in state.suppressed),
  );
  const hot = pool.filter((it) => (it.urgency_score ?? -1) >= 70).length;
  const watch = pool.filter((it) => { const s = it.urgency_score ?? -1; return s >= 40 && s < 70; }).length;
  const ok = pool.filter((it) => { const s = it.urgency_score ?? -1; return s >= 0 && s < 40; }).length;
  let spend = 0;
  for (const it of applyFilter(state.items)) {
    const qty = it.restock_qty_p50;
    const cost = it.last_purchase_unit_price ?? it.master_stock_price_eur;
    if (qty && cost) spend += qty * cost;
  }
  const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  set("rsKpiHot", hot.toLocaleString());
  set("rsKpiWatch", watch.toLocaleString());
  set("rsKpiOk", ok.toLocaleString());
  set("rsKpiFlagged", state.selected.size.toLocaleString());
  set("rsKpiSpend", spend > 0 ? `€${Math.round(spend).toLocaleString()}` : "—");
}

async function load() {
  const tbody = $("rsTbody");
  tbody.innerHTML = '<tr><td colspan="15" class="empty">加载中…</td></tr>';
  try {
    const resp = await fetch("/analytics/list");
    const data = await resp.json();
    if (!data.ok) {
      tbody.innerHTML = `<tr><td colspan="15" class="empty">加载失败：${escapeHtml(data.msg || "")}</td></tr>`;
      return;
    }
    state.items = data.items;
    // 货到后自动 unmark
    autoClearOrderedByPurchase();
    // 决策回流: 拉 skip 抑制集(失败兜底空, 不阻断主列表)
    try {
      const sresp = await fetch("/restock/decisions/suppressed");
      const sdata = await sresp.json();
      state.suppressed = sdata.ok ? (sdata.items || {}) : {};
    } catch (_e) {
      state.suppressed = {};
    }
    $("rsStatTotal").textContent = `共 ${data.total} 个 SKU`;
    render();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="15" class="empty">网络错误：${escapeHtml(err.message)}</td></tr>`;
  }
}

function init() {
  if (!$("pageRestock")) return;

  // 启动时先把 localStorage 里 ordered 加载进来 (含 30 天过期清理)
  state.ordered = loadOrdered();

  $("rsRefresh").addEventListener("click", load);
  $("rsBtnExport").addEventListener("click", exportSelectedCsv);
  $("rsBtnCopyBoson")?.addEventListener("click", copyBosonSelected);
  $("rsBtnMark").addEventListener("click", markSelectedOrdered);
  $("rsBtnSkip").addEventListener("click", markSelectedSkipped);
  $("rsBtnBundle").addEventListener("click", smartBundleSelect);
  $("rsBtnUndo").addEventListener("click", undoMarkRecent);
  $("rsBulkClear")?.addEventListener("click", () => {
    state.selected.clear();
    render();
  });
  // 顶部「更多」下拉
  const actMore = $("rsActMore");
  $("rsMoreBtn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    actMore?.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (actMore && !actMore.contains(e.target)) actMore.classList.remove("open");
  });
  $("rsMenuExport")?.addEventListener("click", () => { actMore?.classList.remove("open"); exportVisibleCsv(); });
  $("rsMenuCopyBoson")?.addEventListener("click", () => { actMore?.classList.remove("open"); copyBosonVisible(); });
  $("rsMenuOrder")?.addEventListener("click", () => { actMore?.classList.remove("open"); exportVisibleCsv(); });
  $("rsSupplierClear").addEventListener("click", () => {
    state.filter.supplier = null;
    render();
  });
  // 搜索框: 输入即过滤 (无 debounce, 27k items 客户端 filter <50ms 体感秒)
  const searchInput = $("rsSearch");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      state.filter.search = e.target.value.trim();
      render();
    });
  }
  $("rsSearchClear")?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    state.filter.search = "";
    render();
  });

  // 状态 band 过滤 chip (全部/紧急/关注/充足/已标记; 再点全部取消)
  for (const btn of document.querySelectorAll("#pageRestock .rs-chip[data-band]")) {
    btn.addEventListener("click", () => {
      state.filter.band = (state.filter.band === btn.dataset.band) ? "all" : btn.dataset.band;
      render();
    });
  }
  // 来源分段控件 (单选)
  for (const btn of document.querySelectorAll("#rsOriginSeg button[data-origin]")) {
    btn.addEventListener("click", () => {
      state.filter.origin = btn.dataset.origin || "";
      render();
    });
  }
  // 视图多选 (活跃/新品/含停用)
  for (const btn of document.querySelectorAll("#pageRestock .rs-vchip[data-view]")) {
    btn.addEventListener("click", () => {
      const k = btn.dataset.view;
      state.filter.views[k] = !state.filter.views[k];
      render();
    });
  }
  // 可撑阈值筛选 cf (收起的滑块 popover)
  const cf = $("rsCoverFilter");
  $("rsCfChip")?.addEventListener("click", (e) => {
    if (e.target.id === "rsCfClear") return; // ✕ 清除时不开 popover
    e.stopPropagation();
    cf?.classList.toggle("open");
  });
  $("rsCfClear")?.addEventListener("click", (e) => {
    e.stopPropagation();
    state.filter.coverMax = null;
    cf?.classList.remove("open");
    render();
  });
  $("rsCfReset")?.addEventListener("click", () => {
    state.filter.coverMax = null;
    cf?.classList.remove("open");
    render();
  });
  $("rsCfRange")?.addEventListener("input", (e) => {
    state.filter.coverMax = Number(e.target.value);
    render();
  });
  document.addEventListener("click", (e) => {
    if (cf && !cf.contains(e.target)) cf.classList.remove("open");
  });
  // 排序下拉
  $("rsSortSel")?.addEventListener("change", (e) => {
    const [key, dir] = e.target.value.split("|");
    state.sort = { key, dir };
    render();
  });
  // 重置全部过滤
  $("rsResetFilters")?.addEventListener("click", () => {
    state.filter.origin = "";
    state.filter.views = { active: true, new: false, disc: false };
    state.filter.band = "all";
    state.filter.coverMax = null;
    state.filter.supplier = null;
    state.filter.search = "";
    if (searchInput) searchInput.value = "";
    render();
  });
  // 可撑列头齿轮: 全局安全周转阈值 popover
  const coverPop = $("rsCoverPop");
  $("rsCoverGear")?.addEventListener("click", (e) => {
    e.stopPropagation();
    coverPop?.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (coverPop && !coverPop.parentElement.contains(e.target)) coverPop.classList.remove("open");
  });
  $("rsCoverThRange")?.addEventListener("input", (e) => {
    state.filter.coverThreshold = Number(e.target.value);
    syncCoverThresholdUI();
    recolorCover();
  });

  for (const th of document.querySelectorAll("#pageRestock .rs-th-sort")) {
    th.addEventListener("click", (e) => {
      if (e.target.closest(".rs-cover-gear, .rs-cover-pop")) return; // 齿轮/弹层不排序
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
