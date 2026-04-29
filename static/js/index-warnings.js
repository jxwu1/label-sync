import { esc, jesc, copyToClip, postJSON } from "./shared.js";
import { initDup, renderDupCard } from "./index-dup.js";

const $ = (selector) => document.querySelector(selector);

export function initWarnings() {}

export function waitMsg(stage) {
  if (stage === "anomaly" || stage === "phase1_barcode") return "发现异常条码，请校正、删除或忽略后继续处理";
  if (stage === "location_format" || stage === "phase1_location") return "发现库位格式异常，请手工校正后继续处理";
  if (stage === "new_barcodes" || stage === "phase2_review" || stage === "phase2") return "发现数据异常，请处理后继续";
  return "任务等待人工处理";
}

function renderBarcodes(items) {
  if (!items.length) return '<div class="empty">暂无异常条码</div>';
  return items.map((warning, index) => {
    if (warning.deleted) return `<div class="warn"><div class="row"><div class="col"><span class="code code--struck">${esc(warning.barcode)}</span></div><span class="tag-del">已删除</span></div></div>`;
    if (warning.corrected) return `<div class="warn"><div class="row"><div class="col"><span class="code code--struck">${esc(warning.barcode)}</span></div><span class="tag-ok">已校正为 ${esc(warning.new_barcode || "")}</span></div></div>`;
    return `<div class="warn" id="bc_${index}"><div class="row"><div class="col"><span class="code">${esc(warning.barcode)}</span><span class="sub">长度 ${warning.length} 位，正常长度 ${warning.normal} 位</span></div><div class="actions"><button class="btn-s is-warn" onclick="showBc(${index})">校正</button><button class="btn-s is-danger" onclick="delBc('${jesc(warning.barcode)}',${index})">删除</button><button class="btn-s is-ghost" onclick="ignoreBc(${index})">忽略</button></div></div><div class="form" id="bcf_${index}"><input id="bci_${index}" placeholder="输入正确条码"><button class="btn-s is-warn-solid" onclick="submitBc('${jesc(warning.barcode)}',${index})">确认</button><button class="btn-s is-ghost-strong" onclick="hideBc(${index})">取消</button></div></div>`;
  }).join("");
}

function renderLocs(items) {
  if (!items.length) return '<div class="empty">暂无库位异常</div>';
  return items.map((warning, index) => {
    if (warning.corrected) return `<div class="warn"><div class="row"><div class="col"><span class="code loc code--struck">${esc(warning.location)}</span></div><span class="tag-ok">已校正为 ${esc(warning.new_location || "")}</span></div></div>`;
    return `<div class="warn"><div class="row"><div class="col"><span class="code loc">${esc(warning.location)}</span><span class="sub">库位格式不符合要求，请手工校正</span></div><div class="actions"><button class="btn-s is-warn" onclick="showLoc(${index})">校正库位</button></div></div><div class="form" id="lf_${index}"><input id="li_${index}" placeholder="输入正确库位，例如 A01"><button class="btn-s is-warn-solid" onclick="submitLoc('${jesc(warning.location)}',${index})">确认</button><button class="btn-s is-ghost-strong" onclick="hideLoc(${index})">取消</button></div></div>`;
  }).join("");
}

function renderNew(items) {
  if (!items.length) return "";
  const header = `<div class="warn"><div class="row"><div class="col"><span class="sub">以下条码未在 stockpile 中找到，可校正、删除或保留后继续：</span></div><div class="actions"><button class="btn-s is-warn" id="nbcopyall" onclick="copyAllNewBc()">一键复制</button></div></div></div>`;
  return header + items.map((barcode, index) =>
    `<div class="warn" id="nb_${index}"><div class="row"><div class="col"><span class="code">${esc(barcode)}</span></div><div class="actions"><button class="btn-s is-warn" onclick="showNbEdit(${index})">校正</button><button class="btn-s is-danger" onclick="delNewBc('${jesc(barcode)}',${index})">删除</button></div></div><div class="form" id="nbf_${index}"><input id="nbi_${index}" placeholder="输入正确条码"><button class="btn-s is-warn-solid" onclick="submitNewBc('${jesc(barcode)}',${index})">确认</button><button class="btn-s is-ghost-strong" onclick="hideNbEdit(${index})">取消</button></div></div>`
  ).join("");
}

