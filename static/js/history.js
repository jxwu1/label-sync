// 货号历史 tab：精确搜索 + 渲染当前状态 + 聚合时间线
"use strict";

const $ = (id) => document.getElementById(id);

const SOURCE_CN = {
  scan_import: "扫描导入",
  user_correction: "手动修正",
  system_export: "系统导出",
  inventory_events: "进销存",
};

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
  sale: "销售",
  purchase: "采购",
};

let _currentBarcode = null;

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderEmpty(msg) {
  $("historyHint").textContent = msg;
  $("historyHint").style.display = "";
  $("historyCurrentPanel").hidden = true;
  $("historyTimelinePanel").hidden = true;
  $("historyFuzzyPanel").hidden = true;
  $("historyAnalyticsPanel").hidden = true;
  if ($("historyPurchasePanel")) $("historyPurchasePanel").hidden = true;
  $("historyTimelineChartPanel").hidden = true;
}

function renderFuzzyMatches(matches, originalQuery) {
  $("historyHint").textContent = `"${originalQuery}" 没有精确匹配，找到 ${matches.length} 条候选`;
  $("historyHint").style.display = "";
  $("historyCurrentPanel").hidden = true;
  $("historyTimelinePanel").hidden = true;
  $("historyFuzzyPanel").hidden = false;
  $("historyAnalyticsPanel").hidden = true;
  if ($("historyPurchasePanel")) $("historyPurchasePanel").hidden = true;
  $("historyTimelineChartPanel").hidden = true;

  const rows = matches
    .map((m) => {
      const badge = m.is_active
        ? '<span class="badge-active">活跃</span>'
        : '<span class="badge-inactive">已下架</span>';
      const loc = escapeHtml(m.location || "—");
      return `
        <tr class="fuzzy-row" data-barcode="${escapeHtml(m.barcode)}">
          <td>${escapeHtml(m.barcode)}</td>
          <td>${escapeHtml(m.model)}</td>
          <td>${loc}</td>
          <td>${badge}</td>
        </tr>`;
    })
    .join("");
  $("historyFuzzyList").innerHTML = `
    <table class="fuzzy-table">
      <thead><tr><th>条码</th><th>型号</th><th>当前位置</th><th>状态</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  // 行点击 → drill 到精确路径
  for (const tr of $("historyFuzzyList").querySelectorAll(".fuzzy-row")) {
    tr.addEventListener("click", () => window.historySearch(tr.dataset.barcode));
  }
}

const AUTO_CATEGORY_CN = {
  new: "新品观察",
  seasonal: "季节性",
  declining: "衰退",
  stable: "稳定",
  unclassified: "未分类",
};

const MANUAL_CATEGORIES = [
  "季节性",
  "网红昙花",
  "应需采购",
  "消耗品",
  "长期产品",
  "阶段性多峰",
  "滞销",
];

function fmtNum(n) {
  if (n === null || n === undefined) return '<span class="empty-val">—</span>';
  return String(n);
}

function fmtPct(n) {
  if (n === null || n === undefined) return '<span class="empty-val">—</span>';
  const sign = n > 0 ? "+" : "";
  return `${sign}${n}%`;
}

function fmtDays(n) {
  if (n === null || n === undefined) return '<span class="empty-val">—</span>';
  return `${n} 天前`;
}

async function loadTimelineChart(barcode) {
  const panel = $("historyTimelineChartPanel");
  const canvas = $("historyTimelineChart");
  panel.hidden = false;
  try {
    const resp = await fetch(`/analytics/sku/${encodeURIComponent(barcode)}/timeline`);
    const data = await resp.json();
    if (!data.ok) {
      drawChartEmpty(canvas, data.msg || "加载失败");
      return;
    }
    drawTimeline(canvas, data.timeline);
  } catch (err) {
    drawChartEmpty(canvas, `网络错误：${err.message}`);
  }
}

function drawChartEmpty(canvas, msg) {
  const ctx = setupCanvas(canvas);
  ctx.fillStyle = "#999";
  ctx.font = "13px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(msg, canvas.clientWidth / 2, 140);
}

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.parentElement.clientWidth - 24; // 减 panel-bd padding
  const h = 280;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return ctx;
}

function drawTimeline(canvas, timeline) {
  const ctx = setupCanvas(canvas);
  const w = canvas.clientWidth;
  const h = 280;
  const padL = 44;
  const padR = 44;
  const padT = 16;
  const padB = 28;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  if (!timeline || timeline.length === 0) {
    drawChartEmpty(canvas, "无数据");
    return;
  }

  const n = timeline.length;
  const sales = timeline.map((t) => t.sale_qty || 0);
  const prices = timeline.map((t) => t.purchase_unit_price);
  const maxSale = Math.max(1, ...sales);
  const validPrices = prices.filter((p) => p !== null && p !== undefined);
  const hasPrices = validPrices.length > 0;
  const minPrice = hasPrices ? Math.min(...validPrices) : 0;
  const maxPrice = hasPrices ? Math.max(...validPrices) : 1;
  const priceRange = Math.max(0.01, maxPrice - minPrice);

  // 网格 + 轴
  ctx.strokeStyle = "#e0d8c8";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plotH * i) / 4;
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
  }
  ctx.stroke();

  // 左 Y 轴标签（销量）
  ctx.fillStyle = "#666";
  ctx.font = "11px sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const v = Math.round((maxSale * (4 - i)) / 4);
    ctx.fillText(v, padL - 4, padT + (plotH * i) / 4);
  }

  // 右 Y 轴标签（进价）
  if (hasPrices) {
    ctx.fillStyle = "#586e75";
    ctx.textAlign = "left";
    for (let i = 0; i <= 4; i++) {
      const v = (maxPrice - (priceRange * i) / 4).toFixed(2);
      ctx.fillText(`€${v}`, padL + plotW + 4, padT + (plotH * i) / 4);
    }
  }

  // X 轴标签（每 ~13 周一个，标月份）
  ctx.fillStyle = "#666";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const xStep = plotW / Math.max(n - 1, 1);
  for (let i = 0; i < n; i += Math.max(1, Math.floor(n / 5))) {
    const month = timeline[i].week_start.slice(0, 7);
    ctx.fillText(month, padL + i * xStep, padT + plotH + 6);
  }

  // 销量：竖条（柱状）
  ctx.fillStyle = "rgba(67, 145, 96, 0.55)";
  const barW = Math.max(2, xStep * 0.6);
  for (let i = 0; i < n; i++) {
    const qty = sales[i];
    if (qty === 0) continue;
    const x = padL + i * xStep - barW / 2;
    const barH = (qty / maxSale) * plotH;
    const y = padT + plotH - barH;
    ctx.fillRect(x, y, barW, barH);
  }

  // 进价：折线（仅连续非空段）
  if (hasPrices) {
    ctx.strokeStyle = "#b0683b";
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < n; i++) {
      const p = prices[i];
      if (p === null || p === undefined) {
        started = false;
        continue;
      }
      const x = padL + i * xStep;
      const y = padT + ((maxPrice - p) / priceRange) * plotH;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();

    // 进价点标记
    ctx.fillStyle = "#b0683b";
    for (let i = 0; i < n; i++) {
      const p = prices[i];
      if (p === null || p === undefined) continue;
      const x = padL + i * xStep;
      const y = padT + ((maxPrice - p) / priceRange) * plotH;
      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

async function loadAnalytics(barcode) {
  const slaPanel = $("historyAnalyticsPanel");
  const purPanel = $("historyPurchasePanel");
  const slaBody = $("historyAnalytics");
  const purBody = $("historyPurchase");
  slaPanel.hidden = false;
  if (purPanel) purPanel.hidden = false;
  slaBody.innerHTML = '<div class="hist-tle-count">加载中…</div>';
  if (purBody) purBody.innerHTML = '<div class="hist-tle-count">加载中…</div>';
  try {
    const resp = await fetch(`/analytics/sku/${encodeURIComponent(barcode)}`);
    const data = await resp.json();
    if (!data.ok) {
      const msg = `<div class="hist-tle-count">${escapeHtml(data.msg || "加载失败")}</div>`;
      slaBody.innerHTML = msg;
      if (purBody) purBody.innerHTML = msg;
      return;
    }
    renderAnalytics(data);
  } catch (err) {
    const msg = `<div class="hist-tle-count">网络错误：${escapeHtml(err.message)}</div>`;
    slaBody.innerHTML = msg;
    if (purBody) purBody.innerHTML = msg;
  }
}

// PR 8a · 拆为 SLA + PUR 两段，分别渲染到独立 panel
function renderAnalytics(data) {
  renderSLA(data);
  renderPUR(data.purchase || {});
}

function renderSLA(data) {
  const s = data.sales || {};
  const cs = data.customer_split || { cn: {}, fo: {} };
  const autoCat = data.auto_category
    ? `<span class="cat-badge cat-${escapeHtml(data.auto_category)}">${escapeHtml(AUTO_CATEGORY_CN[data.auto_category] || data.auto_category)}</span>`
    : '<span class="hist-kv--empty">未计算</span>';
  const computedAt = data.auto_category_computed_at
    ? `<span class="hist-sla-time">（${escapeHtml(data.auto_category_computed_at)}）</span>`
    : "";
  const dropdown = renderManualDropdown(data.barcode, data.manual_category);
  const gradeRow = renderGradeRow(data.manual_grade, data.qty_percentile);

  const dailyAvg = ((s.total_qty || 0) / Math.max(1, s.lifespan_days || 1)).toFixed(2);

  $("historyAnalytics").innerHTML = `
    <div class="hist-sla-body">
      <div class="hist-sla-row">
        <span class="hist-sla-rowlabel">自动分类</span>
        ${autoCat}${computedAt}
      </div>
      <div class="hist-sla-row">
        <span class="hist-sla-rowlabel">人工标签</span>
        ${dropdown}
      </div>
      ${gradeRow}

      <div class="hist-section-label">SALES SIDE · 销售面</div>
      <div class="hist-sla-grid">
        ${_kv("总销量",   fmtNum(s.total_qty),                                  "hist-kv--num hist-kv--accent")}
        ${_kv("总营收",   `€${(s.total_revenue || 0).toFixed(2)}`,              "hist-kv--num hist-kv--accent")}
        ${_kv("独立客户", fmtNum(s.unique_customers),                           "hist-kv--num")}
        ${_kv("寿命",     `${s.lifespan_days || 0} 天`,                         "hist-kv--num")}
        ${_kv("日均件数", dailyAvg,                                             "hist-kv--num")}
        ${_kv("12 周趋势", `${fmtPct(s.trend_slope_pct_per_week)} / 周`,         "hist-kv--num")}
      </div>

      <div class="hist-section-label">CLIENT SPLIT · 客户端拆分</div>
      <div class="hist-cust-split">
        ${renderClientCard("CN", "中国端", cs.cn || {})}
        ${renderClientCard("GR", "老外端", cs.fo || {})}
      </div>
    </div>
  `;

  // 绑下拉 change → POST
  const sel = $("manualCategorySelect");
  if (sel) {
    sel.addEventListener("change", async () => {
      const val = sel.value;
      try {
        const resp = await fetch(
          `/analytics/sku/${encodeURIComponent(data.barcode)}/manual-category`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category: val }),
          },
        );
        const r = await resp.json();
        if (!r.ok) {
          alert(`保存失败：${r.msg}`);
          sel.value = data.manual_category || "";
        } else {
          data.manual_category = r.manual_category;
        }
      } catch (err) {
        alert(`网络错误：${err.message}`);
        sel.value = data.manual_category || "";
      }
    });
  }
}

function renderPUR(p) {
  const purBody = $("historyPurchase");
  if (!purBody) return;
  const stockBalance = p.stock_balance;
  const stockNegative = typeof stockBalance === "number" && stockBalance < 0;
  const warnBox = stockNegative
    ? `<div class="hist-warn-box">
         <span class="hist-warn-icon">⚠</span>
         库存推算结果为负值 — 历史采购数据缺失或未导入。建议在
         <span class="hist-warn-link">进销存导入</span> 模块补录。
       </div>`
    : "";
  purBody.innerHTML = `
    <div class="hist-pur-grid">
      ${_kv("库存推算",      fmtNum(stockBalance),                "hist-kv--num")}
      ${_kv("毛利率",        fmtPct(p.avg_margin_pct),            "hist-kv--num")}
      ${_kv("365 天采购笔数", fmtNum(p.purchase_freq_365d),        "hist-kv--num")}
      ${_kv("上次采购",      fmtDays(p.last_purchase_days_ago),    "hist-kv--num")}
    </div>
    ${warnBox}
  `;
}

function renderManualDropdown(barcode, current) {
  const opts = ['<option value="">— 未设置 —</option>']
    .concat(
      MANUAL_CATEGORIES.map(
        (c) =>
          `<option value="${escapeHtml(c)}"${c === current ? " selected" : ""}>${escapeHtml(c)}</option>`,
      ),
    )
    .join("");
  return `<select id="manualCategorySelect" class="manual-cat-select">${opts}</select>`;
}

// PR 8a · ClientCard 风：CN/GR 两列，border-left 2px 标签色
function renderClientCard(tag, name, m) {
  const last = m.last_at ? escapeHtml(m.last_at) : "—";
  const rows = [
    ["销量", fmtNum(m.qty)],
    ["客户数", fmtNum(m.unique_customers)],
    ["单笔最大", fmtNum(m.max_single_qty)],
    ["月均频次", fmtNum(m.avg_freq_per_month)],
    ["上次购买", last],
  ].map(([k, v]) => `<div class="hist-client-row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("");
  return `
    <div class="hist-client-card" data-tag="${tag}">
      <div class="hist-client-hd">
        <span class="hist-client-tag">${tag}</span>
        <span class="hist-client-name">${escapeHtml(name)}</span>
      </div>
      <div class="hist-client-grid">${rows}</div>
    </div>
  `;
}

