import { esc, logClass, copyToClip, setupDropZone } from "./shared.js";
import { uploadTransferFiles, loadTransferFiles } from "./transfer.js";
import { sendTextMessage, loadMessages, deleteMessage } from "./messaging.js";
import { initWarnings, waitMsg, renderReview } from "./index-warnings.js";
import { initStockpile } from "./index-stockpile.js";

const $ = (selector) => document.querySelector(selector);
let selected = [], poll = null, lastLog = 0, logs = [];

function setBadge(type, text) { const b = $("#badge"); b.className = "badge badge-" + type; b.textContent = text; }
function setStatus(text, cls = "") { const s = $("#status"); s.innerHTML = text; s.className = "status" + (cls ? " " + cls : ""); }
function term(text, cls = "", src = "lp") { logs.push({ text, cls, src }); renderLog(); }
initWarnings({ term });

function renderLog() {
  const tbod = $("#tbod");
  tbod.innerHTML = logs.length ? logs.map((i) => `<div class="${i.src === "dc" ? "log-dc" : "log-lp"} ${i.cls}">${esc(i.text)}</div>`).join("") : '<span class="log-dim">等待操作</span>';
  tbod.scrollTop = tbod.scrollHeight;

  const count = $("#termFabCount");
  if (count) {
    count.textContent = String(logs.length);
    count.classList.remove("is-pulse");
    void count.offsetWidth;
    count.classList.add("is-pulse");
  }
  const qCount = $("#quickTermCount");
  if (qCount) qCount.textContent = String(logs.length);
}
function clearLog() { logs = []; renderLog(); } window.clearLog = clearLog;

function renderFiles() {
  $("#files").innerHTML = selected.map((f, i) => `<div class="file"><span class="name">${esc(f.name)}</span><span class="rm" onclick="rmFile(${i})">×</span></div>`).join("");
  $("#upload").disabled = !selected.length;
}
function rmFile(i) { selected.splice(i, 1); renderFiles(); } window.rmFile = rmFile;

function switchPage(p) {
  document.querySelectorAll(".page").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".app-nav__item").forEach((el) => el.classList.remove("active"));
  const pageMap = { main: "pageMain", dup: "pageDup", purchase: "pagePurchase", attendance: "pageAttendance" };
  const navMap = { main: "navMain", dup: "navDup", purchase: "navPurchase", attendance: "navAttendance" };
  const pageId = pageMap[p];
  const navId = navMap[p];
  if (pageId) document.getElementById(pageId)?.classList.add("active");
  if (navId) document.getElementById(navId)?.classList.add("active");
} window.switchPage = switchPage;

// $("#hamb").onclick = () => $("#nav").classList.toggle("hide");  // 移除：filing 主题已删除汉堡按钮
setupDropZone($("#drop"), $("#fileInput"), (files) => { selected.push(...[...files]); renderFiles(); });

$("#upload").onclick = async () => {
  if (!selected.length) return;
  const upload = $("#upload"); upload.disabled = true;
  setStatus('<span class="spin"></span>正在上传文件...');
  try {
    const formData = new FormData(); selected.forEach((f) => formData.append("files", f));
    const data = await (await fetch("/upload", { method: "POST", body: formData })).json();
    if (!data.ok) { setStatus("上传失败：" + data.msg, "error"); term("上传失败：" + data.msg, "log-err"); upload.disabled = false; return; }
    setStatus("上传成功，共 " + data.saved.length + " 个文件", "success");
    term("上传完成：" + data.saved.join(", "), "log-ok"); $("#run").disabled = false;
  } catch (e) { setStatus("上传失败：" + e, "error"); term("上传失败：" + e, "log-err"); upload.disabled = false; }
};

function handleStatus(data) {
  if (data.log && data.log.length > lastLog) {
    for (let i = lastLog; i < data.log.length; i++) term(data.log[i], logClass(data.log[i]));
    lastLog = data.log.length;
  }
  renderReview(data);
  const cont = $("#cont");
  if (data.waiting) {
    clearInterval(poll); setBadge("waiting", "等待处理"); setStatus(waitMsg(data.waiting_stage));
    cont.style.display = "block"; cont.disabled = false; cont.textContent = "继续处理";
    term(waitMsg(data.waiting_stage), "log-warn"); return;
  }
  if (data.running) { setBadge("running", "处理中"); setStatus('<span class="spin"></span>处理中，请稍候...'); return; }
  clearInterval(poll); cont.style.display = "none";
  if (data.error) { setStatus("处理失败，请查看日志", "error"); setBadge("error", "出错"); $("#run").disabled = false; return; }
  if (data.done) {
    setStatus("处理完成，可下载结果", "success"); setBadge("done", "完成");
    $("#download").style.display = "block"; $("#copyModels").style.display = "block";
    $("#copyModelsAll").style.display = "block"; $("#reset").style.display = "block"; return;
  }
  setBadge("idle", "空闲");
}

