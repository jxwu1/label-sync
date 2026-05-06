// 数据质量（PR-FE-2 起）：维度健康监测
// 只展示 multi_same_kind / flippers。清洁工作流（whitespace/prefix/duplicate/empty）
// 在「标签查重」页（dedupe.js）。
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

function renderMultiKind(section) {
  if (section.samples.length === 0) {
    $("dqMultiKind").innerHTML = '<div class="dq-empty">无</div>';
    return;
  }
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td>${escapeHtml(s.raw_location || "")}</td>
      <td>${escapeHtml(s.duplicated_kind)} × ${s.count}</td>
    </tr>
  `).join("");
  $("dqMultiKind").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>当前 location</th><th>重复维度</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderFlippers(section) {
  if (section.samples.length === 0) {
    $("dqFlippers").innerHTML = '<div class="dq-empty">无</div>';
    return;
  }
  const rows = section.samples.map((s) => `
    <tr>
      <td>${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td class="dq-num">${s.change_count}</td>
      <td>${escapeHtml(s.current_location || "")}</td>
    </tr>
  `).join("");
  $("dqFlippers").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>变更次数</th><th>当前 location</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function refresh() {
  const btn = $("dqRefresh");
  if (!btn) return;
  btn.disabled = true;
  $("dqHint").textContent = "加载中…";
  try {
    const res = await fetch("/data_quality");
    const data = await res.json();
    if (!data.ok) {
      $("dqHint").textContent = "加载失败：" + (data.msg || "未知错误");
      return;
    }
    $("dqHint").textContent = "维度健康监测：multi 维度 + 高频翻转。清洁工作流（4 类脏数据）请到「标签查重」页。";
    _lastReport = data;

    showCount("dqMultiKindCount", data.multi_same_kind.count);
    renderMultiKind(data.multi_same_kind);
    $("dqMultiKindPanel").hidden = false;

    showCount("dqFlippersCount", data.flippers.count);
    renderFlippers(data.flippers);
    $("dqFlippersPanel").hidden = false;
  } catch (e) {
    $("dqHint").textContent = "加载异常：" + e.message;
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

// 限定到 pageDataQuality 内的复制按钮（避免和 dedupe 页同名 button 冲突）
const dqRoot = $("pageDataQuality");
if (dqRoot) {
  dqRoot.querySelectorAll("[data-copy-section]").forEach((btn) => {
    btn.addEventListener("click", () => copyModels(btn.dataset.copySection, btn));
  });
}

$("dqRefresh")?.addEventListener("click", refresh);
