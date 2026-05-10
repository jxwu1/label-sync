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
    refreshImports();
  } catch (err) {
    setHint(`网络错误：${err.message}`, true);
  }
}

const _EVENT_TYPE_CN = { purchase: "采购", sale: "销售" };

async function refreshImports() {
  try {
    const resp = await fetch("/inventory/imports");
    const data = await resp.json();
    if (!data.ok) return;
    if (!data.imports.length) {
      $("invImports").innerHTML = '<div class="inv-imports-empty">暂无 import 记录</div>';
      return;
    }
    const rows = data.imports
      .map((r) => {
        const typeCls = r.event_type === "sale" ? "inv-imp-type--sale" : "inv-imp-type--purchase";
        const typeLabel = _EVENT_TYPE_CN[r.event_type] || r.event_type;
        const errCls = r.error_count > 0 ? " inv-imp-err" : "";
        const dupCls = r.dup_count > 0 ? " inv-imp-dup" : "";
        return `<tr>
          <td class="inv-imp-time">${escapeHtml(r.imported_at)}</td>
          <td><span class="inv-imp-type ${typeCls}">${typeLabel}</span></td>
          <td class="inv-imp-file">${escapeHtml(r.filename)}</td>
          <td class="inv-imp-num">${r.total_rows}</td>
          <td class="inv-imp-num inv-imp-ok">${r.ok_count}</td>
          <td class="inv-imp-num${dupCls}">${r.dup_count}</td>
          <td class="inv-imp-num${errCls}">${r.error_count}</td>
          <td>${escapeHtml(r.operator)}</td>
        </tr>`;
      })
      .join("");
    $("invImports").innerHTML = `
      <table class="inv-imports-table">
        <thead><tr>
          <th>时间</th><th>类型</th><th>文件</th>
          <th class="inv-imp-num">行数</th><th class="inv-imp-num">OK</th>
          <th class="inv-imp-num">重复</th><th class="inv-imp-num">错误</th>
          <th>操作员</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (err) {
    void err;
  }
}

async function refreshStats() {
  try {
    const resp = await fetch("/inventory/stats");
    const data = await resp.json();
    if (!data.ok) return;
    const byType = data.customers_by_type || {};
    const total = (byType.chinese || 0) + (byType.foreign || 0) +
                  (byType.mixed || 0) + (byType.unknown || 0);
    const seg = (n, color) => total > 0
      ? `<span class="inv-bar__seg" style="width:${(n / total) * 100}%;background:${color}"></span>`
      : "";
    $("invStats").innerHTML = `
      <div class="inv-stat-grid">
        <div class="inv-stat-box inv-stat-box--accent">
          <div class="inv-stat-k">事件总数</div>
          <div class="inv-stat-v">${data.events_total.toLocaleString()}</div>
          <div class="inv-stat-sub">采购 ${data.events_purchase.toLocaleString()} / 销售 ${data.events_sale.toLocaleString()}</div>
        </div>
        <div class="inv-stat-box inv-stat-box--info">
          <div class="inv-stat-k">客户</div>
          <div class="inv-stat-v">${data.customers_total.toLocaleString()}</div>
        </div>
        <div class="inv-stat-box">
          <div class="inv-stat-k">供应商</div>
          <div class="inv-stat-v">${data.suppliers_total.toLocaleString()}</div>
        </div>
        <div class="inv-stat-box inv-stat-box--accent">
          <div class="inv-stat-k">SKU</div>
          <div class="inv-stat-v">${data.skus_total.toLocaleString()}</div>
        </div>
      </div>
      <div class="inv-cust-types">
        <div class="inv-cust-types__legend">
          <span class="inv-cust-pill inv-cust-pill--cn">chinese · ${byType.chinese || 0}</span>
          <span class="inv-cust-pill inv-cust-pill--fo">foreign · ${byType.foreign || 0}</span>
          <span class="inv-cust-pill inv-cust-pill--mx">mixed · ${byType.mixed || 0}</span>
          <span class="inv-cust-pill inv-cust-pill--un">unknown · ${byType.unknown || 0}</span>
        </div>
        <div class="inv-bar">
          ${seg(byType.chinese || 0, "var(--accent)")}
          ${seg(byType.foreign || 0, "var(--info)")}
          ${seg(byType.mixed || 0, "var(--warn)")}
          ${seg(byType.unknown || 0, "var(--ink-3)")}
        </div>
      </div>
    `;
  } catch (err) {
    void err;
  }
}

async function doImportProductMaster() {
  const fileInput = $("invProductFile");
  const f = fileInput && fileInput.files[0];
  if (!f) {
    setProductHint("请先选择 product.csv 文件", true);
    return;
  }
  setProductHint("正在导入产品总档（4 万行约 30-60 秒）...");
  const fd = new FormData();
  fd.append("file", f);
  try {
    const resp = await fetch("/inventory/import/product-master", {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();
    if (!data.ok) {
      setProductHint(`导入失败：${data.msg || "未知错误"}`, true);
      return;
    }
    const reasonsHtml = (data.skipped_reasons || [])
      .map((r) => `<li>${escapeHtml(r)}</li>`)
      .join("");
    setProductHint(
      `产品总档导入完成：新建 SKU ${data.rows_imported} / 更新 ${data.rows_updated} / 跳过缺条码 ${data.rows_skipped_missing_barcode} / 跳过同 csv 重复 ${data.rows_skipped_duplicate_barcode} / 新供应商 ${data.new_suppliers}` +
      (reasonsHtml ? ` <details><summary>跳过原因</summary><ul>${reasonsHtml}</ul></details>` : "")
    );
    refreshStats();
  } catch (err) {
    setProductHint(`网络错误：${err.message}`, true);
  }
}

function setProductHint(msg, isError = false) {
  // PR 12 · #invProductHint 已删，改走 alert（error / 长成功消息）+ 按钮文字（短状态）
  // 「正在导入」开头的视为进行中状态 → 改 button 文字
  const btn = $("invProductImport");
  if (msg.startsWith("正在导入")) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = msg;
    }
    return;
  }
  // 其它（成功 / 失败）→ alert + 恢复 button
  if (btn) {
    btn.disabled = false;
    btn.textContent = "↪ 导入产品总档";
  }
  // 用 textContent 转纯文本（去 HTML 标签 / details 块），alert 不渲染 HTML
  const tmp = document.createElement("div");
  tmp.innerHTML = msg;
  alert(tmp.textContent || tmp.innerText || msg);
}

function init() {
  if (!$("invFile")) return; // 不在该页
  $("invPreview").addEventListener("click", doPreview);
  $("invSaveMapping").addEventListener("click", saveMapping);
  $("invImport").addEventListener("click", doImport);
  $("invStatsRefresh").addEventListener("click", refreshStats);
  $("invImportsRefresh").addEventListener("click", refreshImports);
  // PR 12 · file input → 显示文件名
  $("invFile").addEventListener("change", (e) => {
    const f = e.target.files[0];
    $("invFileName").textContent = f ? f.name : "未选择任何文件";
  });
  if ($("invProductImport")) {
    $("invProductImport").addEventListener("click", doImportProductMaster);
  }
  if ($("invProductFile")) {
    $("invProductFile").addEventListener("change", (e) => {
      const f = e.target.files[0];
      $("invProductFileName").textContent = f ? f.name : "未选择任何文件";
    });
  }
}

// 首次切到进销存导入页时自动 load 一次（DB-STATE + RECENT 两段）
window.Alpine?.store?.("nav")?.onFirstActivate?.("inventory", () => {
  refreshStats();
  refreshImports();
});

init();
