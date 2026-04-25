import { esc, logClass, copyToClip, setupDropZone } from "./shared.js";
import { uploadTransferFiles, loadTransferFiles } from "./transfer.js";
import { sendTextMessage, loadMessages, deleteMessage } from "./messaging.js";
import { initWarnings, waitMsg, renderReview } from "./index-warnings.js";

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
}
function clearLog() { logs = []; renderLog(); } window.clearLog = clearLog;

function renderFiles() {
  $("#files").innerHTML = selected.map((f, i) => `<div class="file"><span class="name">${esc(f.name)}</span><span class="rm" onclick="rmFile(${i})">×</span></div>`).join("");
  $("#upload").disabled = !selected.length;
}
function rmFile(i) { selected.splice(i, 1); renderFiles(); } window.rmFile = rmFile;

function switchPage(p) {
  document.querySelectorAll(".page").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((el) => el.classList.remove("active"));
  const pageMap = { main: "pageMain", dup: "pageDup", purchase: "pagePurchase", attendance: "pageAttendance" };
  const navMap = { main: "navMain", dup: "navDup", purchase: "navPurchase", attendance: "navAttendance" };
  const pageId = pageMap[p];
  const navId = navMap[p];
  if (pageId) document.getElementById(pageId)?.classList.add("active");
  if (navId) document.getElementById(navId)?.classList.add("active");
} window.switchPage = switchPage;

$("#hamb").onclick = () => $("#nav").classList.toggle("hide");
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
    if (!data.ok) { dupRes.innerHTML = `<div class="empty" style="color:#f87171">错误：${esc(data.msg)}</div>`; term("检查失败：" + data.msg, "log-err", "dc"); return; }
    if (data.dup_count === 0) { dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | <span class="ok">无重复</span></div>`; term("重复检查完成：无重复", "log-ok", "dc"); return; }
    dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | 重复值：<span class="hl">${data.dup_count}</span></div><table><thead><tr><th>值</th><th>出现次数</th><th>行号</th></tr></thead><tbody>${data.duplicates.map((i) => `<tr><td>${esc(i.value)}</td><td>${i.count}</td><td>${i.rows.join(", ")}</td></tr>`).join("")}</tbody></table>`;
    term("重复检查完成：发现 " + data.dup_count + " 个重复值", "log-warn", "dc");
  } catch (e) { dupRes.innerHTML = `<div class="empty" style="color:#f87171">请求失败：${esc(String(e))}</div>`; term("请求失败：" + e, "log-err", "dc"); }
}

function setupTransferZone() { setupDropZone($("#tDrop"), $("#tInput"), async (files) => { await uploadTransferFiles(files, $("#tMsg")); loadTransferUI(); }); }

