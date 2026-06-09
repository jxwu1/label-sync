// 数据质量 v2（design-pack 05）：7 类只读诊断合并到一页
// 数据全部来自单个 /data_quality 端点（build_report 返回 7 类 count+samples）。
import { copyToClip, escapeHtml, byId as $ } from "./shared.js";

let _lastReport = null;

// tab key → report key / chip 标签 / 异常色调
const CATS = [
  { key: "whitespace", report: "whitespace_anomalies", chip: "空白", tone: "error" },
  { key: "prefix",     report: "unknown_prefix",       chip: "前缀", tone: "error" },
  { key: "duplicate",  report: "duplicate_segments",   chip: "重复", tone: "error" },
  { key: "orphan",     report: "empty_locations",      chip: "空位", tone: "warn" },
  { key: "negstock",   report: "negative_stock",       chip: "负库", tone: "error" },
  { key: "multi",      report: "multi_same_kind",      chip: "多位", tone: "warn" },
  { key: "flippers",   report: "flippers",             chip: "翻转", tone: "warn" },
];

// raw location 里的空格高亮成红点
function highlightWs(raw) {
  return escapeHtml(raw).replace(/ /g, '<span class="ws">·</span>');
}

const EMPTY = '<div class="dq-empty2">✓ 无异常</div>';

function tbl(head, bodyRows) {
  return `<table class="tbl"><thead><tr>${head}</tr></thead><tbody>${bodyRows}</tbody></table>`;
}
function idxCell(i) { return `<td class="idx">${i + 1}</td>`; }

const RENDERERS = {
  whitespace(samples) {
    const rows = samples.map((s, i) => `<tr>${idxCell(i)}
      <td class="bc">${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td><code>${highlightWs(s.raw_location || "")}</code></td>
      <td><code>${escapeHtml(s.normalized || "")}</code></td></tr>`).join("");
    return tbl('<th style="width:28px">#</th><th>条码</th><th>型号</th><th>原 RAW（<span class="ws">·</span> = 空格）</th><th>STRIP 后</th>', rows);
  },
  prefix(samples) {
    const rows = samples.map((s, i) => `<tr>${idxCell(i)}
      <td class="bc">${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td>${escapeHtml(s.raw_location || "")}</td>
      <td><code>${escapeHtml(s.anomalous_segment || "")}</code></td></tr>`).join("");
    return tbl('<th style="width:28px">#</th><th>条码</th><th>型号</th><th>当前 LOCATION</th><th>异常段</th>', rows);
  },
  duplicate(samples) {
    const rows = samples.map((s, i) => {
      const tags = (s.duplicates || []).map((d) => `<span class="dup-tag">${escapeHtml(d)}</span>`).join("");
      return `<tr>${idxCell(i)}
        <td class="bc">${escapeHtml(s.barcode)}</td>
        <td>${escapeHtml(s.model || "")}</td>
        <td><code>${escapeHtml(s.raw_location || "")}</code></td>
        <td>${tags}</td></tr>`;
    }).join("");
    return tbl('<th style="width:28px">#</th><th>条码</th><th>型号</th><th>原 RAW</th><th>重复段</th>', rows);
  },
  orphan(samples) {
    const rows = samples.map((s, i) => `<tr>${idxCell(i)}
      <td class="bc">${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td class="td-name">${escapeHtml(s.product_name || "")}</td>
      <td class="dt">${escapeHtml(s.updated_at || "")}</td></tr>`).join("");
    return tbl('<th style="width:28px">#</th><th>条码</th><th>型号</th><th>品名</th><th>最近更新</th>', rows);
  },
  negstock(samples) {
    const rows = samples.map((s, i) => `<tr>${idxCell(i)}
      <td class="bc">${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td class="td-name">${escapeHtml(s.product_name || "")}</td>
      <td class="r neg">${s.qty}</td></tr>`).join("");
    return tbl('<th style="width:28px">#</th><th>条码</th><th>型号</th><th>品名</th><th class="r">库存</th>', rows);
  },
  multi(samples) {
    const rows = samples.map((s, i) => {
      const isWarehouse = (s.duplicated_kind || "").toLowerCase().includes("warehouse");
      const pillCls = isWarehouse ? "pill-sm pill-sm--warn" : "pill-sm pill-sm--info";
      return `<tr>${idxCell(i)}
        <td class="bc">${escapeHtml(s.barcode)}</td>
        <td>${escapeHtml(s.model || "")}</td>
        <td>${escapeHtml(s.raw_location || "")}</td>
        <td><span class="${pillCls}">${escapeHtml(s.duplicated_kind)} × ${s.count}</span></td></tr>`;
    }).join("");
    return tbl('<th style="width:28px">#</th><th>条码</th><th>型号</th><th>当前 LOCATION</th><th>重复维度</th>', rows);
  },
  flippers(samples) {
    const rows = samples.map((s, i) => `<tr>${idxCell(i)}
      <td class="bc">${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td class="r num-hi">${s.change_count}</td>
      <td>${escapeHtml(s.current_location || "")}</td></tr>`).join("");
    return tbl('<th style="width:28px">#</th><th>条码</th><th>型号</th><th class="r">变更次数</th><th>当前 LOCATION</th>', rows);
  },
};

