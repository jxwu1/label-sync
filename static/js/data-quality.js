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

function setStat(statId, count, baseTone) {
  const el = $(statId);
  if (!el) return;
  el.querySelector(".dq-stat-num").textContent = count.toLocaleString();
  el.dataset.tone = count === 0 ? "accent" : baseTone;
}

function renderMultiKind(section) {
  if (section.samples.length === 0) {
    $("dqMultiKind").innerHTML = '<div class="dq-empty">✓ 无异常</div>';
    return;
  }
  const rows = section.samples.map((s, i) => {
    const isWarehouse = (s.duplicated_kind || "").toLowerCase().includes("warehouse");
    const pillCls = isWarehouse ? "dq-pill dq-pill--warn" : "dq-pill dq-pill--info";
    return `
      <tr>
        <td class="dq-td-idx">${String(i + 1).padStart(2, "0")}</td>
        <td class="dq-td-bc">${escapeHtml(s.barcode)}</td>
        <td>${escapeHtml(s.model || "")}</td>
        <td>${escapeHtml(s.raw_location || "")}</td>
        <td><span class="${pillCls}">${escapeHtml(s.duplicated_kind)} × ${s.count}</span></td>
      </tr>`;
  }).join("");
  $("dqMultiKind").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>#</th><th>条码</th><th>型号</th><th>当前 LOCATION</th><th>重复维度</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderFlippers(section) {
  if (section.samples.length === 0) {
    $("dqFlippers").innerHTML = '<div class="dq-empty">✓ 无异常</div>';
    return;
  }
  const rows = section.samples.map((s, i) => `
    <tr>
      <td class="dq-td-idx">${String(i + 1).padStart(2, "0")}</td>
      <td class="dq-td-bc">${escapeHtml(s.barcode)}</td>
      <td>${escapeHtml(s.model || "")}</td>
      <td class="dq-td-num">${s.change_count}</td>
      <td>${escapeHtml(s.current_location || "")}</td>
    </tr>
  `).join("");
  $("dqFlippers").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>#</th><th>条码</th><th>型号</th><th>变更次数</th><th>当前 LOCATION</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function refresh() {
  const btn = $("dqRefresh");
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = "↻ 加载中…";
  try {
    const res = await fetch("/data_quality");
    const data = await res.json();
    if (!data.ok) {
      btn.textContent = "↻ 加载失败";
      return;
    }
    _lastReport = data;

    const multiCount = data.multi_same_kind.count;
    const flippersCount = data.flippers.count;
    setStat("dqStatMulti", multiCount, "warn");
    setStat("dqStatFlippers", flippersCount, "warn");

    renderMultiKind(data.multi_same_kind);
    renderFlippers(data.flippers);
    $("dqMultiKindPanel").hidden = false;
    $("dqFlippersPanel").hidden = false;
    btn.textContent = "↻ 刷新";
  } catch (e) {
    btn.textContent = "↻ 加载异常";
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

// 首次切到数据质量页时自动 refresh 一次（省去用户点刷新一步）
window.Alpine?.store?.("nav")?.onFirstActivate?.("data_quality", refresh);
