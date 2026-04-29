import "./store.js";
import { esc, logClass, copyToClip, setupDropZone } from "./shared.js";
import { uploadTransferFiles, loadTransferFiles } from "./transfer.js";
import { sendTextMessage, loadMessages, deleteMessage } from "./messaging.js";
import { initWarnings, waitMsg, renderReview } from "./index-warnings.js";
import { initStockpile } from "./index-stockpile.js";

const $ = (selector) => document.querySelector(selector);
let poll = null;

initWarnings();


function switchPage(p) {
  document.querySelectorAll(".page").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".app-nav__item").forEach((el) => el.classList.remove("active"));
  const pageMap = { main: "pageMain", dup: "pageDup", purchase: "pagePurchase", attendance: "pageAttendance", history: "pageHistory", data_quality: "pageDataQuality" };
  const navMap = { main: "navMain", dup: "navDup", purchase: "navPurchase", attendance: "navAttendance", history: "navHistory", data_quality: "navDataQuality" };
  const pageId = pageMap[p];
  const navId = navMap[p];
  if (pageId) document.getElementById(pageId)?.classList.add("active");
  if (navId) document.getElementById(navId)?.classList.add("active");
} window.switchPage = switchPage;

// $("#hamb").onclick = () => $("#nav").classList.toggle("hide");  // 移除：filing 主题已删除汉堡按钮
setupDropZone($("#drop"), $("#fileInput"), (files) => { Alpine.store('upload').add([...files]); });

$("#upload").onclick = async () => {
  const sel = Alpine.store('upload').selected;
  if (!sel.length) return;
  Alpine.store('app').setStatus('<span class="spin"></span>正在上传文件...');
  try {
    const formData = new FormData();
    sel.forEach((f) => formData.append("files", f));
    const data = await (await fetch("/upload", { method: "POST", body: formData })).json();
    if (!data.ok) {
      Alpine.store('app').setStatus("上传失败：" + data.msg, "error");
      Alpine.store('term').push("上传失败：" + data.msg, "log-err");
      return;
    }
    Alpine.store('app').setStatus("上传成功，共 " + data.saved.length + " 个文件", "success");
    Alpine.store('term').push("上传完成：" + data.saved.join(", "), "log-ok");
    $("#run").disabled = false;
  } catch (e) {
    Alpine.store('app').setStatus("上传失败：" + e, "error");
    Alpine.store('term').push("上传失败：" + e, "log-err");
  }
};

function handleStatus(data) {
  if (data.log && data.log.length > Alpine.store('term').lastLog) {
    const last = Alpine.store('term').lastLog;
    for (let i = last; i < data.log.length; i++) Alpine.store('term').push(data.log[i], logClass(data.log[i]));
    Alpine.store('term').setLastLog(data.log.length);
  }
  renderReview(data);
  const cont = $("#cont");
  if (data.waiting) {
    clearInterval(poll); Alpine.store('app').setBadge("waiting", "等待处理"); Alpine.store('app').setStatus(waitMsg(data.waiting_stage));
    cont.style.display = "block"; cont.disabled = false; cont.textContent = "继续处理";
    Alpine.store('term').push(waitMsg(data.waiting_stage), "log-warn"); return;
  }
  if (data.running) { Alpine.store('app').setBadge("running", "处理中"); Alpine.store('app').setStatus('<span class="spin"></span>处理中，请稍候...'); return; }
  clearInterval(poll); cont.style.display = "none";
  if (data.error) { Alpine.store('app').setStatus("处理失败，请查看日志", "error"); Alpine.store('app').setBadge("error", "出错"); $("#run").disabled = false; return; }
  if (data.done) {
    Alpine.store('app').setStatus("处理完成，可下载结果", "success"); Alpine.store('app').setBadge("done", "完成");
    $("#download").style.display = "block"; $("#copyModels").style.display = "block";
    $("#copyModelsAll").style.display = "block"; $("#reset").style.display = "block"; return;
  }
  Alpine.store('app').setBadge("idle", "空闲");
}

function startPoll() {
  clearInterval(poll);
  poll = setInterval(async () => { try { handleStatus(await (await fetch("/status")).json()); } catch (e) { console.error("Status poll failed:", e); } }, 1000);
}

$("#run").onclick = async () => {
  const run = $("#run"); run.disabled = true; $("#cont").style.display = "none";
  Alpine.store('app').setStatus('<span class="spin"></span>正在启动处理流程...'); Alpine.store('app').setBadge("running", "处理中"); Alpine.store('term').push("开始处理");
  try {
    const data = await (await fetch("/run", { method: "POST" })).json();
    if (!data.ok) { Alpine.store('app').setStatus(data.msg, "error"); Alpine.store('app').setBadge("error", "出错"); Alpine.store('term').push("启动失败：" + data.msg, "log-err"); run.disabled = false; return; }
    startPoll();
  } catch (e) { Alpine.store('app').setStatus("启动失败：" + e, "error"); Alpine.store('app').setBadge("error", "出错"); Alpine.store('term').push("启动失败：" + e, "log-err"); run.disabled = false; }
};

