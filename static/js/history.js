// 货号历史 tab：精确搜索 + 渲染当前状态 + 聚合时间线
"use strict";

const $ = (id) => document.getElementById(id);

const SOURCE_CN = {
  scan_import: "扫描导入",
  user_correction: "手动修正",
  system_export: "系统导出",
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

function renderEmpty(msg) {
  $("historyHint").textContent = msg;
  $("historyHint").style.display = "";
  $("historyCurrentPanel").hidden = true;
  $("historyTimelinePanel").hidden = true;
  $("historyFuzzyPanel").hidden = true;
  $("historyAnalyticsPanel").hidden = true;
  $("historyTimelineChartPanel").hidden = true;
}

function renderFuzzyMatches(matches, originalQuery) {
  $("historyHint").textContent = `"${originalQuery}" 没有精确匹配，找到 ${matches.length} 条候选`;
  $("historyHint").style.display = "";
  $("historyCurrentPanel").hidden = true;
  $("historyTimelinePanel").hidden = true;
  $("historyFuzzyPanel").hidden = false;
  $("historyAnalyticsPanel").hidden = true;
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
  const panel = $("historyAnalyticsPanel");
  const body = $("historyAnalytics");
  panel.hidden = false;
  body.innerHTML = '<div class="empty">加载中…</div>';
  try {
    const resp = await fetch(`/analytics/sku/${encodeURIComponent(barcode)}`);
    const data = await resp.json();
    if (!data.ok) {
      body.innerHTML = `<div class="empty">${escapeHtml(data.msg || "加载失败")}</div>`;
      return;
    }
    renderAnalytics(data);
  } catch (err) {
    body.innerHTML = `<div class="empty">网络错误：${escapeHtml(err.message)}</div>`;
  }
}

function renderAnalytics(data) {
  const s = data.sales;
  const p = data.purchase;
  const cs = data.customer_split || { cn: {}, fo: {} };
  const autoCat = data.auto_category
    ? `<span class="cat-badge cat-${escapeHtml(data.auto_category)}">${escapeHtml(AUTO_CATEGORY_CN[data.auto_category] || data.auto_category)}</span>`
    : '<span class="empty-val">未计算</span>';
  const computedAt = data.auto_category_computed_at
    ? `<span class="cat-time">（${escapeHtml(data.auto_category_computed_at)}）</span>`
    : "";

  // manual_category 下拉：current 选中态
  const dropdown = renderManualDropdown(data.barcode, data.manual_category);

  // 等级 vs 销量百分位告警
  const gradeRow = renderGradeRow(data.manual_grade, data.qty_percentile);

  $("historyAnalytics").innerHTML = `
    <div class="ana-cat-row">
      <span class="k">自动分类</span>
      <span class="v">${autoCat}${computedAt}</span>
    </div>
    <div class="ana-cat-row">
      <span class="k">人工标签</span>
      <span class="v">${dropdown}</span>
    </div>
    ${gradeRow}

    <div class="ana-section">销售面</div>
    <div class="kv-grid">
      <div><span class="k">总销量</span><span class="v">${fmtNum(s.total_qty)}</span></div>
      <div><span class="k">总营收</span><span class="v">€${(s.total_revenue || 0).toFixed(2)}</span></div>
      <div><span class="k">独立客户</span><span class="v">${fmtNum(s.unique_customers)}</span></div>
      <div><span class="k">寿命</span><span class="v">${s.lifespan_days} 天</span></div>
      <div><span class="k">12 周趋势</span><span class="v">${fmtPct(s.trend_slope_pct_per_week)} / 周</span></div>
    </div>

    <div class="ana-section">客户端拆分</div>
    <div class="ana-cust-split">
      ${renderCustomerEnd("🇨🇳 中国端", cs.cn || {})}
      ${renderCustomerEnd("🇬🇷 老外端", cs.fo || {})}
    </div>

    <div class="ana-section">采购面</div>
    <div class="kv-grid">
      <div><span class="k">库存推算</span><span class="v">${fmtNum(p.stock_balance)}</span></div>
      <div><span class="k">毛利率</span><span class="v">${fmtPct(p.avg_margin_pct)}</span></div>
      <div><span class="k">365 天采购笔数</span><span class="v">${fmtNum(p.purchase_freq_365d)}</span></div>
      <div><span class="k">上次采购</span><span class="v">${fmtDays(p.last_purchase_days_ago)}</span></div>
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
          // 改 data 状态以便下次渲染一致
          data.manual_category = r.manual_category;
        }
      } catch (err) {
        alert(`网络错误：${err.message}`);
        sel.value = data.manual_category || "";
      }
    });
  }
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

function renderCustomerEnd(label, m) {
  const last = m.last_at ? escapeHtml(m.last_at) : '<span class="empty-val">—</span>';
  return `
    <div class="cust-col">
      <div class="cust-col-hd">${label}</div>
      <div class="cust-col-bd">
        <div><span class="k">销量</span><span class="v">${fmtNum(m.qty)}</span></div>
        <div><span class="k">客户数</span><span class="v">${fmtNum(m.unique_customers)}</span></div>
        <div><span class="k">单笔最大</span><span class="v">${fmtNum(m.max_single_qty)}</span></div>
        <div><span class="k">月均频次</span><span class="v">${fmtNum(m.avg_freq_per_month)}</span></div>
        <div><span class="k">上次购买</span><span class="v">${last}</span></div>
      </div>
    </div>
  `;
}

function renderGradeRow(grade, percentile) {
  if (grade === null || grade === undefined) return "";
  const pctText =
    percentile === null || percentile === undefined
      ? '<span class="empty-val">无销售</span>'
      : `${percentile}% 分位`;
  // 不一致告警：grade ≥ 8 但 pct < 30，或 grade ≤ 3 但 pct > 70
  let warn = "";
  if (percentile !== null && percentile !== undefined) {
    if (grade >= 8 && percentile < 30) {
      warn = '<span class="grade-warn">⚠ 高等级低销量</span>';
    } else if (grade <= 3 && percentile > 70) {
      warn = '<span class="grade-warn">⚠ 低等级高销量</span>';
    }
  }
  return `
    <div class="ana-cat-row">
      <span class="k">等级对照</span>
      <span class="v">ERP 等级 ${grade} · 销量 ${pctText} ${warn}</span>
    </div>
  `;
}

function renderResult(data) {
  $("historyHint").style.display = "none";
  $("historyCurrentPanel").hidden = false;
  $("historyTimelinePanel").hidden = false;
  $("historyFuzzyPanel").hidden = true;

  const c = data.current;
  const stores = (c.store_locations || []).map(escapeHtml).join(", ") || '<span class="empty-val">—</span>';
  const warehouses = (c.warehouse_locations || []).map(escapeHtml).join(", ") || '<span class="empty-val">—</span>';
  const unknown = (c.unknown_locations || []).map(escapeHtml).join(", ");
  const unknownRow = unknown
    ? `<div><span class="k">其他位置</span><span class="v" style="color:#cc6600">${unknown}</span></div>`
    : "";
  // 新加字段（来自 product.csv 主档）—— 有值才显示，避免老数据下空白行
  // 注意：分类不展示（roadmap 决策：源 ERP 分类只参考不照抄）
  // 进价不展示（源数据 CNY/EUR 混，无币种字段，会误导）
  const nameZhRow = c.product_name_zh
    ? `<div><span class="k">品名</span><span class="v">${escapeHtml(c.product_name_zh)}</span></div>`
    : "";
  const nameLocalRow = c.product_name_local
    ? `<div><span class="k">本地品名</span><span class="v">${escapeHtml(c.product_name_local)}</span></div>`
    : "";
  const gradeRow = c.manual_grade !== null && c.manual_grade !== undefined
    ? `<div><span class="k">等级</span><span class="v">${escapeHtml(String(c.manual_grade))}</span></div>`
    : "";
  const priceRow = c.sale_price !== null && c.sale_price !== undefined
    ? `<div><span class="k">售价</span><span class="v">€${Number(c.sale_price).toFixed(2)}</span></div>`
    : "";
  $("historyCurrent").innerHTML = `
    <div class="kv-grid">
      <div><span class="k">型号</span><span class="v">${escapeHtml(c.model)}</span></div>
      <div><span class="k">条码</span><span class="v">${escapeHtml(c.barcode)}</span></div>
      ${nameZhRow}
      ${nameLocalRow}
      <div><span class="k">店面位置</span><span class="v">${stores}</span></div>
      <div><span class="k">仓库位置</span><span class="v">${warehouses}</span></div>
      ${unknownRow}
      ${priceRow}
      ${gradeRow}
      <div><span class="k">状态</span><span class="v">${c.is_active ? "在架" : "下架"}</span></div>
      <div><span class="k">来源</span><span class="v">${escapeHtml(SOURCE_CN[c.source] || c.source)}</span></div>
      <div><span class="k">最后更新</span><span class="v">${escapeHtml(c.updated_at)}</span></div>
    </div>
  `;

  const events = data.events || [];
  if (events.length === 0) {
    $("historyTimeline").innerHTML = '<div class="empty">暂无历史变更</div>';
    return;
  }

  const items = events.map((ev) => {
    const changes = ev.changes
      .map((ch) => {
        const fieldCn = FIELD_CN[ch.field] || ch.field;
        const oldVal = ch.old || '<span class="empty-val">空</span>';
        const newVal = ch.new || '<span class="empty-val">空</span>';
        return `<div class="change-row"><span class="change-field">${escapeHtml(fieldCn)}</span><span class="change-arrow">${oldVal === '<span class="empty-val">空</span>' ? oldVal : escapeHtml(ch.old)} → ${newVal === '<span class="empty-val">空</span>' ? newVal : escapeHtml(ch.new)}</span></div>`;
      })
      .join("");
    return `
      <div class="event-item">
        <div class="event-head">
          <span class="event-time">${escapeHtml(ev.at)}</span>
          <span class="event-source">${escapeHtml(SOURCE_CN[ev.source] || ev.source || "")}</span>
          <span class="event-type">[${escapeHtml(CHANGE_TYPE_CN[ev.change_type] || ev.change_type)}]</span>
        </div>
        <div class="event-body">${changes}</div>
      </div>
    `;
  });
  $("historyTimeline").innerHTML = `
    <div class="event-count">共 ${events.length} 次操作</div>
    ${items.join("")}
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
  } catch (err) {
    renderEmpty(`网络错误：${err.message}`);
  }
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

  // 暴露给最近改动模块下钻调用
  window.historySearch = (q) => {
    $("historyInput").value = q;
    doSearch();
  };
}

init();
