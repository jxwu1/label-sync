import { esc, logClass, setupDropZone } from "./shared.js";
import { uploadTransferFiles, loadTransferFiles, deleteTransferFile, renderAdminTransferItems } from "./admin-transfer.js";
import { sendTextMessage, loadMessages, deleteMessage, renderAdminMessages } from "./admin-messaging.js";

(function () {
  const bar = document.getElementById("terminalBar");
  const handle = document.getElementById("terminalDragHandle");
  const toggle = document.getElementById("btnTermToggle");
  let dragging = false;
  let offsetX = 0;
  let offsetY = 0;
  let pinned = false;

  toggle.addEventListener("click", () => {
    bar.classList.toggle("hidden");
    toggle.classList.toggle("active", !bar.classList.contains("hidden"));
  });

  handle.addEventListener("mousedown", (event) => {
    if (event.target.tagName === "BUTTON") return;
    dragging = true;
    if (!pinned) {
      const rect = bar.getBoundingClientRect();
      bar.style.left = rect.left + "px";
      bar.style.bottom = "auto";
      bar.style.top = rect.top + "px";
      bar.style.transform = "none";
      pinned = true;
    }
    offsetX = event.clientX - bar.getBoundingClientRect().left;
    offsetY = event.clientY - bar.getBoundingClientRect().top;
    event.preventDefault();
  });

  document.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    bar.style.left = event.clientX - offsetX + "px";
    bar.style.top = event.clientY - offsetY + "px";
  });

  document.addEventListener("mouseup", () => { dragging = false; });
})();

const terminalBody = document.getElementById("terminalBody");
let terminalLines = [];

function termLog(text, cls) {
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  terminalLines.push({ text, cls, time: now });
  renderTerminal();
}

function renderTerminal() {
  terminalBody.innerHTML = terminalLines.map((line) =>
    `<span class="log-dim">${line.time} </span><span class="${line.cls || ""}">${esc(line.text)}</span>`
  ).join("\n");
  terminalBody.scrollTop = terminalBody.scrollHeight;
}

function clearLog() {
  terminalLines = [];
  terminalBody.innerHTML = '<span class="log-dim">日志已清空</span>';
}

const navDrawer = document.getElementById("navDrawer");
document.getElementById("btnHamburger").addEventListener("click", () => {
  navDrawer.classList.toggle("collapsed");
});

function switchPage(page) {
  document.querySelectorAll(".page").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
  document.getElementById("page" + page.charAt(0).toUpperCase() + page.slice(1)).classList.add("active");
  document.getElementById("nav" + page.charAt(0).toUpperCase() + page.slice(1)).classList.add("active");
  if (page === "stats") loadStats();
}
window.switchPage = switchPage;

const btnRun = document.getElementById("btnRun");
const statusBadge = document.getElementById("statusBadge");
const inputList = document.getElementById("inputList");
const outputList = document.getElementById("outputList");
const inputCount = document.getElementById("inputCount");
const outputCount = document.getElementById("outputCount");

let lastLogLen = 0;
let knownOutputs = new Set();
let statusKnown = "";

function fileIcon(name) {
  if (name.endsWith(".xlsx") || name.endsWith(".csv")) return "表";
  if (name.endsWith(".zip")) return "包";
  return "文";
}

