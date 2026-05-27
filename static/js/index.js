import { esc, logClass, copyToClip, setupDropZone } from "./shared.js";
import { uploadTransferFiles, loadTransferFiles } from "./transfer.js";
import { sendTextMessage, loadMessages, deleteMessage } from "./messaging.js";
import { initWarnings, waitMsg, renderReview } from "./index-warnings.js";
import { initStockpile } from "./index-stockpile.js";

const $ = (selector) => document.querySelector(selector);
let poll = null;

initWarnings();

setupDropZone($("#drop"), $("#fileInput"), (files) => {
  Alpine.store('upload').add([...files]);
  autoUploadAndRun();
});

async function autoUploadAndRun() {
  const sel = Alpine.store('upload').selected;
  if (!sel.length) return;
  Alpine.store('app').setStatus('<span class="spin"></span>正在上传文件...');
  Alpine.store('app').setBadge("running", "上传中");
  try {
    const formData = new FormData();
    sel.forEach((f) => formData.append("files", f));
    const data = await (await fetch("/upload", { method: "POST", body: formData })).json();
    if (!data.ok) {
      Alpine.store('app').setStatus("上传失败：" + data.msg, "error");
      Alpine.store('term').push("上传失败：" + data.msg, "log-err");
      Alpine.store('app').setBadge("error", "出错");
      return;
    }
    Alpine.store('term').push("上传完成：" + data.saved.join(", "), "log-ok");
    autoRun();
  } catch (e) {
    Alpine.store('app').setStatus("上传失败：" + e, "error");
    Alpine.store('term').push("上传失败：" + e, "log-err");
    Alpine.store('app').setBadge("error", "出错");
  }
}

async function autoRun() {
  Alpine.store('app').setStatus('<span class="spin"></span>正在启动处理流程...');
  Alpine.store('app').setBadge("running", "处理中");
  Alpine.store('term').push("自动开始处理");
  plStart();
  try {
    const data = await (await fetch("/run", { method: "POST" })).json();
    if (!data.ok) {
      Alpine.store('app').setStatus(data.msg, "error");
      Alpine.store('app').setBadge("error", "出错");
      Alpine.store('term').push("启动失败：" + data.msg, "log-err");
      plReset();
      return;
    }
    startPoll();
  } catch (e) {
    Alpine.store('app').setStatus("启动失败：" + e, "error");
    Alpine.store('app').setBadge("error", "出错");
    Alpine.store('term').push("启动失败：" + e, "log-err");
    plReset();
  }
}

$("#upload").onclick = () => autoUploadAndRun();

let _autoContinuing = false;

function _hasUnresolved(data) {
  const bw = data.barcode_warnings || [];
  const lw = data.location_warnings || [];
  const nb = data.new_barcodes || [];
  const pw = data.phase2_warnings || [];
  if (bw.some(w => !w.deleted && !w.corrected)) return true;
  if (lw.some(w => !w.corrected)) return true;
  if (nb.length > 0) return true;
  if (pw.some(w => !w.resolved)) return true;
  return false;
}

async function _autoContinue() {
  if (_autoContinuing) return;
  _autoContinuing = true;
  Alpine.store('app').setBadge("running", "处理中");
  Alpine.store('app').setStatus('<span class="spin"></span>异常已处理完毕，自动继续...');
  Alpine.store('term').push("异常全部处理完毕，自动继续", "log-ok");
  try {
    const data = await (await fetch("/continue", { method: "POST" })).json();
    if (!data.ok) {
      Alpine.store('app').setStatus(data.msg, "error");
      Alpine.store('term').push("继续失败：" + data.msg, "log-err");
      _autoContinuing = false;
      return;
    }
    startPoll();
  } catch (e) {
    Alpine.store('app').setStatus("请求失败：" + e, "error");
    Alpine.store('term').push("请求失败：" + e, "log-err");
  }
  _autoContinuing = false;
}

let _lastBatchId = "";

