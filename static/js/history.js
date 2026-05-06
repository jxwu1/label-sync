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
}

function renderFuzzyMatches(matches, originalQuery) {
  $("historyHint").textContent = `"${originalQuery}" 没有精确匹配，找到 ${matches.length} 条候选`;
  $("historyHint").style.display = "";
  $("historyCurrentPanel").hidden = true;
  $("historyTimelinePanel").hidden = true;
  $("historyFuzzyPanel").hidden = false;

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