function renderGradeRow(grade, percentile) {
  if (grade === null || grade === undefined) return "";
  const pctText =
    percentile === null || percentile === undefined
      ? '<span class="hist-kv--empty">无销售</span>'
      : `${percentile}% 分位`;
  let warn = "";
  if (percentile !== null && percentile !== undefined) {
    if (grade >= 8 && percentile < 30) {
      warn = '<span class="grade-warn">⚠ 高等级低销量</span>';
    } else if (grade <= 3 && percentile > 70) {
      warn = '<span class="grade-warn">⚠ 低等级高销量</span>';
    }
  }
  return `
    <div class="hist-sla-row">
      <span class="hist-sla-rowlabel">等级对照</span>
      <span style="font-size: 12.5px; color: var(--ink-1);">ERP 等级 <span style="font-family: var(--mono); color: var(--ink-0); font-weight: 700;">${grade}</span> · 销量 <span style="font-family: var(--mono); color: var(--accent); font-weight: 700;">${pctText}</span> ${warn}</span>
    </div>
  `;
}

// PR 8a · CUR 4-col mono grid 字段渲染
function _kv(k, v, mods = "") {
  const cls = `hist-kv ${mods}`.trim();
  return `<div class="${cls}"><span class="hist-kv-k">${escapeHtml(k)}</span><span class="hist-kv-v">${v}</span></div>`;
}