function _autoReset(batchId) {
  _lastBatchId = batchId || "";
  plFinish();
  Alpine.store('app').setStatus("处理完成", "success");
  Alpine.store('app').setBadge("done", "完成");
  Alpine.store('term').push("处理完成 · 批次 " + (_lastBatchId || "unknown"), "log-ok");
  Alpine.store('upload').markDone(_lastBatchId);
  $("#warnBox").innerHTML = '<div class="empty">暂无需要人工处理的异常</div>';
  setTimeout(() => {
    plReset();
    Alpine.store('app').setBadge("idle", "空闲");
    Alpine.store('app').setStatus("就绪 · 拖入文件开始下一批");
  }, 3000);
}

function _updateScanStats(data) {
  const bw = data.barcode_warnings || [];
  const lw = data.location_warnings || [];
  const nb = data.new_barcodes || [];
  const pw = data.phase2_warnings || [];
  const totalAnomalies = bw.filter(w => !w.deleted && !w.corrected).length
    + lw.filter(w => !w.corrected).length
    + pw.filter(w => !w.resolved).length;
  const totalNew = nb.length;

  const log = data.log || [];
  let totalBarcodes = 0;
  for (const line of log) {
    const m = line.match(/解析\s*(\d+)\s*条码/);
    if (m) totalBarcodes = parseInt(m[1]);
  }

  const el = (id, v) => { const e = $("#" + id); if (e) e.textContent = v; };
  if (totalBarcodes) {
    el("scTotal", totalBarcodes.toLocaleString());
    const matched = totalBarcodes - totalAnomalies - totalNew;
    const rate = totalBarcodes > 0 ? (matched / totalBarcodes * 100).toFixed(1) + "%" : "—";
    el("scMatchRate", rate);
    const bar = $("#scMatchBar"); if (bar) bar.style.width = (matched / totalBarcodes * 100) + "%";
  }
  el("scAnomalies", totalAnomalies || "0");
  el("scNewItems", totalNew || "0");
}

function handleStatus(data) {
  if (data.log && data.log.length > Alpine.store('term').lastLog) {
    const last = Alpine.store('term').lastLog;
    for (let i = last; i < data.log.length; i++) Alpine.store('term').push(data.log[i], logClass(data.log[i]));
    Alpine.store('term').setLastLog(data.log.length);
  }
  renderReview(data);
  _updateScanStats(data);
  const cont = $("#cont");
  if (data.waiting) {
    clearInterval(poll);
    if (!_hasUnresolved(data)) { _autoContinue(); return; }
    Alpine.store('app').setBadge("waiting", "等待处理");
    Alpine.store('app').setStatus(waitMsg(data.waiting_stage));
    cont.style.display = "block"; cont.disabled = false; cont.textContent = "继续处理";
    return;
  }
  if (data.running) { Alpine.store('app').setBadge("running", "处理中"); Alpine.store('app').setStatus('<span class="spin"></span>处理中，请稍候...'); return; }
  clearInterval(poll); cont.style.display = "none";
  if (data.error) { Alpine.store('app').setStatus("处理失败，请查看日志", "error"); Alpine.store('app').setBadge("error", "出错"); plReset(); return; }
  if (data.done) { _autoReset(data.batch_id); return; }
  Alpine.store('app').setBadge("idle", "空闲");
}

function startPoll() {
  clearInterval(poll);
  poll = setInterval(async () => { try { handleStatus(await (await fetch("/status")).json()); } catch (e) { console.error("Status poll failed:", e); } }, 1000);
}