function fmtDate(timestamp) {
  const date = new Date(timestamp * 1000);
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function renderInput(files) {
  inputCount.textContent = files.length;
  if (!files.length) { inputList.innerHTML = '<div class="empty">暂无文件</div>'; return; }
  inputList.innerHTML = files.map((file) => `
    <div class="file-item">
      <div class="file-left"><span class="file-icon">${fileIcon(file.name)}</span><span class="file-name" title="${file.name}">${file.name}</span></div>
      <span class="file-size">${file.size} KB</span>
    </div>`).join("");
}

function renderOutput(items) {
  const zipItems = items.filter((item) => item.is_zip);
  outputCount.textContent = zipItems.length;
  if (!items.length) { outputList.innerHTML = '<div class="empty">暂无结果</div>'; return; }
  outputList.innerHTML = items.map((file) => {
    const isNew = !knownOutputs.has(file.name) && file.is_zip;
    if (file.is_zip) knownOutputs.add(file.name);
    return `<div class="file-item">
      <div class="file-left"><span class="file-icon">${fileIcon(file.name)}</span><span class="file-name" title="${file.name}">${file.name}</span>${isNew ? '<span class="new-tag">NEW</span>' : ""}</div>
      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;"><span class="file-size" style="font-size:10px;">${fmtDate(file.mtime)}</span><span class="file-size">${file.size}KB</span>${file.is_zip ? `<a class="file-dl" href="/download_zip/${encodeURIComponent(file.name)}">下载</a>` : ""}</div>
    </div>`;
  }).join("");
}

function renderLog(lines, done) {
  if (lines.length === lastLogLen && !done) return;
  for (let i = lastLogLen; i < lines.length; i += 1) termLog(lines[i], logClass(lines[i]));
  lastLogLen = lines.length;
}

function updateStatus(status) {
  const key = status.running ? "running" : status.error ? "error" : status.done ? "done" : "idle";
  if (status.running) { statusBadge.className = "badge badge-running"; statusBadge.innerHTML = '<span class="spinner"></span>处理中'; btnRun.disabled = true; }
  else if (status.error) { statusBadge.className = "badge badge-error"; statusBadge.textContent = "出错"; btnRun.disabled = false; if (statusKnown !== "error") termLog("处理出错", "log-err"); }
  else if (status.done) { statusBadge.className = "badge badge-done"; statusBadge.textContent = "完成"; btnRun.disabled = false; if (statusKnown !== "done") termLog("处理完成", "log-ok"); }
  else { statusBadge.className = "badge badge-idle"; statusBadge.textContent = "空闲"; btnRun.disabled = false; }
  statusKnown = key;
}

async function refresh() {
  try {
    const response = await fetch("/files");
    const data = await response.json();
    renderInput(data.input);
    renderOutput(data.output);
    updateStatus(data.status);
    renderLog(data.status.log, data.status.done);
  } catch (error) { console.error("Refresh failed:", error); }
}

btnRun.addEventListener("click", async () => {
  btnRun.disabled = true; lastLogLen = 0; statusKnown = "";
  termLog("开始处理...", "");
  try {
    const response = await fetch("/run", { method: "POST" });
    const data = await response.json();
    if (!data.ok) { termLog("启动失败：" + data.msg, "log-err"); alert(data.msg); btnRun.disabled = false; }
  } catch (error) { btnRun.disabled = false; console.error("Run failed:", error); }
});

async function loadStats() {
  try {
    const response = await fetch("/stats");
    const data = await response.json();
    const container = document.getElementById("statsContainer");
    if (!data.length) { container.innerHTML = '<div style="color:#4a5568;font-size:13px;">暂无数据</div>'; return; }
    container.innerHTML = data.map((month) => {
      const max = Math.max(...month.employees.map((e) => e.count), 1);
      const columns = month.employees.map((e) => `<div class="bar-col"><span class="bar-count">${e.count}</span><div class="bar-fill" style="height:${Math.max(4, Math.round((e.count / max) * 120))}px"></div></div>`).join("");
      const names = month.employees.map((e) => `<div class="bar-name">${e.name}</div>`).join("");
      return `<div class="month-block"><div class="month-label">${month.month}</div><div class="bar-chart">${columns}</div><div class="bar-names">${names}</div></div>`;
    }).join("");
  } catch (error) { console.error("Stats failed:", error); }
}

const transferFileList = document.getElementById("transferFileList");
const transferMsg = document.getElementById("transferMsg");

setupDropZone(document.getElementById("bDropZone"), document.getElementById("bFileInput"), (files) => {
  uploadTransferFiles(files, transferMsg).then(() => loadTransfer());
});

async function loadTransfer() {
  const items = await loadTransferFiles();
  transferFileList.innerHTML = renderAdminTransferItems(items);
}

async function deleteTransfer(filename) {
  await deleteTransferFile(filename);
  loadTransfer();
}
window.deleteTransfer = deleteTransfer;

const textInput = document.getElementById("textInput");
const btnTextSend = document.getElementById("btnTextSend");
const btnTextCopy = document.getElementById("btnTextCopy");
const textMsgList = document.getElementById("textMsgList");

btnTextCopy.addEventListener("click", () => {
  if (!textInput.value) return;
  navigator.clipboard.writeText(textInput.value).then(() => {
    btnTextCopy.textContent = "已复制"; btnTextCopy.classList.add("copied");
    setTimeout(() => { btnTextCopy.textContent = "复制"; btnTextCopy.classList.remove("copied"); }, 1500);
  });
});

btnTextSend.addEventListener("click", sendText);
textInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) sendText(); });

async function sendText() {
  const text = textInput.value.trim();
  if (!text) return;
  btnTextSend.disabled = true;
  try {
    const data = await sendTextMessage(text, "B");
    if (data.ok) { textInput.value = ""; loadTextMsgs(); }
  } catch (error) { console.error("Send text failed:", error); }
  btnTextSend.disabled = false;
}

async function loadTextMsgs() {
  const messages = await loadMessages();
  if (!messages.length) { textMsgList.innerHTML = '<div class="t-empty">暂无消息</div>'; return; }
  textMsgList.innerHTML = renderAdminMessages(messages, "B");
}

async function deleteTextMsg(id) {
  await deleteMessage(id);
  loadTextMsgs();
}
window.deleteTextMsg = deleteTextMsg;

termLog("控制台已就绪", "log-dim");
refresh();
loadStats();
loadTransfer();
loadTextMsgs();
setInterval(refresh, 2000);
setInterval(loadStats, 10000);
setInterval(loadTransfer, 5000);
setInterval(loadTextMsgs, 5000);