function renderChips(report) {
  const html = CATS.map((c) => {
    const n = report[c.report]?.count || 0;
    const tone = n === 0 ? "clean" : c.tone;
    return `<div class="s-chip" data-tone="${tone}"><span class="s-chip-label">${c.chip}</span><span class="s-chip-num">${n.toLocaleString()}</span></div>`;
  }).join("");
  $("dqChips").innerHTML = html;
}

function renderAll(report) {
  let total = 0;
  CATS.forEach((c) => {
    const section = report[c.report] || { count: 0, samples: [] };
    const n = section.count || 0;
    total += n;
    // tab count + tone
    const countEl = document.querySelector(`#dqTabStrip .tab-count[data-c="${c.key}"]`);
    if (countEl) {
      countEl.textContent = n.toLocaleString();
      countEl.dataset.tone = n === 0 ? "clean" : c.tone;
    }
    // 表格
    const listEl = $(`dqList_${c.key}`);
    if (listEl) {
      listEl.innerHTML = (section.samples && section.samples.length)
        ? RENDERERS[c.key](section.samples)
        : EMPTY;
    }
  });
  renderChips(report);
  const totalEl = $("dqTotalAnomalies");
  if (totalEl) totalEl.textContent = total.toLocaleString();
  const scannedEl = $("dqScannedCount");
  if (scannedEl && typeof report.scanned_count === "number") {
    scannedEl.textContent = report.scanned_count.toLocaleString();
  }
  const scanEl = $("dqLastScan");
  if (scanEl) {
    const n = new Date();
    scanEl.textContent = `${String(n.getHours()).padStart(2, "0")}:${String(n.getMinutes()).padStart(2, "0")}:${String(n.getSeconds()).padStart(2, "0")}`;
  }
}

async function refresh() {
  const btn = $("dqRefresh");
  if (btn) { btn.disabled = true; btn.textContent = "↻ 扫描中…"; }
  try {
    const res = await fetch("/data_quality");
    const data = await res.json();
    if (!data.ok) {
      if (btn) btn.textContent = "↻ 加载失败";
      return;
    }
    _lastReport = data;
    renderAll(data);
    if (btn) btn.textContent = "↻ 重新扫描";
  } catch (e) {
    if (btn) btn.textContent = "↻ 加载异常";
  } finally {
    if (btn) btn.disabled = false;
  }
}

// tab 切换
function setupTabs() {
  const strip = $("dqTabStrip");
  if (!strip) return;
  strip.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    const tab = btn.dataset.dqTab;
    strip.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll("#pageDataQuality [data-dq-panel]").forEach((p) => {
      p.classList.toggle("active", p.dataset.dqPanel === tab);
    });
  });
}

async function copyModels(sectionKey, btn) {
  if (!_lastReport) { flashBtn(btn, "先点扫描"); return; }
  const section = _lastReport[sectionKey];
  const samples = (section && section.samples) || [];
  const models = [...new Set(samples.map((s) => s.model).filter(Boolean))];
  if (models.length === 0) { flashBtn(btn, "无型号"); return; }
  const truncated = section.count > samples.length;
  try {
    await copyToClip(models.join("\n"));
    const suffix = truncated ? `（共 ${section.count}）` : "";
    flashBtn(btn, `已复制 ${models.length}${suffix}`, "copied");
  } catch (e) {
    flashBtn(btn, "复制失败");
  }
}

// 复制全部：跨 7 类去重汇总所有异常型号
async function copyAllModels(btn) {
  if (!_lastReport) { flashBtn(btn, "先点扫描"); return; }
  const models = new Set();
  let truncated = false;
  CATS.forEach((c) => {
    const section = _lastReport[c.report];
    const samples = (section && section.samples) || [];
    samples.forEach((s) => { if (s.model) models.add(s.model); });
    if (section && section.count > samples.length) truncated = true;
  });
  const list = [...models];
  if (list.length === 0) { flashBtn(btn, "无型号"); return; }
  try {
    await copyToClip(list.join("\n"));
    flashBtn(btn, `已复制 ${list.length}${truncated ? "（部分截断）" : ""}`, "copied");
  } catch (e) {
    flashBtn(btn, "复制失败");
  }
}

function flashBtn(btn, text, extraClass) {
  const original = btn.dataset.originalText || btn.textContent;
  btn.dataset.originalText = original;
  btn.textContent = text;
  if (extraClass) btn.classList.add(extraClass);
  setTimeout(() => {
    btn.textContent = original;
    if (extraClass) btn.classList.remove(extraClass);
  }, 2000);
}

const dqRoot = $("pageDataQuality");
if (dqRoot) {
  dqRoot.querySelectorAll("[data-copy-section]").forEach((btn) => {
    btn.addEventListener("click", () => copyModels(btn.dataset.copySection, btn));
  });
}
setupTabs();
$("dqRefresh")?.addEventListener("click", refresh);
$("dqCopyAll")?.addEventListener("click", (e) => copyAllModels(e.currentTarget));

// 首次切到数据质量页时自动 refresh 一次
window.Alpine?.store?.("nav")?.onFirstActivate?.("data_quality", refresh);