function showNbEdit(index) { $("#nbf_" + index).style.display = "flex"; $("#nbi_" + index).focus(); }
function hideNbEdit(index) { $("#nbf_" + index).style.display = "none"; }

async function copyAllNewBc() {
  const items = Array.from(document.querySelectorAll('[id^="nb_"] .code')).map((el) => el.textContent);
  if (!items.length) return;
  try {
    await copyToClip(items.join("\n"));
    const button = document.getElementById("nbcopyall");
    if (button) { button.textContent = "已复制 ✓"; setTimeout(() => { button.textContent = "一键复制"; }, 2000); }
  } catch (error) { alert("复制失败：" + error); }
}

async function submitNewBc(oldBarcode, index) {
  const input = $("#nbi_" + index);
  const newBarcode = input.value.trim();
  if (!newBarcode) { input.focus(); return; }
  const button = document.querySelector(`#nbf_${index} .is-warn-solid`);
  button.disabled = true; button.textContent = "提交中...";
  try {
    const data = await postJSON("/correct", { old_barcode: oldBarcode, new_barcode: newBarcode });
    if (!data.ok) { alert("校正失败：" + data.msg); button.disabled = false; button.textContent = "确认"; return; }
    Alpine.store('term').push("新条码校正：" + oldBarcode + " -> " + newBarcode, "log-ok");
    await reloadStatus();
  } catch (error) { alert("请求失败：" + error); button.disabled = false; button.textContent = "确认"; }
}

async function delNewBc(barcode, index) {
  const button = document.querySelector(`#nb_${index} .is-danger`);
  button.disabled = true; button.textContent = "删除中...";
  try {
    const data = await postJSON("/delete_barcode", { barcode });
    if (!data.ok) { alert("删除失败：" + data.msg); button.disabled = false; button.textContent = "删除"; return; }
    Alpine.store('term').push("已删除新条码：" + barcode, "log-warn");
    await reloadStatus();
  } catch (error) { alert("请求失败：" + error); button.disabled = false; button.textContent = "删除"; }
}