function renderResult(data) {
  $("historyHint").style.display = "none";
  $("historyCurrentPanel").hidden = false;
  $("historyTimelinePanel").hidden = false;
  $("historyFuzzyPanel").hidden = true;

  const c = data.current;
  _currentBarcode = c.barcode;
  $("historyCopyBarcodeBtn").hidden = false;
  const storesText = (c.store_locations || []).map(escapeHtml).join(", ");
  const warehousesText = (c.warehouse_locations || []).map(escapeHtml).join(", ");
  const unknownText = (c.unknown_locations || []).map(escapeHtml).join(", ");
  // 新加字段（来自 product.csv 主档）—— 有值才显示，避免老数据下空白行
  // 注意：分类不展示（roadmap 决策：源 ERP 分类只参考不照抄）
  // 进价不展示（源数据 CNY/EUR 混，无币种字段，会误导）
  const cells = [];
  cells.push(_kv("型号", escapeHtml(c.model), "hist-kv--mono hist-kv--accent"));
  cells.push(_kv("条码", escapeHtml(c.barcode), "hist-kv--mono"));
  if (c.product_name_zh) cells.push(_kv("品名", escapeHtml(c.product_name_zh)));
  if (c.product_name_local) cells.push(_kv("本地品名", escapeHtml(c.product_name_local), "hist-kv--mono hist-kv--muted"));
  cells.push(_kv("店面位置", storesText || "—", storesText ? "hist-kv--mono" : "hist-kv--empty"));
  cells.push(_kv("仓库位置", warehousesText || "—", warehousesText ? "hist-kv--mono" : "hist-kv--empty"));
  if (unknownText) cells.push(_kv("其他位置", unknownText, "hist-kv--mono"));
  if (c.sale_price !== null && c.sale_price !== undefined) {
    cells.push(_kv("售价", `€${Number(c.sale_price).toFixed(2)}`, "hist-kv--mono"));
  }
  if (c.manual_grade !== null && c.manual_grade !== undefined) {
    cells.push(_kv("等级", escapeHtml(String(c.manual_grade)), "hist-kv--mono"));
  }
  // 状态 用 pill（active accent / inactive muted）
  const statusPill = c.is_active
    ? '<span class="hist-status-pill hist-status-pill--active"><span class="hist-status-dot"></span>在架</span>'
    : '<span class="hist-status-pill hist-status-pill--inactive"><span class="hist-status-dot"></span>下架</span>';
  cells.push(_kv("状态", statusPill));
  cells.push(_kv("来源", escapeHtml(SOURCE_CN[c.source] || c.source), "hist-kv--mono hist-kv--muted"));
  cells.push(_kv("最后更新", escapeHtml(c.updated_at), "hist-kv--mono hist-kv--muted"));

  $("historyCurrent").innerHTML = `<div class="hist-cur-grid">${cells.join("")}</div>`;

  const events = data.events || [];
  if (events.length === 0) {
    $("historyTimeline").innerHTML = '<div class="empty">暂无历史变更</div>';
    return;
  }

  // PR 8a · TimelineEvent 风：左侧 dot + 1px 竖线，按事件类型上色
  const items = events.map((ev, i) => {
    const isLast = i === events.length - 1;
    const detail = ev.summary
      ? `<div class="hist-tle-detail">${escapeHtml(ev.summary)}</div>`
      : (ev.changes && ev.changes.length
          ? `<div class="hist-tle-changes">${ev.changes.map((ch) => {
              const fieldCn = FIELD_CN[ch.field] || ch.field;
              const oldDisp = ch.old ? escapeHtml(ch.old) : '<span class="hist-kv--empty">空</span>';
              const newDisp = ch.new ? escapeHtml(ch.new) : '<span class="hist-kv--empty">空</span>';
              return `<div><span style="color:var(--ink-3)">${escapeHtml(fieldCn)}</span> <span>${oldDisp}</span><span class="hist-tle-change-arrow">→</span><span>${newDisp}</span></div>`;
            }).join("")}</div>`
          : "");
    return `
      <div class="hist-tle" data-type="${escapeHtml(ev.change_type)}">
        <div class="hist-tle-rail">
          <div class="hist-tle-dot"></div>
          ${isLast ? "" : '<div class="hist-tle-line"></div>'}
        </div>
        <div class="hist-tle-body">
          <div class="hist-tle-head">
            <span class="hist-tle-type">${escapeHtml(CHANGE_TYPE_CN[ev.change_type] || ev.change_type)}</span>
            <span class="hist-tle-title">${escapeHtml(SOURCE_CN[ev.source] || ev.source || "")}</span>
            <span class="hist-tle-spacer"></span>
            <span class="hist-tle-time">${escapeHtml(ev.at)}</span>
          </div>
          ${detail}
        </div>
      </div>
    `;
  });
  $("historyTimeline").innerHTML = `
    <div class="hist-tle-count">共 ${events.length} 次操作</div>
    <div class="hist-timeline-list">${items.join("")}</div>
  `;
}

