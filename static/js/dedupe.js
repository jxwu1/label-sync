// 标签查重（PR-FE-2 起）：扫 stockpile 主档 4 类脏数据
// 后端复用 /data_quality endpoint，只渲染 4 类（whitespace/unknown/duplicate/empty）。
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

function showCount(elId, n) {
  $(elId).textContent = n > 0 ? `· ${n}` : "· 0";
  $(elId).classList.toggle("dq-count--zero", n === 0);
}

function visibleSpace(s) {
  return String(s)
    .replace(/ /g, '<span class="dq-ws">·</span>')
    .replace(/\t/g, '<span class="dq-ws">→</span>');
}

function renderWhitespace(section) {
  if (section.samples.length === 0) {
    $("ddWhitespace").innerHTML = '<div class="dq-empty">无</div>';
    return;
  }
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td><code>${visibleSpace(escapeHtml(s.raw_location))}</code></td>
      <td><code>${escapeHtml(s.normalized)}</code></td>
    </tr>
  `).join("");
  $("ddWhitespace").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>原 raw（· 表示空格）</th><th>strip 后</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderUnknown(section) {
  if (section.samples.length === 0) {
    $("ddUnknown").innerHTML = '<div class="dq-empty">无</div>';
    return;
  }
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td>${escapeHtml(s.raw_location || "")}</td>
      <td><code>${escapeHtml(s.anomalous_segment)}</code></td>
    </tr>
  `).join("");
  $("ddUnknown").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>当前 location</th><th>异常段</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderDuplicate(section) {
  if (section.samples.length === 0) {
    $("ddDuplicate").innerHTML = '<div class="dq-empty">无</div>';
    return;
  }
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td><code>${escapeHtml(s.raw_location)}</code></td>
      <td>${s.duplicates.map((d) => `<code>${escapeHtml(d)}</code>`).join(" ")}</td>
    </tr>
  `).join("");
  $("ddDuplicate").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>原 raw</th><th>重复段</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderEmptyLocations(section) {
  if (section.samples.length === 0) {
    $("ddEmptyLoc").innerHTML = '<div class="dq-empty">无</div>';
    return;
  }
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td>${escapeHtml(s.product_name || "")}</td>
      <td>${escapeHtml(s.updated_at || "")}</td>
    </tr>
  `).join("");
  $("ddEmptyLoc").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>品名</th><th>最近更新</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function refresh() {
  const btn = $("ddRefresh");
  if (!btn) return;
  btn.disabled = true;
  $("ddHint").textContent = "加载中…";
  try {
    const res = await fetch("/data_quality");
    const data = await res.json();
    if (!data.ok) {
      $("ddHint").textContent = "加载失败：" + (data.msg || "未知错误");
      return;
    }
    $("ddHint").textContent = "本页只展示，不修改数据。在老系统修复后，下次 import 自动同步。";
    _lastReport = data;

    showCount("ddWhitespaceCount", data.whitespace_anomalies.count);
    renderWhitespace(data.whitespace_anomalies);
    $("ddWhitespacePanel").hidden = false;

    showCount("ddUnknownCount", data.unknown_prefix.count);
    renderUnknown(data.unknown_prefix);
    $("ddUnknownPanel").hidden = false;

    showCount("ddDuplicateCount", data.duplicate_segments.count);
    renderDuplicate(data.duplicate_segments);
    $("ddDuplicatePanel").hidden = false;

    showCount("ddEmptyLocCount", data.empty_locations.count);
    renderEmptyLocations(data.empty_locations);
    $("ddEmptyLocPanel").hidden = false;
  } catch (e) {
    $("ddHint").textContent = "加载异常：" + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function copyModels(sectionKey, btn) {
  if (!_lastReport) {
    flashBtn(btn, "先点刷新");
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
    flashBtn(btn, `已复制 ${models.length}${suffix}`, "copied");
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

// 限定到 pageDup 内的 dedupe 复制按钮（避免和 quality 页同名 button 冲突）
const dupRoot = $("pageDup");
if (dupRoot) {
  dupRoot.querySelectorAll("[data-copy-section]").forEach((btn) => {
    btn.addEventListener("click", () => copyModels(btn.dataset.copySection, btn));
  });
}

$("ddRefresh")?.addEventListener("click", refresh);
