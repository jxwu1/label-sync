// 标签查重（PR-FE-2 起；视觉重设计 2026-05-09 · DataOps Terminal handoff §3.5）
// 扫 stockpile 主档 4 类脏数据。后端复用 /data_quality endpoint，只渲染 4 类。
// 维度健康（multi/flippers）留在「数据质量」页。
import { copyToClip } from "./shared.js";

function $(id) { return document.getElementById(id); }

let _lastReport = null;

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function visibleSpace(s) {
  return String(s)
    .replace(/ /g, '<span class="dd-ws">·</span>')
    .replace(/\t/g, '<span class="dd-ws">→</span>');
}

// 4 group 配置 —— pill tone 顺设计：count==0 用 clean / orphan 用 warn / 其它 error
const GROUPS = [
  { key: "whitespace_anomalies", statId: "ddStatWhitespace", panelId: "ddWhitespacePanel",
    stateId: "ddWhitespaceState", bodyId: "ddWhitespace", tone: "error" },
  { key: "unknown_prefix",       statId: "ddStatUnknown",   panelId: "ddUnknownPanel",
    stateId: "ddUnknownState",   bodyId: "ddUnknown",       tone: "error" },
  { key: "duplicate_segments",   statId: "ddStatDuplicate", panelId: "ddDuplicatePanel",
    stateId: "ddDuplicateState", bodyId: "ddDuplicate",     tone: "error" },
  { key: "empty_locations",      statId: "ddStatEmptyLoc",  panelId: "ddEmptyLocPanel",
    stateId: "ddEmptyLocState",  bodyId: "ddEmptyLoc",      tone: "warn" },
  { key: "negative_stock",       statId: "ddStatNegStock",  panelId: "ddNegStockPanel",
    stateId: "ddNegStockState",  bodyId: "ddNegStock",      tone: "error" },
];

function setStat(statId, count, baseTone) {
  const el = $(statId);
  if (!el) return;
  el.querySelector(".dd-stat-num").textContent = count.toLocaleString();
  el.dataset.tone = count === 0 ? "accent" : baseTone;
}

function setPill(stateId, count, baseTone) {
  const el = $(stateId);
  if (!el) return;
  if (count === 0) {
    el.textContent = "CLEAN";
    el.dataset.tone = "clean";
  } else {
    el.textContent = count.toLocaleString();
    el.dataset.tone = baseTone;
  }
}

function setGroupEmpty(panelId, empty, bodyId) {
  const panel = $(panelId);
  if (!panel) return;
  panel.dataset.empty = empty ? "true" : "false";
  if (empty) $(bodyId).innerHTML = '<div class="dd-empty">✓ 无异常</div>';
}

function renderTable(bodyId, headers, rows) {
  if (rows.length === 0) {
    return; // empty 已经被 setGroupEmpty 处理
  }
  const thead = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("");
  const tbody = rows.join("");
  $(bodyId).innerHTML = `
    <table class="dd-table">
      <thead><tr>${thead}</tr></thead>
      <tbody>${tbody}</tbody>
    </table>
  `;
}

function renderWhitespace(section) {
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td><code>${visibleSpace(escapeHtml(s.raw_location))}</code></td>
      <td><code>${escapeHtml(s.normalized)}</code></td>
    </tr>
  `);
  renderTable("ddWhitespace", ["条码", "型号", "原 raw（· 表示空格）", "strip 后"], rows);
}

function renderUnknown(section) {
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td>${escapeHtml(s.raw_location || "")}</td>
      <td><code>${escapeHtml(s.anomalous_segment)}</code></td>
    </tr>
  `);
  renderTable("ddUnknown", ["条码", "型号", "当前 location", "异常段"], rows);
}

function renderDuplicate(section) {
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td><code>${escapeHtml(s.raw_location)}</code></td>
      <td>${s.duplicates.map((d) => `<code>${escapeHtml(d)}</code>`).join(" ")}</td>
    </tr>
  `);
  renderTable("ddDuplicate", ["条码", "型号", "原 raw", "重复段"], rows);
}

function renderEmptyLocations(section) {
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td>${escapeHtml(s.product_name || "")}</td>
      <td>${escapeHtml(s.updated_at || "")}</td>
    </tr>
  `);
  renderTable("ddEmptyLoc", ["条码", "型号", "品名", "最近更新"], rows);
}