async function doSearch() {
  const q = $("historyInput").value.trim();
  if (!q) {
    renderEmpty("请输入条码或型号");
    return;
  }
  try {
    const resp = await fetch(`/history?q=${encodeURIComponent(q)}`);
    const data = await resp.json();
    if (!data.ok) {
      renderEmpty(`查询失败：${data.msg || "未知错误"}`);
      return;
    }
    if (!data.found) {
      if (data.fuzzy_matches && data.fuzzy_matches.length > 0) {
        renderFuzzyMatches(data.fuzzy_matches, q);
      } else {
        renderEmpty(`未找到 "${q}"，请检查型号或条码是否正确`);
      }
      return;
    }
    renderResult(data);
    loadAnalytics(data.current.barcode);
    loadTimelineChart(data.current.barcode);
    pushRecentQuery(q);
  } catch (err) {
    renderEmpty(`网络错误：${err.message}`);
  }
}

// HTTP 局域网部署常见：navigator.clipboard 仅在 secure context 可用
// fallback 用 execCommand。两条路径都失败才弹 alert
function copyTextFallback(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

async function copyCurrentBarcode(btn) {
  if (!_currentBarcode) return;
  let ok = false;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(_currentBarcode);
      ok = true;
    } catch {
      // 非安全上下文 / 权限拒绝 → 走 fallback
      ok = false;
    }
  }
  if (!ok) ok = copyTextFallback(_currentBarcode);
  if (!ok) {
    alert(`复制失败，请手动复制：${_currentBarcode}`);
    return;
  }
  const orig = btn.textContent;
  btn.textContent = "已复制 ✓";
  setTimeout(() => {
    btn.textContent = orig;
  }, 1200);
}