function startPoll() {
  clearInterval(poll);
  poll = setInterval(async () => { try { handleStatus(await (await fetch("/status")).json()); } catch (e) { console.error("Status poll failed:", e); } }, 1000);
}

$("#run").onclick = async () => {
  const run = $("#run"); run.disabled = true; $("#cont").style.display = "none";
  setStatus('<span class="spin"></span>正在启动处理流程...'); setBadge("running", "处理中"); term("开始处理");
  try {
    const data = await (await fetch("/run", { method: "POST" })).json();
    if (!data.ok) { setStatus(data.msg, "error"); setBadge("error", "出错"); term("启动失败：" + data.msg, "log-err"); run.disabled = false; return; }
    startPoll();
  } catch (e) { setStatus("启动失败：" + e, "error"); setBadge("error", "出错"); term("启动失败：" + e, "log-err"); run.disabled = false; }
};

$("#cont").onclick = async () => {
  const cont = $("#cont"); cont.disabled = true; cont.textContent = "处理中...";
  setBadge("running", "处理中"); setStatus('<span class="spin"></span>继续处理中...'); term("继续处理");
  try {
    const data = await (await fetch("/continue", { method: "POST" })).json();
    if (!data.ok) { setBadge("waiting", "等待处理"); setStatus(data.msg, "error"); cont.disabled = false; cont.textContent = "继续处理"; term("继续失败：" + data.msg, "log-err"); return; }
    startPoll();
  } catch (e) { setStatus("请求失败：" + e, "error"); cont.disabled = false; cont.textContent = "继续处理"; term("请求失败：" + e, "log-err"); }
};

$("#download").onclick = () => { location.href = "/download"; term("下载结果文件"); };

$("#reset").onclick = () => {
  selected = []; $("#files").innerHTML = ""; $("#fileInput").value = "";
  $("#upload").disabled = true; $("#run").disabled = true;
  const c = $("#cont"); c.style.display = "none"; c.disabled = false; c.textContent = "继续处理";
  $("#download").style.display = "none"; $("#copyModels").style.display = "none";
  $("#copyModelsAll").style.display = "none"; $("#reset").style.display = "none";
  $("#warnBox").innerHTML = '<div class="empty">暂无需要人工处理的异常</div>';
  setBadge("idle", "空闲"); setStatus("请先上传文件"); clearInterval(poll); lastLog = 0;
  term("已清空界面，准备下一批", "log-dim");
};

async function copyModelsAndDisplay(isUnique) {
  const cm = isUnique ? $("#copyModels") : $("#copyModelsAll"); const label = isUnique ? "复制所有型号" : "复制所有型号（含重复）";
  cm.disabled = true; cm.textContent = "复制中...";
  try {
    const data = await (await fetch("/models")).json();
    if (!data.ok) { alert("获取失败：" + data.msg); cm.disabled = false; cm.textContent = label; return; }
    const models = isUnique ? [...new Set(data.models)] : data.models;
    await copyToClip(models.join("\n")); const l = isUnique ? "个型号（去重）" : "个型号（含重复）";
    term(`已复制 ${models.length} ${l}`, "log-ok"); cm.textContent = `已复制 ${models.length} ${l}`;
    setTimeout(() => { cm.textContent = label; cm.disabled = false; }, 2500);
  } catch (e) { alert("复制失败：" + e); cm.textContent = label; cm.disabled = false; }
}
$("#copyModels").onclick = () => copyModelsAndDisplay(true);
$("#copyModelsAll").onclick = () => copyModelsAndDisplay(false);

function setupDupZone() { setupDropZone($("#dupDrop"), $("#dupInput"), (files) => { if (files[0]) runDup(files[0]); }); }