function renderNegativeStock(section) {
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode || "(未关联)")}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td>${escapeHtml(s.product_name || "")}</td>
      <td class="dd-num dd-num--neg">${s.qty}</td>
    </tr>
  `);
  renderTable("ddNegStock", ["条码", "型号", "品名", "库存（负）"], rows);
}

const RENDERERS = {
  whitespace_anomalies: renderWhitespace,
  unknown_prefix: renderUnknown,
  duplicate_segments: renderDuplicate,
  empty_locations: renderEmptyLocations,
  negative_stock: renderNegativeStock,
};

async function refresh() {
  const btn = $("ddRefresh");
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = "↻ 加载中…";
  try {
    // 同时拉 /data_quality 与 /stockpile/status，工具条要显示扫描总数
    const [dqRes, spRes] = await Promise.allSettled([
      fetch("/data_quality").then((r) => r.json()),
      fetch("/stockpile/status").then((r) => r.json()),
    ]);
    if (dqRes.status !== "fulfilled" || !dqRes.value.ok) {
      const msg = dqRes.status === "fulfilled" ? (dqRes.value.msg || "未知错误") : dqRes.reason;
      $("ddTotalAnomaly").textContent = "—";
      $("ddTotalScanned").textContent = "—";
      btn.textContent = "↻ 加载失败：" + msg;
      return;
    }
    const data = dqRes.value;
    _lastReport = data;

    let totalAnomaly = 0;
    GROUPS.forEach((g) => {
      const section = data[g.key];
      const count = section.count || 0;
      totalAnomaly += count;
      setStat(g.statId, count, g.tone);
      setPill(g.stateId, count, g.tone);
      setGroupEmpty(g.panelId, count === 0, g.bodyId);
      if (count > 0) RENDERERS[g.key](section);
    });

    $("ddTotalAnomaly").textContent = totalAnomaly.toLocaleString();

    // 扫描总数：active + inactive (来自 /stockpile/status)
    if (spRes.status === "fulfilled" && spRes.value.ok) {
      const sp = spRes.value;
      const total = (sp.active_count || 0) + (sp.inactive_count || 0);
      $("ddTotalScanned").textContent = total ? total.toLocaleString() : "—";
    }

    btn.textContent = "↻ 重新扫描";
  } catch (e) {
    btn.textContent = "↻ 加载异常：" + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function copyModels(sectionKey, btn) {
  if (!_lastReport) {
    flashBtn(btn, "先点扫描");
    return;
  }
  const section = _lastReport[sectionKey];
  const samples = (section && section.samples) || [];
  const models = [...new Set(samples.map((s) => s.model).filter(Boolean))];
  if (models.length === 0) {
    flashBtn(btn, "无型号");
    return;
  }
  const truncated = section.count > samples.length;
  try {
    await copyToClip(models.join("\n"));
    const suffix = truncated ? `（共 ${section.count}）` : "";
    flashBtn(btn, `已复制 ${models.length}${suffix}`);
  } catch (e) {
    flashBtn(btn, "复制失败");
  }
}

async function copyAllAnomalies(btn) {
  if (!_lastReport) {
    flashBtn(btn, "先点扫描");
    return;
  }
  const allModels = new Set();
  GROUPS.forEach((g) => {
    const section = _lastReport[g.key];
    (section && section.samples || []).forEach((s) => {
      if (s.model) allModels.add(s.model);
    });
  });
  if (allModels.size === 0) {
    flashBtn(btn, "无异常");
    return;
  }
  try {
    await copyToClip([...allModels].join("\n"));
    flashBtn(btn, `已复制 ${allModels.size}`);
  } catch (e) {
    flashBtn(btn, "复制失败");
  }
}

function flashBtn(btn, text) {
  const original = btn.dataset.originalText || btn.textContent;
  btn.dataset.originalText = original;
  btn.textContent = text;
  setTimeout(() => {
    btn.textContent = original;
  }, 2000);
}

// 限定到 pageDup 内的 dedupe 复制按钮（避免和 quality 页同名 button 冲突）
const dupRoot = $("pageDup");
if (dupRoot) {
  dupRoot.querySelectorAll("[data-copy-section]").forEach((btn) => {
    btn.addEventListener("click", () => copyModels(btn.dataset.copySection, btn));
  });
}

$("ddRefresh")?.addEventListener("click", refresh);
$("ddCopyAll")?.addEventListener("click", (e) => copyAllAnomalies(e.currentTarget));

// 首次切到查重页时自动 refresh 一次（与 sa/dq 同款 lazy load）
window.Alpine?.store?.("nav")?.onFirstActivate?.("dup", refresh);