// PR-FE-8a：Pipeline 假壳动画（B 选项 — 后端只发开始/完成，前端时间驱动 5 阶段）
const PL_STAGES = ["parse", "norm", "match", "audit", "commit"];
let _plTimer = null;
function plReset() {
  clearInterval(_plTimer); _plTimer = null;
  $("#plBarFill").style.width = "0%"; $("#plPct").textContent = "0%";
  document.querySelectorAll(".pl-stage-v2").forEach(el => el.classList.remove("is-current", "is-done"));
}
function plStart() {
  plReset();
  let pct = 0;
  // 走 0→90% 慢速（约 8 秒）；剩 10% 等 backend done 信号补满
  const cap = 90;
  const tickMs = 200;
  const totalSec = 8;
  const inc = cap / (totalSec * 1000 / tickMs);
  _plTimer = setInterval(() => {
    pct = Math.min(cap, pct + inc);
    plRender(pct);
    if (pct >= cap) { clearInterval(_plTimer); _plTimer = null; }
  }, tickMs);
}
function plRender(pct) {
  $("#plBarFill").style.width = pct + "%";
  $("#plPct").textContent = Math.round(pct) + "%";
  // 当前阶段：每 20% 一段
  const idx = Math.min(PL_STAGES.length - 1, Math.floor(pct / 20));
  document.querySelectorAll(".pl-stage-v2").forEach((el, i) => {
    el.classList.toggle("is-current", i === idx && pct < 100);
    el.classList.toggle("is-done", i < idx || pct >= 100);
  });
}
function plFinish() {
  clearInterval(_plTimer); _plTimer = null;
  plRender(100);
}

// 占位按钮：配置规则 / 重放上次（PR-FE-8 后续 PR 实现）
const _upRules = $("#upRules"); if (_upRules) _upRules.onclick = () => alert("配置规则：留作后续 PR 实现");
const _upReplay = $("#upReplay"); if (_upReplay) _upReplay.onclick = () => alert("重放上次：留作后续 PR 实现");
// 文件队列 panel header 的「+ 添加」按钮 → 触发隐藏 fileInput
const _fqAdd = $("#fqAddBtn"); if (_fqAdd) _fqAdd.onclick = () => $("#fileInput").click();

$("#run").onclick = () => autoRun();

$("#cont").onclick = async () => {
  const cont = $("#cont"); cont.disabled = true; cont.textContent = "处理中...";
  Alpine.store('app').setBadge("running", "处理中"); Alpine.store('app').setStatus('<span class="spin"></span>继续处理中...'); Alpine.store('term').push("继续处理");
  try {
    const data = await (await fetch("/continue", { method: "POST" })).json();
    if (!data.ok) { Alpine.store('app').setBadge("waiting", "等待处理"); Alpine.store('app').setStatus(data.msg, "error"); cont.disabled = false; cont.textContent = "继续处理"; Alpine.store('term').push("继续失败：" + data.msg, "log-err"); return; }
    startPoll();
  } catch (e) { Alpine.store('app').setStatus("请求失败：" + e, "error"); cont.disabled = false; cont.textContent = "继续处理"; Alpine.store('term').push("请求失败：" + e, "log-err"); }
};

$("#download").onclick = () => {
  const bid = _lastBatchId;
  if (bid) {
    location.href = "/scan_history/batches/" + encodeURIComponent(bid) + "/download/csv";
  } else {
    location.href = "/download";
  }
  Alpine.store('term').push("下载结果文件" + (bid ? " · " + bid : ""));
};

$("#reset").onclick = () => {
  Alpine.store('upload').clear();
  $("#fileInput").value = "";
  const c = $("#cont"); c.style.display = "none"; c.disabled = false; c.textContent = "继续处理";
  $("#download").style.display = "none"; $("#copyModels").style.display = "none";
  $("#copyModelsAll").style.display = "none";
  $("#warnBox").innerHTML = '<div class="empty">暂无需要人工处理的异常</div>';
  plReset();
  Alpine.store('app').setBadge("idle", "空闲"); Alpine.store('app').setStatus("就绪 · 拖入文件开始下一批"); clearInterval(poll); Alpine.store('term').setLastLog(0);
  Alpine.store('term').push("已清空文件队列", "log-dim");
};

