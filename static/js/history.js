// 货号历史 tab：精确搜索 + 渲染当前状态 + 聚合时间线
"use strict";

import { escapeHtml, byId as $ } from "./shared.js";

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


function renderEmpty(msg) {
  $("historyHint").textContent = msg;
  $("historyHint").style.display = "";
  if ($("historyLeftTabs")) $("historyLeftTabs").hidden = true;
  if ($("historyDetailCol")) $("historyDetailCol").hidden = true;
  if ($("historyHeroWrap")) $("historyHeroWrap").innerHTML = "";
  $("historyTimelinePanel").hidden = true;
  $("historyFuzzyPanel").hidden = true;
  $("historyAnalyticsPanel").hidden = true;
  if ($("historyPurchasePanel")) $("historyPurchasePanel").hidden = true;
  if ($("historyExtrasPanel")) $("historyExtrasPanel").hidden = true;
  if ($("historyRestockPanel")) $("historyRestockPanel").hidden = true;
  $("historyTimelineChartPanel").hidden = true;
}

function renderFuzzyMatches(matches, originalQuery) {
  $("historyHint").textContent = `"${originalQuery}" 没有精确匹配，找到 ${matches.length} 条候选`;
  $("historyHint").style.display = "";
  if ($("historyLeftTabs")) $("historyLeftTabs").hidden = true;
  if ($("historyDetailCol")) $("historyDetailCol").hidden = true;
  if ($("historyHeroWrap")) $("historyHeroWrap").innerHTML = "";
  $("historyTimelinePanel").hidden = true;
  $("historyFuzzyPanel").hidden = false;
  $("historyAnalyticsPanel").hidden = true;
  if ($("historyPurchasePanel")) $("historyPurchasePanel").hidden = true;
  if ($("historyExtrasPanel")) $("historyExtrasPanel").hidden = true;
  if ($("historyRestockPanel")) $("historyRestockPanel").hidden = true;
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
  panel.hidden = false;
  try {
    const resp = await fetch(`/analytics/sku/${encodeURIComponent(barcode)}/timeline`);
    const data = await resp.json();
    if (!data.ok) {
      renderTmlEmpty(data.msg || "加载失败");
      return;
    }
    renderTmlSvg(data.timeline || [], data.monthly_sales || []);
  } catch (err) {
    renderTmlEmpty(`网络错误：${err.message}`);
  }
}

function renderTmlEmpty(msg) {
  $("historyTimelineChart").innerHTML = `<div class="hist-tml-empty">${escapeHtml(msg)}</div>`;
  $("historyTimelineXAxis").innerHTML = "";
  const yl = $("historyTimelineYLeft");
  const yr = $("historyTimelineYRight");
  if (yl) yl.innerHTML = "";
  if (yr) yr.innerHTML = "";
}