async function loadTransferUI() {
  const items = await loadTransferFiles();
  $("#tList").innerHTML = items.length ? items.map((i) => `<div class="tf"><span class="tname" title="${esc(i.name)}">${esc(i.name)}</span><span class="ts">${i.size}KB</span><a class="tdl" href="/transfer_download/${encodeURIComponent(i.name)}">下载</a></div>`).join("") : '<div class="empty">暂无</div>';
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
  msgList.innerHTML = m.length ? m.map((i) => `<div class="mi${i.sender === "A" ? " self" : ""}"><div class="mh"><span class="ms">${i.sender === "A" ? "我（A）" : "B 端"}</span><span><span class="mt">${esc(i.time)}</span><button class="md" onclick="delMsg(${i.id})">×</button></span></div><div class="mb">${esc(i.text)}</div></div>`).join("") : '<div class="empty">暂无消息</div>';
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

// --- stockpile database management ---
const spStatus = document.getElementById('spStatus');
const spInitDrop = document.getElementById('spInitDrop');
const spInitInput = document.getElementById('spInitInput');
const spInitBtn = document.getElementById('spInitBtn');
const spInitMsg = document.getElementById('spInitMsg');
const spCmpDrop = document.getElementById('spCmpDrop');
const spCmpInput = document.getElementById('spCmpInput');
const spCmpBtn = document.getElementById('spCmpBtn');
const spCmpRes = document.getElementById('spCmpRes');

let spInitFile = null;
let spCmpFile = null;

spInitDrop.addEventListener('click', () => spInitInput.click());
spCmpDrop.addEventListener('click', () => spCmpInput.click());

spInitDrop.addEventListener('dragover', e => { e.preventDefault(); spInitDrop.classList.add('drag'); });
spInitDrop.addEventListener('dragleave', () => spInitDrop.classList.remove('drag'));
spInitDrop.addEventListener('drop', e => {
    e.preventDefault();
    spInitDrop.classList.remove('drag');
    if (e.dataTransfer.files.length) {
        spInitInput.files = e.dataTransfer.files;
        spInitFile = e.dataTransfer.files[0];
        spInitBtn.disabled = false;
        spInitDrop.querySelector('div').textContent = spInitFile.name;
    }
});

spCmpDrop.addEventListener('dragover', e => { e.preventDefault(); spCmpDrop.classList.add('drag'); });
spCmpDrop.addEventListener('dragleave', () => spCmpDrop.classList.remove('drag'));
spCmpDrop.addEventListener('drop', e => {
    e.preventDefault();
    spCmpDrop.classList.remove('drag');
    if (e.dataTransfer.files.length) {
        spCmpInput.files = e.dataTransfer.files;
        spCmpFile = e.dataTransfer.files[0];
        spCmpBtn.disabled = false;
        spCmpDrop.querySelector('div').textContent = spCmpFile.name;
    }
});

spInitInput.addEventListener('change', () => {
    if (spInitInput.files.length) {
        spInitFile = spInitInput.files[0];
        spInitBtn.disabled = false;
        spInitDrop.querySelector('div').textContent = spInitFile.name;
    }
});

spCmpInput.addEventListener('change', () => {
    if (spCmpInput.files.length) {
        spCmpFile = spCmpInput.files[0];
        spCmpBtn.disabled = false;
        spCmpDrop.querySelector('div').textContent = spCmpFile.name;
    }
});

spInitBtn.addEventListener('click', async () => {
    if (!spInitFile) return;
    spInitBtn.disabled = true;
    spInitBtn.textContent = '导入中...';
    spInitMsg.textContent = '';

    const form = new FormData();
    form.append('files', spInitFile);

    try {
        const res = await fetch('/stockpile/init', { method: 'POST', body: form });
        const data = await res.json();
        if (data.ok) {
            spInitMsg.textContent = '导入成功，共 ' + data.count + ' 条记录';
            spInitMsg.style.color = '#2e7d32';
            refreshSpStatus();
        } else {
            spInitMsg.textContent = '导入失败：' + data.msg;
            spInitMsg.style.color = '#c62828';
        }
    } catch (e) {
        spInitMsg.textContent = '网络错误';
        spInitMsg.style.color = '#c62828';
    }
    spInitBtn.disabled = false;
    spInitBtn.textContent = '初始化';
});

spCmpBtn.addEventListener('click', async () => {
    if (!spCmpFile) return;
    spCmpBtn.disabled = true;
    spCmpBtn.textContent = '比对中...';
    spCmpRes.innerHTML = '';

    const form = new FormData();
    form.append('files', spCmpFile);

    try {
        const res = await fetch('/stockpile/compare', { method: 'POST', body: form });
        const data = await res.json();
        if (data.ok) {
            const d = data.diff;
            let html = '<b>比对结果：</b><br>';
            html += '本地记录：' + d.total_local + ' &nbsp; 导出记录：' + d.total_export + ' &nbsp; 一致：' + d.consistent + '<br>';
            if (d.only_in_local.length) html += '<span style="color:#e65100">仅本地有：' + d.only_in_local.join(', ') + '</span><br>';
            if (d.only_in_export.length) html += '<span style="color:#1565c0">仅导出有：' + d.only_in_export.join(', ') + '</span><br>';
            if (d.mismatches.length) {
                html += '<span style="color:#c62828">不一致条数：' + d.mismatches.length + '</span><br>';
                html += d.mismatches.slice(0, 5).map(m => m.barcode + ': 型号(' + m.local_model + '→' + m.export_model + ')').join('<br>');
                if (d.mismatches.length > 5) html += '<br>...等共' + d.mismatches.length + '条';
            }
            if (!d.only_in_local.length && !d.only_in_export.length && !d.mismatches.length) {
                html += '<b style="color:#2e7d32">完全一致</b>';
            }
            spCmpRes.innerHTML = html;
        } else {
            spCmpRes.innerHTML = '<span style="color:#c62828">比对失败：' + data.msg + '</span>';
        }
    } catch (e) {
        spCmpRes.innerHTML = '<span style="color:#c62828">网络错误</span>';
    }
    spCmpBtn.disabled = false;
    spCmpBtn.textContent = '比对';
});

async function refreshSpStatus() {
    try {
        const res = await fetch('/stockpile/status');
        const data = await res.json();
        if (data.initialized) {
            spStatus.textContent = '状态：已初始化，共 ' + data.count + ' 条记录';
            spStatus.style.color = '#2e7d32';
        } else {
            spStatus.textContent = '状态：未初始化，请先上传系统导出文件';
            spStatus.style.color = '#c62828';
        }
    } catch (e) {
        spStatus.textContent = '状态：检查失败';
        spStatus.style.color = '#999';
    }
}

refreshSpStatus();