$("#cont").onclick = async () => {
  const cont = $("#cont"); cont.disabled = true; cont.textContent = "处理中...";
  Alpine.store('app').setBadge("running", "处理中"); Alpine.store('app').setStatus('<span class="spin"></span>继续处理中...'); Alpine.store('term').push("继续处理");
  try {
    const data = await (await fetch("/continue", { method: "POST" })).json();
    if (!data.ok) { Alpine.store('app').setBadge("waiting", "等待处理"); Alpine.store('app').setStatus(data.msg, "error"); cont.disabled = false; cont.textContent = "继续处理"; Alpine.store('term').push("继续失败：" + data.msg, "log-err"); return; }
    startPoll();
  } catch (e) { Alpine.store('app').setStatus("请求失败：" + e, "error"); cont.disabled = false; cont.textContent = "继续处理"; Alpine.store('term').push("请求失败：" + e, "log-err"); }
};

$("#download").onclick = () => { location.href = "/download"; Alpine.store('term').push("下载结果文件"); };

$("#reset").onclick = () => {
  Alpine.store('upload').clear();
  $("#fileInput").value = "";
  $("#run").disabled = true;
  const c = $("#cont"); c.style.display = "none"; c.disabled = false; c.textContent = "继续处理";
  $("#download").style.display = "none"; $("#copyModels").style.display = "none";
  $("#copyModelsAll").style.display = "none"; $("#reset").style.display = "none";
  $("#warnBox").innerHTML = '<div class="empty">暂无需要人工处理的异常</div>';
  Alpine.store('app').setBadge("idle", "空闲"); Alpine.store('app').setStatus("请先上传文件"); clearInterval(poll); Alpine.store('term').setLastLog(0);
  Alpine.store('term').push("已清空界面，准备下一批", "log-dim");
};

async function copyModelsAndDisplay(isUnique) {
  const cm = isUnique ? $("#copyModels") : $("#copyModelsAll"); const label = isUnique ? "复制所有型号" : "复制所有型号（含重复）";
  cm.disabled = true; cm.textContent = "复制中...";
  try {
    const data = await (await fetch("/models")).json();
    if (!data.ok) { alert("获取失败：" + data.msg); cm.disabled = false; cm.textContent = label; return; }
    const models = isUnique ? [...new Set(data.models)] : data.models;
    await copyToClip(models.join("\n")); const l = isUnique ? "个型号（去重）" : "个型号（含重复）";
    Alpine.store('term').push(`已复制 ${models.length} ${l}`, "log-ok"); cm.textContent = `已复制 ${models.length} ${l}`;
    setTimeout(() => { cm.textContent = label; cm.disabled = false; }, 2500);
  } catch (e) { alert("复制失败：" + e); cm.textContent = label; cm.disabled = false; }
}
$("#copyModels").onclick = () => copyModelsAndDisplay(true);
$("#copyModelsAll").onclick = () => copyModelsAndDisplay(false);

function setupDupZone() { setupDropZone($("#dupDrop"), $("#dupInput"), (files) => { if (files[0]) runDup(files[0]); }); }

async function runDup(file) {
  const dupRes = $("#dupRes");
  dupRes.innerHTML = '<div class="empty"><span class="spin"></span>检查中...</div>';
  Alpine.store('term').push("开始重复检查：" + file.name, "", "dc");
  const formData = new FormData(); formData.append("file", file);
  try {
    const data = await (await fetch("/check_dup", { method: "POST", body: formData })).json();
    if (!data.ok) { dupRes.innerHTML = `<div class="empty text-danger-light">错误：${esc(data.msg)}</div>`; Alpine.store('term').push("检查失败：" + data.msg, "log-err", "dc"); return; }
    if (data.dup_count === 0) { dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | <span class="ok">无重复</span></div>`; Alpine.store('term').push("重复检查完成：无重复", "log-ok", "dc"); return; }
    dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | 重复值：<span class="hl">${data.dup_count}</span></div><table><thead><tr><th>值</th><th>出现次数</th><th>行号</th></tr></thead><tbody>${data.duplicates.map((i) => `<tr><td>${esc(i.value)}</td><td>${i.count}</td><td>${i.rows.join(", ")}</td></tr>`).join("")}</tbody></table>`;
    Alpine.store('term').push("重复检查完成：发现 " + data.dup_count + " 个重复值", "log-warn", "dc");
  } catch (e) { dupRes.innerHTML = `<div class="empty text-danger-light">请求失败：${esc(String(e))}</div>`; Alpine.store('term').push("请求失败：" + e, "log-err", "dc"); }
}

function setupTransferZone() { setupDropZone($("#tDrop"), $("#tInput"), async (files) => { await uploadTransferFiles(files, $("#tMsg")); loadTransferUI(); }); }

async function loadTransferUI() {
  const items = await loadTransferFiles();
  $("#tList").innerHTML = items.length ? items.map((i) => `<div class="transfer-file"><span class="transfer-file__name" title="${esc(i.name)}">${esc(i.name)}</span><span class="transfer-file__size">${i.size}KB</span><a class="transfer-file__dl" href="/transfer_download/${encodeURIComponent(i.name)}">下载</a></div>`).join("") : '<div class="empty">暂无</div>';
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

setupDupZone(); setupTransferZone(); loadTransferUI(); loadMsgsUI(); restore();
setInterval(loadTransferUI, 5000); setInterval(loadMsgsUI, 5000);
initStockpile();