// PR 8b · 时间线 SVG (2026-05-23 重写: 3 年 = 156 周进价 / 36 月销量柱)
// 柱状: monthly_sales (36 月, 宽柱不挤)
// 进价线/点: timeline (156 周, 阶梯前向填充 + dot on 真实进货事件)
// viewBox 1000×200 + preserveAspectRatio="none". X label HTML overlay.
function renderTmlSvg(timeline, monthlySales) {
  const xAxis = $("historyTimelineXAxis");
  if (!timeline || timeline.length === 0) {
    renderTmlEmpty("无数据");
    return;
  }
  // 月度销量 fallback: 老 API 没 monthly_sales 字段 → 按 week 用 timeline
  const months = (monthlySales && monthlySales.length > 0) ? monthlySales : null;

  const n = timeline.length;  // 周数 (156)
  const rawPrices = timeline.map((t) => t.purchase_unit_price);
  // 销量柱用 monthly_sales (sale_qty + retail_qty); 没有就退化到 weekly
  const sales = months
    ? months.map((m) => (m.sale_qty || 0) + (m.retail_qty || 0))
    : timeline.map((t) => t.sale_qty || 0);
  const maxQ = Math.max(1, ...sales);
  const validPrices = rawPrices.filter((p) => p !== null && p !== undefined);
  const hasPrices = validPrices.length > 0;
  // 前向填充 + 反向外推:
  // - null 沿用上次进价 (语义: 没新采购前进价没变, 阶梯线)
  // - 最早进价之前段也用第一个进价填 (避免起点段空白)
  const prices = (() => {
    const out = new Array(n).fill(null);
    const firstValid = rawPrices.findIndex((v) => v !== null && v !== undefined);
    if (firstValid < 0) return out;
    const firstValue = rawPrices[firstValid];
    let last = firstValue;
    for (let i = 0; i < n; i++) {
      const v = rawPrices[i];
      if (v !== null && v !== undefined) last = v;
      out[i] = last;  // 前段沿用 firstValue, 后段前向填充
    }
    return out;
  })();
  const maxP = hasPrices ? Math.max(...validPrices) : 1;
  const minP = hasPrices ? Math.min(...validPrices) : 0;
  // Y 轴从 0 起 (2026-05-23 用户反馈): 避免 min 价贴 baseline 看着像"压地".
  // 代价: 高价区分辨率压缩, 但波动语义保留 (€5.20 vs €5.80 仍能看出来).
  const sameValue = hasPrices && maxP === minP;
  const priceRange = Math.max(0.01, maxP);  // 从 0 到 max

  const W = 1000;
  const H = 200;
  const padL = 32;
  const padR = 36;
  const padT = 12;
  const padB = 8;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const stepW = innerW / n;             // 周 step (用于进价线 X 位置)
  // 月柱用 monthly_sales 长度算 step; 退化时跟周 step 一致
  const barCount = months ? months.length : n;
  const barStep = innerW / barCount;
  const barW = Math.max(1, barStep - 2);

  // 网格（Y 轴标签改到 HTML overlay 避免 preserveAspectRatio=none 拉伸字形）
  const gridParts = [];
  [0.25, 0.5, 0.75, 1].forEach((f) => {
    const y = padT + innerH * (1 - f);
    gridParts.push(
      `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" stroke="var(--line-soft)" stroke-width="1" stroke-dasharray="2 4"/>`,
    );
  });

  // Y 轴 HTML overlay (在 innerH 内按比例放 span)
  const yPxOf = (f) => padT + innerH * (1 - f);
  const chartTopOffset = padT;
  const renderYAxis = () => {
    // 左轴: 销量 4 ticks
    const leftHtml = [0.25, 0.5, 0.75, 1].map((f) => {
      // SVG Y 坐标 (0..H) → HTML top% relative to .hist-tml-yaxis (高度 = 200px 同 SVG)
      const topPct = (yPxOf(f) / H) * 100;
      return `<span style="top:${topPct.toFixed(2)}%">${Math.round(maxQ * f)}</span>`;
    }).join("");
    $("historyTimelineYLeft").innerHTML = leftHtml;
    // 右轴: 进价 (Y 轴从 0 起到 maxP)
    let rightHtml = "";
    if (hasPrices) {
      if (sameValue) {
        // 同价 → 只在折线那条 y (innerH * 0.4) 放 1 个 label
        const topPct = ((padT + innerH * 0.4) / H) * 100;
        rightHtml = `<span style="top:${topPct.toFixed(2)}%">€${maxP.toFixed(2)}</span>`;
      } else {
        rightHtml = [0, 0.25, 0.5, 0.75, 1].map((f) => {
          const topPct = (yPxOf(f) / H) * 100;
          const v = (maxP * f).toFixed(2);  // 从 0 起
          return `<span style="top:${topPct.toFixed(2)}%">€${v}</span>`;
        }).join("");
      }
    }
    $("historyTimelineYRight").innerHTML = rightHtml;
  };
  void chartTopOffset;  // 保留变量供阅读

  // 销量柱 (月度: 36 根宽柱)
  const barParts = sales.map((qty, i) => {
    if (qty === 0) return "";
    const x = padL + i * barStep + 1;
    const barH = (qty / maxQ) * innerH * 0.85;
    const y = padT + innerH - barH;
    const fill = qty > maxQ * 0.6 ? "var(--accent)" : "var(--accent-dim)";
    const title = months ? `${months[i]?.month_start ?? ''}: ${qty} 件` : '';
    return `<rect x="${x}" y="${y}" width="${barW}" height="${barH}" fill="${fill}" opacity="0.85" rx="0.5"><title>${escapeHtml(title)}</title></rect>`;
  });

  // 进价折线 (前向填充后是阶梯线, null 段在最早进价之前不画).
  // 同价 (sameValue) 时 Y 固定中段, 避免跟 baseline 撞.
  let pathD = "";
  const dotParts = [];
  let started = false;
  prices.forEach((p, i) => {
    if (p === null || p === undefined) {
      started = false;
      return;
    }
    const x = padL + (i + 0.5) * stepW;
    const y = sameValue
      ? padT + innerH * 0.4   // 中段稍偏上, 跟柱状销量留出层次
      : padT + innerH - (p / priceRange) * innerH * 0.85;  // 从 0 到 maxP, 不贴地
    pathD += started ? ` L${x.toFixed(1)},${y.toFixed(1)}` : `M${x.toFixed(1)},${y.toFixed(1)}`;
    started = true;
    // 只在原始数据点 (非填充) 上放 dot, 让用户看到"哪周真有进货"
    if (rawPrices[i] !== null && rawPrices[i] !== undefined) {
      const wk = timeline[i];
      const raw = wk?.raw_unit_price_local;
      const cur = wk?.currency_local;
      // CN 货: tooltip 拆解 RMB 单价 + EUR 落地; FOREIGN: 仅 EUR
      let tip = `${wk?.week_start ?? ''} · €${p.toFixed(4)}`;
      if (cur === "RMB" && raw != null) {
        tip = `${wk?.week_start ?? ''}\n€${p.toFixed(4)} (落地)\n← ¥${raw} (RMB 进价) / 7.8 + 海运分摊`;
      }
      dotParts.push(`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5" fill="var(--warn)"><title>${escapeHtml(tip)}</title></circle>`);
    }
  });
  const linePart = pathD
    ? `<path d="${pathD}" stroke="var(--warn)" stroke-width="1.5" fill="none" vector-effect="non-scaling-stroke"/>`
    : "";

  // baseline
  const baseline = `<line x1="${padL}" x2="${W - padR}" y1="${padT + innerH}" y2="${padT + innerH}" stroke="var(--line)" stroke-width="1"/>`;

  $("historyTimelineChart").innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="hist-tml-svg">
      ${gridParts.join("")}
      ${barParts.join("")}
      ${linePart}
      ${dotParts.join("")}
      ${baseline}
    </svg>
  `;
  renderYAxis();

  // X 轴月份 label: 7 个均匀分布 (3 年覆盖 ~36 月, 每 ~6 月 1 个)
  const labelSrc = months || timeline;
  const labelCount = Math.min(7, labelSrc.length);
  const xLabels = [];
  for (let i = 0; i < labelCount; i++) {
    const idx = Math.floor(((labelSrc.length - 1) * i) / Math.max(1, labelCount - 1));
    const pt = labelSrc[idx];
    const ts = pt?.month_start || pt?.week_start;
    if (ts) xLabels.push(`<span>${escapeHtml(ts.slice(0, 7))}</span>`);
  }
  xAxis.innerHTML = xLabels.join("");
}

async function loadAnalytics(barcode) {
  const slaPanel = $("historyAnalyticsPanel");
  const purPanel = $("historyPurchasePanel");
  const extPanel = $("historyExtrasPanel");
  const slaBody = $("historyAnalytics");
  const purBody = $("historyPurchase");
  slaPanel.hidden = false;
  if (purPanel) purPanel.hidden = false;
  if (extPanel) extPanel.hidden = false;
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
  renderPUR(data.purchase || {}, data);
  renderExtras(data);
  renderRestockSnapshot(data.restock_snapshot);
}

// 货号历史复用补货决策 drawer 的指标 (2026-05-23): 让"非补货"场景下也能
// 看完整的财务 / 库存 / 累计盈亏 / 销售 26w / 紧迫分.
function renderRestockSnapshot(it) {
  const panel = document.getElementById("historyRestockPanel");
  const root = document.getElementById("historyRestock");
  if (!panel || !root) return;
  if (!it) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const bd = it.urgency_breakdown;
  const dv = bd?.demand_validity;
  const dvTag = (dv != null && dv < 1.0) ? ` <span class="rs-dv-tag" title="长尾活跃度折扣">×${dv}</span>` : "";
  const fmtNum2 = (v, d = 2) => (v === null || v === undefined) ? "—" : Number(v).toFixed(d);
  const fmtInt = (v) => (v === null || v === undefined) ? "—" : Math.round(v);
  const fmtEur = (v) => (v === null || v === undefined) ? "—" : `€${Number(v).toFixed(2)}`;
  const fmtEurInt = (v) => (v === null || v === undefined) ? "—" : `€${Math.round(v)}`;
  // 零售价行: observed vs estimate 并排展示
  const rpObs = it.retail_price_observed;
  const rpEst = it.retail_price_estimate;
  let retailLine;
  if (rpObs != null && rpEst != null) {
    retailLine = `零售价 <b>${fmtEur(rpObs)}</b> <span class="rs-drawer-muted">(实际 ${it.retail_qty_26w} 笔)</span> · 估算 ${fmtEur(rpEst)} (×2)`;
  } else if (rpObs != null) {
    retailLine = `零售价 <b>${fmtEur(rpObs)}</b> <span class="rs-drawer-muted">(实际)</span>`;
  } else if (rpEst != null) {
    retailLine = `零售价 <b>${fmtEur(rpEst)}</b> <span class="rs-drawer-muted">(批发×2 估算)</span>`;
  } else {
    retailLine = `零售价 —`;
  }
  // 累计盈亏状态
  const rp = it.realized_profit_eur;
  const inv = it.inventory_cost_value_eur ?? 0;
  let badge, line;
  if (rp == null) {
    badge = '<span class="rs-profit-badge rs-profit-badge--unknown">缺成本</span>';
    line = '<span class="rs-drawer-muted">无 cost 数据</span>';
  } else if (rp > 0) {
    badge = '<span class="rs-profit-badge rs-profit-badge--good">💚 已回本</span>';
    line = `实现利润 <b>+€${fmtInt(rp)}</b>`;
  } else if (rp + inv > 0) {
    badge = '<span class="rs-profit-badge rs-profit-badge--mid">🟡 压货中</span>';
    line = `实现利润 <b>€${fmtInt(rp)}</b> · 库存能补 <b>€${fmtInt(inv)}</b> 回本`;
  } else {
    badge = '<span class="rs-profit-badge rs-profit-badge--bad">🔴 账面亏损</span>';
    line = `实现利润 <b>€${fmtInt(rp)}</b> + 库存 <b>€${fmtInt(inv)}</b> 仍亏 <b>€${fmtInt(-(rp + inv))}</b>`;
  }
  // 净现金流并列显示 (2026-05-23 A): 大库存差异时 FIFO 乐观 vs cashflow 保守
  const ncf = it.net_cashflow_eur;
  const imb = it.inventory_imbalance_pct;
  let cashflowLine = "";
  if (ncf !== null && ncf !== undefined) {
    const imbWarn = (imb != null && imb > 30)
      ? ` <span class="rs-trunc-warn" title="进销库存差 ${imb}% > 30%, FIFO 可能高估, 实际请看净现金流">⚠️ 不平 ${imb}%</span>`
      : '';
    cashflowLine = `<div>净现金流 <b>${ncf >= 0 ? '+' : ''}€${fmtInt(ncf)}</b>${imbWarn}</div>`;
  }
  // 紧迫分四维 (dv 应用在 cover/recency)
  const coverScore = bd ? `${bd.cover}${dvTag}` : "—";
  const recencyScore = bd ? `${bd.recency}${dvTag}` : "—";
  const velocityScore = bd ? bd.velocity : "—";
  const marginScore = bd ? bd.margin : "—";

  root.innerHTML = `
    <div class="rst-grid">
      <div class="rst-sec">
        <h4>💰 财务</h4>
        <div class="rst-row">批发 <b>${fmtEur(it.master_sale_price_eur ?? it.sale_net_avg)}</b> <span class="rst-muted">(主档)</span></div>
        <div class="rst-row">${retailLine}</div>
        <div class="rst-row">进价 <b>${fmtEur(it.last_purchase_unit_price ?? it.master_stock_price_eur)}</b></div>
        <div class="rst-row">毛利 <b>${it.margin_pct != null ? it.margin_pct + '%' : '—'}</b></div>
      </div>
      <div class="rst-sec">
        <h4>📦 库存</h4>
        <div class="rst-row">库存 <b>${fmtInt(it.qty_total)} 件</b></div>
        <div class="rst-row">可销额 <b>${fmtEur(it.inventory_sale_value_eur)}</b></div>
        <div class="rst-row">成本 <b>${fmtEur(it.inventory_cost_value_eur)}</b></div>
        <div class="rst-row">可撑 <b>${it.weeks_of_cover != null ? it.weeks_of_cover.toFixed(1) + ' 周' : '—'}</b></div>
      </div>
      <div class="rst-sec">
        <h4>💵 累计盈亏 ${badge}</h4>
        <div class="rst-row">投入 <b>${fmtEur(it.lifetime_invested_eur)}</b> <span class="rst-muted">(${fmtInt(it.lifetime_purchase_qty)} 件)</span></div>
        <div class="rst-row">销售 <b>${fmtEurInt(it.lifetime_sale_revenue_eur)}</b> <span class="rst-muted">(${fmtInt(it.lifetime_sale_qty)} 件)</span></div>
        <div class="rst-row">${line}</div>
        ${cashflowLine}
      </div>
      <div class="rst-sec">
        <h4>📊 销售 26 周</h4>
        <div class="rst-row">周销 <b>${fmtNum2(it.weekly_velocity, 2)} 件/周</b></div>
        <div class="rst-row">周额 <b>€${fmtNum2(it.weekly_revenue, 2)}/周</b></div>
        <div class="rst-row">活跃 <b>${fmtInt(it.n_active_weeks_26w)} 周</b></div>
        <div class="rst-row">距进货 <b>${it.last_purchase_days_ago != null ? it.last_purchase_days_ago + ' 天' : '—'}</b></div>
      </div>
      <div class="rst-sec">
        <h4>🎯 紧迫 ${it.urgency_score ?? '—'}</h4>
        <div class="rst-row">销额 <b>${velocityScore}</b>/30</div>
        <div class="rst-row">库存 <b>${coverScore}</b>/30</div>
        <div class="rst-row">距进货 <b>${recencyScore}</b>/10</div>
        <div class="rst-row">毛利 <b>${marginScore}</b>/30</div>
      </div>
    </div>
  `;
}

function renderSLA(data) {
  const s = data.sales || {};
  const cs = data.customer_split || { cn: {}, fo: {} };
  // 2026-05-23 移除自动分类 + 人工标签行 (用户: 已无用处). 等级对照保留 (qty 分位仍有意义).
  const dailyAvg = ((s.total_qty || 0) / Math.max(1, s.lifespan_days || 1)).toFixed(2);

  $("historyAnalytics").innerHTML = `
    <div class="sla-grid">
      ${_seckv("总销量", fmtNum(s.total_qty), "kv-val--mono kv-val--accent")}
      ${_seckv("总营收", `€${(s.total_revenue || 0).toFixed(2)}`, "kv-val--mono kv-val--accent")}
      ${_seckv("独立客户", fmtNum(s.unique_customers), "kv-val--mono")}
      ${_seckv("寿命", `${s.lifespan_days || 0} 天`, "kv-val--mono")}
      ${_seckv("日均件数", dailyAvg, "kv-val--mono")}
      ${_seckv("12 周趋势", `${fmtPct(s.trend_slope_pct_per_week)} / 周`, "kv-val--mono")}
    </div>
    <div class="s-label">CLIENT SPLIT · 客户端拆分</div>
    <div class="cust-split">
      ${renderClientCard("cn", "中国", cs.cn || {})}
      ${renderClientCard("gr", "老外", cs.fo || {})}
    </div>
  `;
}

function renderPUR(p) {
  const purBody = $("historyPurchase");
  if (!purBody) return;
  const stockBalance = p.stock_balance;
  const stockNegative = typeof stockBalance === "number" && stockBalance < 0;
  const warnBox = stockNegative
    ? `<div style="margin-top:8px;padding:6px 10px;border-left:2px solid var(--warn);background:var(--warn-subtle);border-radius:var(--r-sm);font-size:var(--fs-sm);color:var(--ink-1);">⚠ 库存推算为负 — 历史采购数据缺失或未导入，建议在「进销存导入」补录。</div>`
    : "";
  purBody.innerHTML = `
    <div class="sla-grid" style="grid-template-columns:repeat(4,1fr);">
      ${_seckv("库存推算", fmtNum(stockBalance), "kv-val--mono")}
      ${_seckv("毛利率", fmtPct(p.avg_margin_pct), "kv-val--mono")}
      ${_seckv("365 天采购", fmtNum(p.purchase_freq_365d), "kv-val--mono")}
      ${_seckv("上次采购", fmtDays(p.last_purchase_days_ago), "kv-val--mono")}
    </div>
    ${warnBox}
  `;
}

// 货号历史扩展数据 (波 3, 2026-05-23): 退货 / 价格波动 / 客户 TOP10 /
// 月度热力图 / 持仓周期 / 下季度预测 / 数据范围 + 完整性
function renderExtras(data) {
  const root = document.getElementById("historyExtras");
  if (!root) return;
  const ex = data.extras || {};
  const h = data.holding || {};
  const heat = data.heatmap || {};
  const fc = data.forecast;

  // 退货率 + 价格波动
  const ps = ex.price_stats || {};
  const returnSec = `
    <div class="ext-section">
      <div class="ext-section-label">退货率 + 价格波动</div>
      ${_curkv("退货率", `${ex.return_rate_pct != null ? ex.return_rate_pct + '%' : '—'} <span class="ext-muted">(${ex.return_qty ?? 0}/${(ex.total_sale_qty_gross ?? 0) + (ex.return_qty ?? 0)})</span>`)}
      ${_curkv("批发售价均", `€${ps.mean ?? '—'} ±${ps.std ?? '—'}`, "cur-kv-val--mono")}
      ${_curkv("售价区间", `€${ps.min ?? '—'} ~ €${ps.max ?? '—'}`, "cur-kv-val--mono")}
    </div>`;

  // 零售汇总 (MB700 + customer_id='0')
  const rs = ex.retail_summary || {};
  const retailSec = rs.n_transactions > 0
    ? `<div class="ext-section">
        <div class="ext-section-label">零售汇总 (MB700 + ID=0)</div>
        ${_curkv("件数 / 营收", `${rs.qty} · €${rs.revenue}`, "cur-kv-val--mono")}
        ${_curkv("笔数 / 件均", `${rs.n_transactions} 笔 · ${rs.avg_ticket_qty ?? '—'}`, "cur-kv-val--mono")}
        ${_curkv("最近零售", escapeHtml(String(rs.last_at ?? '—')), "cur-kv-val--mono cur-kv-val--muted")}
      </div>`
    : `<div class="ext-section"><div class="ext-section-label">零售汇总</div><div class="ext-muted">暂无零售记录 (MB700 / ID=0)</div></div>`;

  // 客户 TOP — CN / GR 各一个 mini-tbl（名字带中文一律 CN）
  const miniTbl = (rows) => {
    const trs = (rows || []).map((c) => `<tr>
      <td class="id">${escapeHtml(c.customer_id || '')}</td>
      <td>${escapeHtml(c.customer_name || '—')}</td>
      <td class="r">${c.qty}</td>
      <td class="r">${escapeHtml(String(c.last_at || ''))}</td>
    </tr>`).join('') || '<tr><td colspan="4" class="ext-muted">—</td></tr>';
    return `<table class="ext-mini-tbl"><thead><tr><th>ID</th><th>名字</th><th class="r">件</th><th class="r">上次</th></tr></thead><tbody>${trs}</tbody></table>`;
  };
  const cnSec = `<div class="ext-section"><div class="ext-section-label"><span class="cust-tag cust-tag--cn">CN</span> 中国客户 TOP</div>${miniTbl(ex.top_customers_cn)}</div>`;
  const grSec = `<div class="ext-section"><div class="ext-section-label"><span class="cust-tag cust-tag--gr">GR</span> 老外客户 TOP</div>${miniTbl(ex.top_customers_foreign)}</div>`;

  // 月度热力图 (4 年 × 12 月) — heat-mini
  const monthTh = ['1','2','3','4','5','6','7','8','9','10','11','12'].map(m => `<th>${m}</th>`).join('');
  const heatMax = heat.max_qty || 1;
  const heatRows = (heat.years || []).slice().reverse().map(y => {
    const row = heat.matrix[y] || new Array(12).fill(0);
    const cells = row.map((q, mi) => {
      const isPeak = q === heatMax && q > 0;
      const intensity = q > 0 ? Math.max(0.12, q / heatMax) : 0;
      const cls = isPeak ? 'hc hc--peak' : 'hc';
      const style = (q > 0 && !isPeak) ? ` style="background:rgba(46,160,67,${intensity.toFixed(2)});color:var(--ink-0);"` : '';
      return `<td class="${cls}"${style} title="${y}-${(mi+1).toString().padStart(2,'0')}: ${q} 件">${q > 0 ? q : '—'}</td>`;
    }).join('');
    return `<tr><td class="hy">${String(y).slice(2)}</td>${cells}</tr>`;
  }).join('');
  const heatSec = `<div class="ext-section"><div class="ext-section-label">🌡 月度热力图 (4 年)</div>
    <table class="heat-mini"><thead><tr><th></th>${monthTh}</tr></thead><tbody>${heatRows}</tbody></table></div>`;

  // 持仓 / 预测 / 数据范围
  const truncWarn = ex.is_history_truncated ? ' <span class="ext-warn">⚠ 不全</span>' : '';
  const holdRows = [];
  if (h.avg_days != null) holdRows.push(_curkv("平均持仓", `${h.avg_days} 天 <span class="ext-muted">(${h.n_pairs} 件)</span>`, "cur-kv-val--mono"));
  if (h.oldest_held_days != null) holdRows.push(_curkv("当前压最久", `${h.oldest_held_days} 天`, "cur-kv-val--mono"));
  holdRows.push(fc
    ? _curkv("下季度预测", `${fc.quarter_mu} 件 <span class="ext-muted">(p98 ${fc.quarter_p98})</span>`, "cur-kv-val--mono")
    : _curkv("预测", `<span class="ext-muted">序列太短未训出</span>`));
  holdRows.push(_curkv("数据范围", `${escapeHtml(String(ex.first_event_at ?? '—'))} ~ ${escapeHtml(String(ex.last_event_at ?? '—'))}${truncWarn}`, "cur-kv-val--muted"));
  const miscSec = `<div class="ext-section"><div class="ext-section-label">🔮 持仓 / 预测</div>${holdRows.join("")}</div>`;

  root.innerHTML = returnSec + retailSec + cnSec + grSec + heatSec + miscSec;
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
  const TAG = String(tag).toUpperCase();
  return `
    <div class="cust-card">
      <div class="cust-hd"><span class="cust-tag cust-tag--${tag}">${TAG}</span> ${escapeHtml(name)}</div>
      <div class="cust-row">销量 <b>${fmtNum(m.qty)}</b> · 客户 <b>${fmtNum(m.unique_customers)}</b></div>
      <div class="cust-row">单笔最大 <b>${fmtNum(m.max_single_qty)}</b> · 月频 <b>${fmtNum(m.avg_freq_per_month)}</b></div>
      <div class="cust-row">上次 <b>${last}</b></div>
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

// v2 设计: 左列概况 KV 行（label 左 / value 右）
function _curkv(k, v, valMods = "") {
  return `<div class="cur-kv"><span class="cur-kv-label">${escapeHtml(k)}</span><span class="cur-kv-val ${valMods}">${v}</span></div>`;
}
// v2 设计: 右列 sec 内 KV box（label 上 / value 下）
function _seckv(k, v, valMods = "") {
  return `<div class="kv"><div class="kv-label">${escapeHtml(k)}</div><div class="kv-val ${valMods}">${v}</div></div>`;
}

function renderResult(data) {
  $("historyHint").style.display = "none";
  if ($("historyLeftTabs")) $("historyLeftTabs").hidden = false;
  if ($("historyDetailCol")) $("historyDetailCol").hidden = false;
  $("historyTimelinePanel").hidden = false;
  $("historyFuzzyPanel").hidden = true;

  const c = data.current;
  _currentBarcode = c.barcode;

  // hero: 型号 + 条码 + 状态 pill + grade badge + 复制按钮（复用已绑 handler 的静态按钮）
  const statusPill = c.is_truly_discontinued
    ? '<span class="status-pill status-pill--inactive"><span class="status-dot"></span>已停售</span>'
    : '<span class="status-pill status-pill--active"><span class="status-dot"></span>在售</span>';
  const gradeBadge = (c.manual_grade !== null && c.manual_grade !== undefined)
    ? `<span class="grade-badge">${escapeHtml(String(c.manual_grade))}</span>` : "";
  $("historyHeroWrap").innerHTML = `
    <div class="cur-hero">
      <div class="cur-model">${escapeHtml(c.model || "—")}</div>
      <div class="cur-barcode">${escapeHtml(c.barcode)}</div>
      <div class="cur-status" id="historyHeroStatus">${statusPill}${gradeBadge}<span style="flex:1"></span></div>
    </div>`;
  // 把已在 init 绑好 click 的复制按钮移进 hero（避免重建丢 handler）
  const copyBtn = $("historyCopyBarcodeBtn");
  if (copyBtn) {
    copyBtn.hidden = false;
    copyBtn.removeAttribute("style");
    copyBtn.className = "btn btn--ghost";
    copyBtn.style.fontSize = "var(--fs-xs)";
    copyBtn.style.padding = "3px 8px";
    copyBtn.textContent = "⎘ 复制";
    document.getElementById("historyHeroStatus").appendChild(copyBtn);
  }

  // 概况（左列 overview）：品名 / 位置 / 售价 / 来源 / 更新
  // 注意：分类/进价不展示（源 ERP 分类只参考；进价 CNY/EUR 混无币种字段会误导）
  const storesText = (c.store_locations || []).map(escapeHtml).join(", ");
  const warehousesText = (c.warehouse_locations || []).map(escapeHtml).join(", ");
  const unknownText = (c.unknown_locations || []).map(escapeHtml).join(", ");
  const ov = [];
  if (c.product_name_zh) ov.push(_curkv("品名", escapeHtml(c.product_name_zh)));
  if (c.product_name_local) ov.push(_curkv("本地品名", escapeHtml(c.product_name_local), "cur-kv-val--mono cur-kv-val--muted"));
  ov.push(_curkv("店面位置", storesText || "—", storesText ? "cur-kv-val--mono" : "cur-kv-val--muted"));
  ov.push(_curkv("仓库位置", warehousesText || "—", warehousesText ? "cur-kv-val--mono" : "cur-kv-val--muted"));
  if (unknownText) ov.push(_curkv("其他位置", unknownText, "cur-kv-val--mono"));
  if (c.sale_price !== null && c.sale_price !== undefined) {
    ov.push(_curkv("售价", `€${Number(c.sale_price).toFixed(2)}`, "cur-kv-val--mono"));
  }
  ov.push(_curkv("来源", escapeHtml(SOURCE_CN[c.source] || c.source), "cur-kv-val--mono cur-kv-val--muted"));
  ov.push(_curkv("最后更新", escapeHtml(c.updated_at), "cur-kv-val--mono cur-kv-val--muted"));
  $("historyCurrent").innerHTML = ov.join("");

  const events = data.events || [];
  if (events.length === 0) {
    $("historyTimeline").innerHTML = '<div class="ext-muted" style="padding:4px 0;">暂无历史变更</div>';
    return;
  }

  // v2 evt 时间线：左侧 dot + 1px 竖线，按事件类型上色
  const items = events.map((ev, i) => {
    const isLast = i === events.length - 1;
    const detail = ev.summary
      ? `<div class="evt-detail">${escapeHtml(ev.summary)}</div>`
      : (ev.changes && ev.changes.length
          ? `<div class="evt-detail">${ev.changes.map((ch) => {
              const fieldCn = FIELD_CN[ch.field] || ch.field;
              const oldDisp = ch.old ? `<code>${escapeHtml(ch.old)}</code>` : '<span class="ext-muted">空</span>';
              const newDisp = ch.new ? `<code>${escapeHtml(ch.new)}</code>` : '<span class="ext-muted">空</span>';
              return `<div><span style="color:var(--ink-3)">${escapeHtml(fieldCn)}</span> ${oldDisp}<span class="evt-arrow">→</span>${newDisp}</div>`;
            }).join("")}</div>`
          : "");
    return `
      <div class="evt" data-type="${escapeHtml(ev.change_type)}">
        <div class="evt-rail"><div class="evt-dot"></div>${isLast ? "" : '<div class="evt-line"></div>'}</div>
        <div class="evt-body">
          <div class="evt-head">
            <span class="evt-type">${escapeHtml(CHANGE_TYPE_CN[ev.change_type] || ev.change_type)}</span>
            <span class="evt-src">${escapeHtml(SOURCE_CN[ev.source] || ev.source || "")}</span>
            <span class="evt-time">${escapeHtml(ev.at)}</span>
          </div>
          ${detail}
        </div>
      </div>
    `;
  });
  $("historyTimeline").innerHTML = `<div class="ext-muted" style="margin-bottom:8px;">共 ${events.length} 次操作</div>${items.join("")}`;
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

  // v2 左列子 tab（概况 / 深度）切换
  const leftTabs = $("historyLeftTabs");
  if (leftTabs) {
    leftTabs.addEventListener("click", (e) => {
      const btn = e.target.closest(".left-tab");
      if (!btn) return;
      const t = btn.dataset.ltab;
      leftTabs.querySelectorAll(".left-tab").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll("#historyCurCol .left-panel").forEach((p) => {
        p.classList.toggle("active", p.dataset.lpanel === t);
      });
    });
  }

  // 暴露给最近改动模块下钻调用
  window.historySearch = (q) => {
    $("historyInput").value = q;
    doSearch();
  };

  renderRecentChips(null);
}

init();
