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
  // 把空格 / 制表符替换成可见标记，方便看
  return String(s)
    .replace(/ /g, '<span class="dq-ws">·</span>')
    .replace(/\t/g, '<span class="dq-ws">→</span>');
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

function renderWhitespace(section) {
  if (section.samples.length === 0) {
    $("dqWhitespace").innerHTML = '<div class="dq-empty">无</div>';
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
  $("dqWhitespace").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>原 raw（· 表示空格）</th><th>strip 后</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderDuplicate(section) {
  if (section.samples.length === 0) {
    $("dqDuplicate").innerHTML = '<div class="dq-empty">无</div>';
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
  $("dqDuplicate").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>原 raw</th><th>重复段</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderUnknown(section) {
  if (section.samples.length === 0) {
    $("dqUnknown").innerHTML = '<div class="dq-empty">无</div>';
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
  $("dqUnknown").innerHTML = `
    <table class="dq-table">
      <thead><tr><th>条码</th><th>型号</th><th>当前 location</th><th>异常段</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function refresh() {
  const btn = $("dqRefresh");
  btn.disabled = true;
  $("dqHint").textContent = "加载中…";
  try {
    const res = await fetch("/data_quality");
    const data = await res.json();
    if (!data.ok) {
      $("dqHint").textContent = "加载失败：" + (data.msg || "未知错误");
      return;
    }
    $("dqHint").textContent = "本页只展示，不修改数据。在老系统修复后，下次 import 自动同步。";
    _lastReport = data;

    showCount("dqMultiKindCount", data.multi_same_kind.count);
    renderMultiKind(data.multi_same_kind);
    $("dqMultiKindPanel").hidden = false;

    showCount("dqFlippersCount", data.flippers.count);
    renderFlippers(data.flippers);
    $("dqFlippersPanel").hidden = false;

    showCount("dqWhitespaceCount", data.whitespace_anomalies.count);
    renderWhitespace(data.whitespace_anomalies);
    $("dqWhitespacePanel").hidden = false;

    showCount("dqUnknownCount", data.unknown_prefix.count);
    renderUnknown(data.unknown_prefix);
    $("dqUnknownPanel").hidden = false;

    showCount("dqDuplicateCount", data.duplicate_segments.count);
    renderDuplicate(data.duplicate_segments);
    $("dqDuplicatePanel").hidden = false;
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
    await navigator.clipboard.writeText(models.join("\n"));
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

document.querySelectorAll(".dq-copy").forEach((btn) => {
  btn.addEventListener("click", () => copyModels(btn.dataset.copySection, btn));
});

$("dqRefresh")?.addEventListener("click", refresh);