async function runDup(file) {
  const dupRes = $("#dupRes");
  dupRes.innerHTML = '<div class="empty"><span class="spin"></span>检查中...</div>';
  term("开始重复检查：" + file.name, "", "dc");
  const formData = new FormData(); formData.append("file", file);
  try {
    const data = await (await fetch("/check_dup", { method: "POST", body: formData })).json();
    if (!data.ok) { dupRes.innerHTML = `<div class="empty text-danger-light">错误：${esc(data.msg)}</div>`; term("检查失败：" + data.msg, "log-err", "dc"); return; }
    if (data.dup_count === 0) { dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | <span class="ok">无重复</span></div>`; term("重复检查完成：无重复", "log-ok", "dc"); return; }
    dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | 重复值：<span class="hl">${data.dup_count}</span></div><table><thead><tr><th>值</th><th>出现次数</th><th>行号</th></tr></thead><tbody>${data.duplicates.map((i) => `<tr><td>${esc(i.value)}</td><td>${i.count}</td><td>${i.rows.join(", ")}</td></tr>`).join("")}</tbody></table>`;
    term("重复检查完成：发现 " + data.dup_count + " 个重复值", "log-warn", "dc");
  } catch (e) { dupRes.innerHTML = `<div class="empty text-danger-light">请求失败：${esc(String(e))}</div>`; term("请求失败：" + e, "log-err", "dc"); }
}

function setupTransferZone() { setupDropZone($("#tDrop"), $("#tInput"), async (files) => { await uploadTransferFiles(files, $("#tMsg")); loadTransferUI(); }); }

async function loadTransferUI() {
  const items = await loadTransferFiles();
  $("#tList").innerHTML = items.length ? items.map((i) => `<div class="transfer-file"><span class="transfer-file__name" title="${esc(i.name)}">${esc(i.name)}</span><span class="transfer-file__size">${i.size}KB</span><a class="transfer-file__dl" href="/transfer_download/${encodeURIComponent(i.name)}">下载</a></div>`).join("") : '<div class="empty">暂无</div>';
}

const textInput = $("#textInput"), copyText = $("#copyText"), sendText = $("#sendText"), msgList = $("#msgList");

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
  msgList.innerHTML = m.length ? m.map((i) => `<div class="message${i.sender === "A" ? " is-self" : ""}"><div class="message__head"><span class="message__source">${i.sender === "A" ? "我（A）" : "B 端"}</span><span><span class="message__time">${esc(i.time)}</span><button class="message__del" onclick="delMsg(${i.id})">×</button></span></div><div class="message__body">${esc(i.text)}</div></div>`).join("") : '<div class="empty">暂无消息</div>';
}

async function delMsg(id) { await deleteMessage(id); loadMsgsUI(); } window.delMsg = delMsg;

async function restore() {
  try {
    const data = await (await fetch("/status")).json();
    if (data.log && data.log.length) { logs = data.log.map((t) => ({ text: t, cls: logClass(t), src: "lp" })); renderLog(); lastLog = data.log.length; }
    handleStatus(data); if (data.running) startPoll();
  } catch (e) { console.error("Status restore failed:", e); }
}

setupDupZone(); setupTransferZone(); loadTransferUI(); loadMsgsUI(); restore();
setInterval(loadTransferUI, 5000); setInterval(loadMsgsUI, 5000);
initStockpile();

$("#termFab")?.addEventListener("click", () => {
  $("#termDrawer").classList.toggle("hide");
});
$("#termClose")?.addEventListener("click", () => {
  $("#termDrawer").classList.add("hide");
});

$("#transferFab")?.addEventListener("click", () => {
  $("#transferDrawer").classList.toggle("is-open");
  $("#transferFabDot").classList.remove("is-on");
  $("#quickTransferDot")?.classList.remove("is-on");
});
$("#transferDrawerClose")?.addEventListener("click", () => {
  $("#transferDrawer").classList.remove("is-open");
});

// ========== 右下角汉堡菜单 ==========
$("#quickToggle")?.addEventListener("click", (e) => {
  e.stopPropagation();
  $("#quickMenu")?.classList.toggle("is-open");
});
$("#quickTransfer")?.addEventListener("click", () => {
  $("#transferFab")?.click();
  $("#quickMenu")?.classList.remove("is-open");
});
$("#quickTerm")?.addEventListener("click", () => {
  $("#termFab")?.click();
  $("#quickMenu")?.classList.remove("is-open");
});
document.addEventListener("click", (e) => {
  const m = $("#quickMenu");
  if (m && !m.contains(e.target)) m.classList.remove("is-open");
});
