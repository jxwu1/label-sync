// 进销存导入 tab：列映射向导 + import 触发 + 结果展示
"use strict";

const $ = (id) => document.getElementById(id);

let cachedColumns = []; // 上次预览拿到的列名
let cachedMapping = {}; // 当前展示中的映射
let cachedSample = []; // 前 5 行
let internalFields = []; // 合法 internal 字段（含 ignore）

function getFileType() {
  const r = document.querySelector('input[name="invType"]:checked');
  return r ? r.value : "purchase";
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function setHint(msg, isError = false) {
  const el = $("invHint");
  if (!el) return;
  el.textContent = msg;
  el.style.color = isError ? "#dc3545" : "";
}

function renderMappingTable() {
  const body = $("invMappingBody");
  if (!body) return;
  const optionsHtml = internalFields
    .map((f) => `<option value="${escapeHtml(f)}">${escapeHtml(f)}</option>`)
    .join("");
  body.innerHTML = cachedColumns
    .map((col) => {
      const cur = cachedMapping[col] || "ignore";
      const sample = cachedSample.length > 0 ? cachedSample[0][col] : "";
      const optsWithSelected = internalFields
        .map(
          (f) =>
            `<option value="${escapeHtml(f)}"${f === cur ? " selected" : ""}>${escapeHtml(f)}</option>`,
        )
        .join("");
      return `
        <tr data-col="${escapeHtml(col)}">
          <td><b>${escapeHtml(col)}</b></td>
          <td><select class="inv-mapping-select" data-col="${escapeHtml(col)}">${optsWithSelected}</select></td>
          <td><span class="inv-mapping-sample">${escapeHtml(sample)}</span></td>
        </tr>
      `;
    })
    .join("");
  // 监听下拉变化
  for (const sel of body.querySelectorAll(".inv-mapping-select")) {
    sel.addEventListener("change", (e) => {
      cachedMapping[e.target.dataset.col] = e.target.value;
    });
  }
  void optionsHtml; // 保留可能将来要做"批量改"
}

async function doPreview() {
  const fileInput = $("invFile");
  const f = fileInput && fileInput.files[0];
  if (!f) {
    setHint("请先选择文件", true);
    return;
  }
  setHint("解析中...");
  const fd = new FormData();
  fd.append("file", f);
  try {
    const resp = await fetch("/inventory/preview", { method: "POST", body: fd });
    const data = await resp.json();
    if (!data.ok) {
      setHint(`预览失败：${data.msg || "未知错误"}`, true);
      return;
    }
    cachedColumns = data.columns;
    cachedSample = data.sample;
    internalFields = data.internal_fields;

    // 拉当前 profile（如果保存过）；否则用 default
    const fileType = getFileType();
    const profResp = await fetch(`/inventory/profiles/${fileType}`);
    const profData = await profResp.json();
    cachedMapping = profData.mapping || data.default_mapping || {};

    renderMappingTable();
    $("invPreviewCount").textContent = `（${data.row_count} 行）`;
    $("invPreviewPanel").hidden = false;
    setHint(`预览成功：${data.row_count} 行 / ${cachedColumns.length} 列。检查映射，可调整后保存或直接「执行导入」。`);
  } catch (err) {
    setHint(`网络错误：${err.message}`, true);
  }
}

async function saveMapping() {
  const fileType = getFileType();
  if (Object.keys(cachedMapping).length === 0) {
    setHint("请先「预览」拿到列结构", true);
    return;
  }
  try {
    const resp = await fetch(`/inventory/profiles/${fileType}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mapping: cachedMapping }),
    });
    const data = await resp.json();
    if (!data.ok) {
      setHint(`保存失败：${data.msg}`, true);
    } else {
      setHint(`已保存 ${fileType} profile，下次导入会自动应用`);
    }
  } catch (err) {
    setHint(`网络错误：${err.message}`, true);
  }
}

async function doImport() {
  const fileInput = $("invFile");
  const f = fileInput && fileInput.files[0];
  if (!f) {
    setHint("请先选择文件", true);
    return;
  }
  const fileType = getFileType();
  setHint(`正在导入到 ${fileType} ...`);
  const fd = new FormData();
  fd.append("file", f);
  try {
    const resp = await fetch(`/inventory/import/${fileType}`, {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();
    if (!data.ok) {
      setHint(`导入失败：${data.msg || "未知错误"}`, true);
      return;
    }
    setHint("导入完成");
    const reasonsHtml = (data.skipped_reasons || [])
      .map((r) => `<li>${escapeHtml(r)}</li>`)
      .join("");
    const recovered = data.barcodes_recovered || 0;
    const noDate = data.rows_skipped_no_date || 0;
    const orphan = data.rows_skipped_orphan_barcode || 0;
    $("invResult").innerHTML = `
      <div class="inv-stats">
        <div><b>导入：</b>${data.rows_imported}</div>
        <div><b>跳过（重复）：</b>${data.rows_skipped_duplicate}</div>
        <div><b>跳过（缺字段）：</b>${data.rows_skipped_missing_key}</div>
        <div><b>跳过（无日期）：</b>${noDate}</div>
        <div><b>跳过（孤儿条码）：</b>${orphan}</div>
        <div><b>条码反查救回：</b>${recovered}</div>
        <div><b>新建客户：</b>${data.new_customers}</div>
        <div><b>新建供应商：</b>${data.new_suppliers}</div>
        <div><b>新建 SKU：</b>${data.new_skus}</div>
      </div>
      ${reasonsHtml ? `<details><summary>跳过原因（前 ${data.skipped_reasons.length} 条）</summary><ul>${reasonsHtml}</ul></details>` : ""}
    `;
    $("invResultPanel").hidden = false;
    refreshStats();
  } catch (err) {
    setHint(`网络错误：${err.message}`, true);
  }
}

async function refreshStats() {
  try {
    const resp = await fetch("/inventory/stats");
    const data = await resp.json();
    if (!data.ok) return;
    const byType = data.customers_by_type || {};
    $("invStats").innerHTML = `
      <div class="inv-stats">
        <div><b>事件总数：</b>${data.events_total}（采购 ${data.events_purchase} / 销售 ${data.events_sale}）</div>
        <div><b>客户：</b>${data.customers_total}</div>
        <div><b>供应商：</b>${data.suppliers_total}</div>
        <div><b>SKU：</b>${data.skus_total}</div>
      </div>
      <div class="inv-stats-sub">
        <span>客户类型分布：</span>
        ${Object.entries(byType)
          .map(([k, v]) => `<span class="inv-badge">${escapeHtml(k)} ${v}</span>`)
          .join("")}
      </div>
    `;
  } catch (err) {
    void err;
  }
}

function init() {
  if (!$("invFile")) return; // 不在该页
  $("invPreview").addEventListener("click", doPreview);
  $("invSaveMapping").addEventListener("click", saveMapping);
  $("invImport").addEventListener("click", doImport);
  $("invStatsRefresh").addEventListener("click", refreshStats);
}

init();