async function copyModelsAndDisplay(isUnique, batchId) {
  const cm = isUnique ? $("#copyModels") : $("#copyModelsAll"); const label = isUnique ? "复制型号" : "复制型号(含重复)";
  cm.disabled = true; cm.textContent = "复制中...";
  try {
    const url = batchId ? "/models?batch_id=" + encodeURIComponent(batchId) : "/models";
    const data = await (await fetch(url)).json();
    if (!data.ok) { alert("获取失败：" + data.msg); cm.disabled = false; cm.textContent = label; return; }
    const models = isUnique ? [...new Set(data.models)] : data.models;
    await copyToClip(models.join("\n")); const l = isUnique ? "个型号（去重）" : "个型号（含重复）";
    Alpine.store('term').push(`已复制 ${models.length} ${l}`, "log-ok"); cm.textContent = `已复制 ${models.length} ${l}`;
    setTimeout(() => { cm.textContent = label; cm.disabled = false; }, 2500);
  } catch (e) { alert("复制失败：" + e); cm.textContent = label; cm.disabled = false; }
}
$("#copyModels").onclick = () => copyModelsAndDisplay(true, _lastBatchId);
$("#copyModelsAll").onclick = () => copyModelsAndDisplay(false, _lastBatchId);

function setupTransferZone() { setupDropZone($("#tDrop"), $("#tInput"), async (files) => { await uploadTransferFiles(files, $("#tMsg")); loadTransferUI(); }); }

async function loadTransferUI() {
  const items = await loadTransferFiles();
  Alpine.store('transfer').setFiles(items);
}

const textInput = $("#textInput"), copyText = $("#copyText"), sendText = $("#sendText");

copyText.onclick = async () => {
  if (!textInput.value) return; await copyToClip(textInput.value);
  copyText.textContent = "已复制"; copyText.classList.add("copied");
  setTimeout(() => { copyText.textContent = "复制"; copyText.classList.remove("copied"); }, 1500);
};
sendText.onclick = sendMsg;
textInput.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendMsg(); });

async function sendMsg() {
  const text = textInput.value.trim(); if (!text) return; sendText.disabled = true;
  try { const data = await sendTextMessage(text, "A"); if (data.ok) { textInput.value = ""; loadMsgsUI(); } } catch (e) { console.error("Send message failed:", e); }
  sendText.disabled = false;
}

async function loadMsgsUI() {
  const m = await loadMessages();
  Alpine.store('messages').setList(m);
}

async function __delMsg(id) { await deleteMessage(id); loadMsgsUI(); }
window.__delMsg = __delMsg;
window.__batchDownload = (bid) => { location.href = "/scan_history/batches/" + encodeURIComponent(bid) + "/download/csv"; };
window.__batchCopyModels = (bid) => copyModelsAndDisplay(true, bid);

async function restore() {
  try {
    const data = await (await fetch("/status")).json();
    if (data.log && data.log.length) {
      const term = Alpine.store('term');
      term.clear();
      data.log.forEach((t) => term.push(t, logClass(t)));
      term.setLastLog(data.log.length);
    }
    handleStatus(data); if (data.running) startPoll();
  } catch (e) { console.error("Status restore failed:", e); }
}

setupTransferZone(); loadTransferUI(); loadMsgsUI(); restore();
setInterval(loadTransferUI, 5000); setInterval(loadMsgsUI, 5000);
initStockpile();

async function loadLastBatch() {
  try {
    const r = await fetch("/scan_history/batches");
    const d = await r.json();
    if (!d.ok || !d.batches || !d.batches.length) return;
    const b = d.batches[0];
    const s = $("#exIdleSession"); if (s) s.textContent = b.employee + " · 价格标";
    const c = $("#exIdleCount"); if (c) c.textContent = (b.csv_rows || 0) + " 条码";
    const t = $("#exIdleTime"); if (t) t.textContent = (b.scanned_at || "").slice(5, 16);
  } catch (_) {}
}
loadLastBatch();
