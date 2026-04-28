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
}

function renderResult(data) {
  $("historyHint").style.display = "none";
  $("historyCurrentPanel").hidden = false;
  $("historyTimelinePanel").hidden = false;

  const c = data.current;
  const stores = (c.store_locations || []).map(escapeHtml).join(", ") || '<span class="empty-val">—</span>';
  const warehouses = (c.warehouse_locations || []).map(escapeHtml).join(", ") || '<span class="empty-val">—</span>';
  $("historyCurrent").innerHTML = `
    <div class="kv-grid">
      <div><span class="k">型号</span><span class="v">${escapeHtml(c.model)}</span></div>
      <div><span class="k">条码</span><span class="v">${escapeHtml(c.barcode)}</span></div>
      <div><span class="k">店面位置</span><span class="v">${stores}</span></div>
      <div><span class="k">仓库位置</span><span class="v">${warehouses}</span></div>
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
      renderEmpty(`未找到 "${q}"，请检查型号或条码是否正确`);
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
}

init();
