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
  if ($("historyExtrasPanel")) $("historyExtrasPanel").hidden = true;
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
  if ($("historyExtrasPanel")) $("historyExtrasPanel").hidden = true;
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

// 货号历史扩展数据 (波 3, 2026-05-23): 退货 / 价格波动 / 客户 TOP10 /
// 月度热力图 / 持仓周期 / 下季度预测 / 数据范围 + 完整性
function renderExtras(data) {
  const root = document.getElementById("historyExtras");
  if (!root) return;
  const ex = data.extras || {};
  const h = data.holding || {};
  const heat = data.heatmap || {};
  const fc = data.forecast;

  // 1. 退货 + 价格波动 卡片
  const ps = ex.price_stats || {};
  const returnCard = `
    <section class="hist-ex-card">
      <h4>📊 退货率 + 价格波动</h4>
      <div class="hist-ex-row">退货率 <b>${ex.return_rate_pct != null ? ex.return_rate_pct + '%' : '—'}</b>
        <span class="hist-ex-muted">(${ex.return_qty ?? 0} / ${(ex.total_sale_qty_gross ?? 0) + (ex.return_qty ?? 0)} 件)</span></div>
      <div class="hist-ex-row">批发售价均 <b>€${ps.mean ?? '—'}</b> ± ${ps.std ?? '—'} <span class="hist-ex-muted">(${ps.n} 笔)</span></div>
      <div class="hist-ex-row">售价区间 <b>€${ps.min ?? '—'}</b> ~ <b>€${ps.max ?? '—'}</b></div>
    </section>`;

  // 2. 客户 TOP10
  const topRows = (ex.top_customers || []).map((c, i) => {
    const typeBadge = c.customer_type === 'chinese'
      ? '<span class="hist-ex-type hist-ex-type--cn">CN</span>'
      : c.customer_type === 'foreign'
      ? '<span class="hist-ex-type hist-ex-type--fo">GR</span>'
      : '<span class="hist-ex-type hist-ex-type--unk">?</span>';
    return `<tr>
      <td class="hist-ex-rank">${i + 1}</td>
      <td>${typeBadge}</td>
      <td class="hist-ex-mono">${escapeHtml(c.customer_id || '')}</td>
      <td>${escapeHtml(c.customer_name || '—')}</td>
      <td class="hist-ex-num">${c.qty}</td>
      <td class="hist-ex-mono">${c.last_at || ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" class="hist-ex-empty">暂无客户记录</td></tr>';
  const topCustomersCard = `
    <section class="hist-ex-card hist-ex-card--wide">
      <h4>👥 客户 TOP 10 (按净 qty)</h4>
      <table class="hist-ex-top">
        <thead><tr><th>#</th><th></th><th>客户 ID</th><th>名字</th><th>件数</th><th>上次</th></tr></thead>
        <tbody>${topRows}</tbody>
      </table>
    </section>`;

  // 3. 月度热力图 (4 年 × 12 月)
  const monthNames = ['1','2','3','4','5','6','7','8','9','10','11','12'];
  const heatMax = heat.max_qty || 1;
  const heatRows = (heat.years || []).slice().reverse().map(y => {
    const row = heat.matrix[y] || [0]*12;
    const cells = row.map((q, mi) => {
      const intensity = q > 0 ? Math.max(0.15, q / heatMax) : 0;
      const bg = intensity > 0
        ? `background: rgba(46, 160, 67, ${intensity.toFixed(2)});`
        : 'background: var(--surface-2);';
      const label = q > 0 ? q : '';
      const title = `${y}-${(mi+1).toString().padStart(2,'0')}: ${q} 件`;
      return `<td class="hist-ex-heat-cell" style="${bg}" title="${title}">${label}</td>`;
    }).join('');
    return `<tr><th class="hist-ex-heat-year">${y}</th>${cells}</tr>`;
  }).join('');
  const heatmapCard = `
    <section class="hist-ex-card hist-ex-card--wide">
      <h4>🌡 月度销量热力图 (4 年)</h4>
      <table class="hist-ex-heat">
        <thead><tr><th></th>${monthNames.map(m => `<th>${m}月</th>`).join('')}</tr></thead>
        <tbody>${heatRows}</tbody>
      </table>
    </section>`;

  // 4. 持仓 + 预测 + 数据范围 卡片
  const truncWarn = ex.is_history_truncated
    ? '<span class="hist-ex-warn" title="首笔事件早于 ETL 窗口起点 2021-06-01, 更早期事件未纳入">⚠️ 历史可能不全</span>'
    : '';
  const fcLine = fc
    ? `<div class="hist-ex-row">下季度预测 <b>${fc.quarter_mu}</b> 件 <span class="hist-ex-muted">(p98 ${fc.quarter_p98}, 模型 ${fc.model_used})</span></div>`
    : '<div class="hist-ex-row">预测 <span class="hist-ex-muted">序列太短未训出</span></div>';
  const oldestLine = h.oldest_held_days != null
    ? `<div class="hist-ex-row">当前压最久 <b>${h.oldest_held_days} 天</b> <span class="hist-ex-muted">(库存最早进的那批)</span></div>`
    : '';
  const avgHoldLine = h.avg_days != null
    ? `<div class="hist-ex-row">平均持仓 <b>${h.avg_days} 天</b> <span class="hist-ex-muted">(${h.n_pairs} 件配对)</span></div>`
    : '';
  const miscCard = `
    <section class="hist-ex-card">
      <h4>🔮 持仓 / 预测 / 数据范围</h4>
      ${avgHoldLine}
      ${oldestLine}
      ${fcLine}
      <div class="hist-ex-row hist-ex-muted">首笔 ${ex.first_event_at ?? '—'} · 末笔 ${ex.last_event_at ?? '—'} ${truncWarn}</div>
    </section>`;

  root.innerHTML = returnCard + topCustomersCard + heatmapCard + miscCard;
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
    const g = Number(c.manual_grade);
    const tone = g >= 8 ? "accent" : g >= 4 ? "warn" : g >= 2 ? "info" : "error";
    cells.push(_kv("等级", `<span class="hist-grade-badge" data-tone="${tone}">${escapeHtml(String(c.manual_grade))}</span>`));
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