// ===== RECENT 查询 chip（PR 7）=====
const HISTORY_RECENT_KEY = "history.recentQueries";
const HISTORY_RECENT_MAX = 6;

function loadRecentQueries() {
  try {
    const raw = localStorage.getItem(HISTORY_RECENT_KEY);
    return raw ? JSON.parse(raw).slice(0, HISTORY_RECENT_MAX) : [];
  } catch (_) { return []; }
}

function pushRecentQuery(q) {
  if (!q) return;
  const list = loadRecentQueries().filter((x) => x !== q);
  list.unshift(q);
  const trimmed = list.slice(0, HISTORY_RECENT_MAX);
  try { localStorage.setItem(HISTORY_RECENT_KEY, JSON.stringify(trimmed)); } catch (_) { /* ignore */ }
  renderRecentChips(q);
}

function renderRecentChips(activeQ) {
  const row = $("historyRecentRow");
  const wrap = $("historyRecentChips");
  if (!row || !wrap) return;
  const list = loadRecentQueries();
  if (list.length === 0) {
    row.hidden = true;
    wrap.innerHTML = "";
    return;
  }
  row.hidden = false;
  wrap.innerHTML = list
    .map((q) => {
      const cls = q === activeQ ? "hist-recent-chip is-active" : "hist-recent-chip";
      const safe = q.replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
      return `<button class="${cls}" type="button" data-q="${safe}">${safe}</button>`;
    })
    .join("");
  wrap.querySelectorAll(".hist-recent-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("historyInput").value = btn.dataset.q;
      doSearch();
    });
  });
}

function init() {
  const input = $("historyInput");
  if (!input) return; // 当前不在 history tab
  $("historySearch").addEventListener("click", doSearch);
  $("historyClear").addEventListener("click", () => {
    input.value = "";
    renderEmpty("输入条码或型号后查询历史");
    input.focus();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
  });
  $("historyCopyBarcodeBtn").addEventListener("click", (e) =>
    copyCurrentBarcode(e.currentTarget),
  );

  // 暴露给最近改动模块下钻调用
  window.historySearch = (q) => {
    $("historyInput").value = q;
    doSearch();
  };

  renderRecentChips(null);
}

init();