function parseP2WFromLog(log) {
  return (log || [])
    .filter((text) => text.startsWith("[PHASE2_WARNING]"))
    .map((text) => {
      const match = text.match(/^\[PHASE2_WARNING\] (\S+) (.+)$/);
      if (!match) return null;
      const barcode = match[1];
      let payload;
      try { payload = JSON.parse(match[2]); } catch (_) { payload = null; }
      if (payload && typeof payload === "object") {
        return { barcode, reason: payload.reason || match[2], locations: [], stockpile_stores: payload.stockpile_stores || [], stockpile_warehouses: payload.stockpile_warehouses || [], scan_stores: payload.scan_stores || [], scan_warehouses: payload.scan_warehouses || [], warehouse_only_location: payload.warehouse_only_location || "", resolved: false, resolution: null };
      }
      const reason = match[2];
      const locations = reason.match(/'([^']+)'/g) || [];
      return { barcode, reason, locations: locations.map((item) => item.replace(/'/g, "")), resolved: false, resolution: null };
    })
    .filter(Boolean);
}

function isUnknownPrefixWarning(warning) { return typeof warning.reason === "string" && warning.reason.includes("unknown location prefix"); }

async function submitExLoc(barcode, inputId, buttonId) {
  const input = document.getElementById(inputId);
  const value = input ? input.value.trim() : "";
  if (!value) { if (input) input.focus(); return; }
  const button = document.getElementById(buttonId);
  if (button) { button.disabled = true; button.textContent = "提交中..."; }
  try { await resolveEx(barcode, value); } catch (error) { if (button) { button.disabled = false; button.textContent = "提交新库位"; } alert("提交失败：" + error); }
}

async function submitNoStore(barcode, warehouseLocation, inputId, buttonId) {
  const input = document.getElementById(inputId);
  const store = input ? input.value.trim() : "";
  if (!store) { if (input) input.focus(); return; }
  const button = document.getElementById(buttonId);
  const fullLocation = store + "/" + warehouseLocation;
  if (button) { button.disabled = true; button.textContent = "提交中..."; }
  try { await resolveEx(barcode, fullLocation); } catch (error) { if (button) { button.disabled = false; button.textContent = "填充店面"; } alert("提交失败：" + error); }
}

function renderUnknownPrefixCard(warning) {
  const barcode = warning.barcode;
  const key = barcode.replace(/\W/g, "_");
  const inputId = `exli_${key}`;
  const buttonId = `exlf_${key}`;
  return `<div class="warn"><div class="row"><div class="col"><span class="code">${esc(barcode)}</span><span class="sub text-warn-amber">${esc(warning.reason)}</span></div></div><div class="actions u-mt-2"><input id="${inputId}" class="form-input-text" placeholder="填写正确库位" /><button id="${buttonId}" class="btn-s is-warn-solid" onclick="submitExLoc('${jesc(barcode)}','${inputId}','${buttonId}')">提交新库位</button><button class="btn-s is-danger" onclick="resolveEx('${jesc(barcode)}','ignore')">删除</button></div></div>`;
}

function renderNoStoreCard(warning) {
  const barcode = warning.barcode;
  const key = barcode.replace(/\W/g, "_");
  const inputId = `nsli_${key}`;
  const buttonId = `nslf_${key}`;
  const warehouseOnly = warning.warehouse_only_location || "";
  const scanWh = (warning.scan_warehouses || []).join(", ");
  const stockWh = (warning.stockpile_warehouses || []).join(", ");
  const whInfo = [
    scanWh ? `扫描仓库：${scanWh}` : "",
    stockWh ? `系统仓库：${stockWh}` : "",
  ].filter(Boolean).join(" / ");
  return `<div class="warn"><div class="row"><div class="col"><span class="code">${esc(barcode)}</span><span class="sub text-warn-amber">缺少店面位置${whInfo ? "，当前 " + whInfo : ""}</span></div></div><div class="actions u-mt-2"><input id="${inputId}" class="form-input-text" placeholder="填写店面位置，如 A-01-01" /><button id="${buttonId}" class="btn-s is-warn-solid" onclick="submitNoStore('${jesc(barcode)}','${jesc(warehouseOnly)}','${inputId}','${buttonId}')">填充店面</button><button class="btn-s is-danger" onclick="resolveEx('${jesc(barcode)}','${jesc(warehouseOnly)}')">仅保留仓库</button></div></div>`;
}

function renderP2Warnings(items) {
  if (!items.length) return "";
  return '<div class="warn"><div class="col"><span class="sub text-danger-light">以下条码存在数据异常，请选择处理方式后继续：</span></div></div>' +
    items.map((warning) => {
      if (warning.resolved) return `<div class="warn"><div class="row"><div class="col"><span class="code code--struck">${esc(warning.barcode)}</span><span class="sub">${esc(warning.reason)}</span></div><span class="${warning.resolution === "ignore" ? "tag-del" : "tag-ok"}">${warning.resolution === "ignore" ? "已忽略" : "已选 " + esc(warning.resolution)}</span></div></div>`;
      if (warning.reason === "multi_location") return renderDupCard(warning);
      if (warning.reason === "no_store_location") return renderNoStoreCard(warning);
      if (isUnknownPrefixWarning(warning)) return renderUnknownPrefixCard(warning);
      return `<div class="warn"><div class="row"><div class="col"><span class="code">${esc(warning.barcode)}</span><span class="sub">${esc(warning.reason)}</span></div><div class="actions">${(warning.locations || []).map((loc) => `<button class="btn-s is-warn" onclick="resolveEx('${jesc(warning.barcode)}','${jesc(loc)}')">选 ${esc(loc)}</button>`).join("")}<button class="btn-s is-danger" onclick="resolveEx('${jesc(warning.barcode)}','ignore')">忽略</button></div></div></div>`;
    }).join("");
}

export function renderReview(data) {
  const warnBox = $("#warnBox");
  if (data.waiting_stage === "anomaly" || data.waiting_stage === "phase1_barcode") { warnBox.innerHTML = renderBarcodes(data.barcode_warnings || []); return; }
  if (data.waiting_stage === "location_format" || data.waiting_stage === "phase1_location") { warnBox.innerHTML = renderLocs(data.location_warnings || []); return; }
  if (data.waiting_stage === "phase2_review" || data.waiting_stage === "new_barcodes" || data.waiting_stage === "phase2") {
    const phase2Warnings = data.phase2_warnings && data.phase2_warnings.length ? data.phase2_warnings : parseP2WFromLog(data.log);
    const html = renderNew(data.new_barcodes || []) + renderP2Warnings(phase2Warnings);
    warnBox.innerHTML = html || '<div class="empty">等待确认后继续</div>';
    return;
  }
  if ((data.barcode_warnings || []).length) { warnBox.innerHTML = renderBarcodes(data.barcode_warnings); return; }
  if ((data.location_warnings || []).length) { warnBox.innerHTML = renderLocs(data.location_warnings); return; }
  if ((data.new_barcodes || []).length) { warnBox.innerHTML = renderNew(data.new_barcodes); return; }
  warnBox.innerHTML = '<div class="empty">暂无需要人工处理的异常</div>';
}

function showBc(index) { $("#bcf_" + index).style.display = "flex"; $("#bci_" + index).focus(); }
function hideBc(index) { $("#bcf_" + index).style.display = "none"; }
function showLoc(index) { $("#lf_" + index).style.display = "flex"; $("#li_" + index).focus(); }
function hideLoc(index) { $("#lf_" + index).style.display = "none"; }
function ignoreBc(index) { const el = $("#bc_" + index); if (!el) return; el.style.opacity = ".35"; el.style.pointerEvents = "none"; Alpine.store('term').push("已忽略异常条码条目 #" + (index + 1)); }

async function reloadStatus() {
  const response = await fetch("/status");
  const data = await response.json();
  renderReview(data);
  return data;
}

async function resolveEx(barcode, resolution) {
  try {
    const data = await postJSON("/resolve_exception", { barcode, resolution });
    if (!data.ok) { alert("操作失败：" + data.msg); return; }
    Alpine.store('term').push(resolution === "ignore" ? `已忽略条码：${barcode}` : `条码 ${barcode} 使用库位 ${resolution}`, "log-ok");
    await reloadStatus();
  } catch (error) { alert("请求失败：" + error); }
}

initDup({ resolveEx });

async function delBc(barcode, index) {
  const button = document.querySelector(`#bc_${index} .is-danger`);
  button.disabled = true; button.textContent = "删除中...";
  try {
    const data = await postJSON("/delete_barcode", { barcode });
    if (!data.ok) { alert("删除失败：" + data.msg); button.disabled = false; button.textContent = "删除"; return; }
    Alpine.store('term').push("已删除条码：" + barcode, "log-warn");
    await reloadStatus();
  } catch (error) { alert("请求失败：" + error); button.disabled = false; button.textContent = "删除"; }
}

async function submitBc(oldBarcode, index) {
  const input = $("#bci_" + index);
  const newBarcode = input.value.trim();
  if (!newBarcode) { input.focus(); return; }
  const button = document.querySelector(`#bcf_${index} .is-warn-solid`);
  button.disabled = true; button.textContent = "提交中...";
  try {
    const data = await postJSON("/correct", { old_barcode: oldBarcode, new_barcode: newBarcode });
    if (!data.ok) { alert("校正失败：" + data.msg); button.disabled = false; button.textContent = "确认"; return; }
    Alpine.store('term').push("条码校正：" + oldBarcode + " -> " + newBarcode, "log-ok");
    await reloadStatus();
  } catch (error) { alert("请求失败：" + error); button.disabled = false; button.textContent = "确认"; }
}

async function submitLoc(oldLocation, index) {
  const input = $("#li_" + index);
  const newLocation = input.value.trim();
  if (!newLocation) { input.focus(); return; }
  const button = document.querySelector(`#lf_${index} .is-warn-solid`);
  button.disabled = true; button.textContent = "提交中...";
  try {
    const data = await postJSON("/correct_location", { old_location: oldLocation, new_location: newLocation });
    if (!data.ok) { alert("校正失败：" + data.msg); button.disabled = false; button.textContent = "确认"; return; }
    Alpine.store('term').push("库位校正：" + oldLocation + " -> " + newLocation, "log-ok");
    await reloadStatus();
  } catch (error) { alert("请求失败：" + error); button.disabled = false; button.textContent = "确认"; }
}

window.showNbEdit = showNbEdit;
window.hideNbEdit = hideNbEdit;
window.copyAllNewBc = copyAllNewBc;
window.submitNewBc = submitNewBc;
window.delNewBc = delNewBc;
window.submitExLoc = submitExLoc;
window.submitNoStore = submitNoStore;
window.showBc = showBc;
window.hideBc = hideBc;
window.showLoc = showLoc;
window.hideLoc = hideLoc;
window.ignoreBc = ignoreBc;
window.resolveEx = resolveEx;
window.delBc = delBc;
window.submitBc = submitBc;
window.submitLoc = submitLoc;