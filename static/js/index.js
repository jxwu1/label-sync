const $ = (selector) => document.querySelector(selector);
const esc = (value) =>
  String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
const jesc = (value) => String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");

async function copyToClip(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

const badge = $("#badge");
const status = $("#status");
const warnBox = $("#warnBox");
const filesBox = $("#files");
const upload = $("#upload");
const run = $("#run");
const cont = $("#cont");
const download = $("#download");
const copyModels = $("#copyModels");
const copyModelsAll = $("#copyModelsAll");
const reset = $("#reset");
const fileInput = $("#fileInput");
const tbod = $("#tbod");

let selected = [];
let poll = null;
let lastLog = 0;
let logs = [];
let page = "main";

function switchPage(nextPage) {
  page = nextPage;
  $("#pageMain").classList.toggle("active", nextPage === "main");
  $("#pageDup").classList.toggle("active", nextPage === "dup");
  $("#navMain").classList.toggle("active", nextPage === "main");
  $("#navDup").classList.toggle("active", nextPage === "dup");
}
window.switchPage = switchPage;

$("#hamb").onclick = () => $("#nav").classList.toggle("hide");

function setBadge(type, text) {
  badge.className = "badge badge-" + type;
  badge.textContent = text;
}

function setStatus(text, extraClass = "") {
  status.innerHTML = text;
  status.className = "status" + (extraClass ? " " + extraClass : "");
}

function logCls(text) {
  if (text.includes("[错误]") || text.includes("失败")) {
    return "log-err";
  }
  if (text.includes("[条码异常]") || text.includes("[库位格式异常]") || text.includes("等待")) {
    return "log-warn";
  }
  if (text.includes("完成") || text.includes("成功")) {
    return "log-ok";
  }
  return "";
}

function term(text, cls = "", src = "lp") {
  logs.push({ text, cls, src });
  renderLog();
}

function renderLog() {
  tbod.innerHTML = logs.length
    ? logs
        .map(
          (item) =>
            `<div class="${item.src === "dc" ? "log-dc" : "log-lp"} ${item.cls}">${esc(item.text)}</div>`,
        )
        .join("")
    : '<span class="log-dim">等待操作</span>';
  tbod.scrollTop = tbod.scrollHeight;
}

function clearLog() {
  logs = [];
  renderLog();
}
window.clearLog = clearLog;

function renderFiles() {
  filesBox.innerHTML = selected
    .map(
      (file, index) =>
        `<div class="file"><span class="name">${esc(file.name)}</span><span class="rm" onclick="rmFile(${index})">×</span></div>`,
    )
    .join("");
  upload.disabled = !selected.length;
}

function rmFile(index) {
  selected.splice(index, 1);
  renderFiles();
}
window.rmFile = rmFile;

function addFiles(fileList) {
  selected.push(...[...fileList]);
  renderFiles();
}

const drop = $("#drop");
drop.onclick = () => fileInput.click();
drop.addEventListener("dragover", (event) => {
  event.preventDefault();
  drop.classList.add("drag");
});
drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  drop.classList.remove("drag");
  addFiles(event.dataTransfer.files);
});
fileInput.onchange = () => {
  addFiles(fileInput.files);
  fileInput.value = "";
};

upload.onclick = async () => {
  if (!selected.length) {
    return;
  }
  upload.disabled = true;
  setStatus('<span class="spin"></span>正在上传文件...');
  try {
    const formData = new FormData();
    selected.forEach((file) => formData.append("files", file));
    const response = await fetch("/upload", { method: "POST", body: formData });
    const data = await response.json();
    if (!data.ok) {
      setStatus("上传失败：" + data.msg, "error");
      term("上传失败：" + data.msg, "log-err");
      upload.disabled = false;
      return;
    }
    setStatus("上传成功，共 " + data.saved.length + " 个文件", "success");
    term("上传完成：" + data.saved.join(", "), "log-ok");
    run.disabled = false;
  } catch (error) {
    setStatus("上传失败：" + error, "error");
    term("上传失败：" + error, "log-err");
    upload.disabled = false;
  }
};

run.onclick = async () => {
  run.disabled = true;
  cont.style.display = "none";
  download.style.display = "none";
  copyModels.style.display = "none";
  copyModelsAll.style.display = "none";
  reset.style.display = "none";
  warnBox.innerHTML = '<div class="empty">处理中，等待检测结果...</div>';
  setBadge("running", "处理中");
  setStatus('<span class="spin"></span>正在启动处理流程...');
  term("开始处理");
  try {
    const response = await fetch("/run", { method: "POST" });
    const data = await response.json();
    if (!data.ok) {
      setStatus(data.msg, "error");
      setBadge("error", "出错");
      term("启动失败：" + data.msg, "log-err");
      run.disabled = false;
      return;
    }
    startPoll();
  } catch (error) {
    setStatus("启动失败：" + error, "error");
    setBadge("error", "出错");
    term("启动失败：" + error, "log-err");
    run.disabled = false;
  }
};

function waitMsg(stage) {
  if (stage === "anomaly" || stage === "phase1_barcode") {
    return "发现异常条码，请校正、删除或忽略后继续处理";
  }
  if (stage === "location_format" || stage === "phase1_location") {
    return "发现库位格式异常，请手工校正后继续处理";
  }
  if (stage === "new_barcodes" || stage === "phase2_review" || stage === "phase2") {
    return "发现数据异常，请处理后继续";
  }
  return "任务等待人工处理";
}

function renderBarcodes(items) {
  if (!items.length) {
    return '<div class="empty">暂无异常条码</div>';
  }
  return items
    .map((warning, index) => {
      if (warning.deleted) {
        return `<div class="warn"><div class="row"><div class="col"><span class="code" style="text-decoration:line-through;opacity:.45">${esc(warning.barcode)}</span></div><span class="tag-del">已删除</span></div></div>`;
      }
      if (warning.corrected) {
        return `<div class="warn"><div class="row"><div class="col"><span class="code" style="text-decoration:line-through;opacity:.45">${esc(warning.barcode)}</span></div><span class="tag-ok">已校正为 ${esc(warning.new_barcode || "")}</span></div></div>`;
      }
      return `<div class="warn" id="bc_${index}"><div class="row"><div class="col"><span class="code">${esc(warning.barcode)}</span><span class="sub">长度 ${warning.length} 位，正常长度 ${warning.normal} 位</span></div><div class="actions"><button class="btn-s bc" onclick="showBc(${index})">校正</button><button class="btn-s bd" onclick="delBc('${jesc(warning.barcode)}',${index})">删除</button><button class="btn-s bi" onclick="ignoreBc(${index})">忽略</button></div></div><div class="form" id="bcf_${index}"><input id="bci_${index}" placeholder="输入正确条码"><button class="btn-s bf" onclick="submitBc('${jesc(warning.barcode)}',${index})">确认</button><button class="btn-s cx" onclick="hideBc(${index})">取消</button></div></div>`;
    })
    .join("");
}

function renderLocs(items) {
  if (!items.length) {
    return '<div class="empty">暂无库位异常</div>';
  }
  return items
    .map((warning, index) => {
      if (warning.corrected) {
        return `<div class="warn"><div class="row"><div class="col"><span class="code loc" style="text-decoration:line-through;opacity:.45">${esc(warning.location)}</span></div><span class="tag-ok">已校正为 ${esc(warning.new_location || "")}</span></div></div>`;
      }
      return `<div class="warn"><div class="row"><div class="col"><span class="code loc">${esc(warning.location)}</span><span class="sub">库位格式不符合要求，请手工校正</span></div><div class="actions"><button class="btn-s bc" onclick="showLoc(${index})">校正库位</button></div></div><div class="form" id="lf_${index}"><input id="li_${index}" placeholder="输入正确库位，例如 A01"><button class="btn-s bf" onclick="submitLoc('${jesc(warning.location)}',${index})">确认</button><button class="btn-s cx" onclick="hideLoc(${index})">取消</button></div></div>`;
    })
    .join("");
}

function renderNew(items) {
  if (!items.length) {
    return "";
  }
  return '<div class="warn"><div class="col"><span class="sub">以下条码未在 stockpile 中找到，请确认后继续：</span></div></div>' +
    items
      .map(
        (barcode) =>
          `<div class="warn"><div class="row"><div class="col"><span class="code">${esc(barcode)}</span></div></div></div>`,
      )
      .join("");
}

function parseP2WFromLog(log) {
  return (log || [])
    .filter((text) => text.startsWith("[PHASE2_WARNING]"))
    .map((text) => {
      const match = text.match(/^\[PHASE2_WARNING\] (\S+) (.+)$/);
      if (!match) {
        return null;
      }
      const barcode = match[1];
      const reason = match[2];
      const locations = reason.match(/'([^']+)'/g) || [];
      return {
        barcode,
        reason,
        locations: locations.map((item) => item.replace(/'/g, "")),
        resolved: false,
        resolution: null,
      };
    })
    .filter(Boolean);
}

const p2DupSel = {};
const p2DupFixed = {};

function parseDupLoc(reason) {
  if (!reason.includes("duplicate_locations")) {
    return null;
  }
  const storeMatch = reason.match(/store=\[([^\]]*)\]/);
  const warehouseMatch = reason.match(/warehouse=\[([^\]]*)\]/);
  return {
    stores: storeMatch ? storeMatch[1].split(",").filter(Boolean) : [],
    warehouses: warehouseMatch ? warehouseMatch[1].split(",").filter(Boolean) : [],
  };
}

function pickDupLoc(barcode, type, loc) {
  if (!p2DupSel[barcode]) {
    p2DupSel[barcode] = { store: null, warehouse: null };
  }
  p2DupSel[barcode][type] = loc;
  const key = barcode.replace(/\W/g, "_");
  document.querySelectorAll(".dpbtn-" + type + "-" + key).forEach((button) => {
    button.style.background = button.dataset.loc === loc ? "#c2410c" : "transparent";
    button.style.color = button.dataset.loc === loc ? "#fff" : "#fb923c";
  });
  const fixed = p2DupFixed[barcode] || {};
  const selectedItem = p2DupSel[barcode];
  if (fixed.dupBoth) {
    if (selectedItem.store && selectedItem.warehouse) {
      const confirmButton = document.getElementById("dpconf_" + key);
      if (confirmButton) {
        confirmButton.disabled = false;
      }
    }
  } else {
    resolveEx(
      barcode,
      [selectedItem.store || fixed.store, selectedItem.warehouse || fixed.warehouse]
        .filter(Boolean)
        .join("/"),
    );
  }
}
window.pickDupLoc = pickDupLoc;

function confirmDupLoc(barcode) {
  const selectedItem = p2DupSel[barcode] || {};
  const fixed = p2DupFixed[barcode] || {};
  resolveEx(
    barcode,
    [selectedItem.store || fixed.store, selectedItem.warehouse || fixed.warehouse]
      .filter(Boolean)
      .join("/"),
  );
}
window.confirmDupLoc = confirmDupLoc;

function renderDupCard(warning, dup) {
  const { stores, warehouses } = dup;
  const dupBoth = stores.length > 1 && warehouses.length > 1;
  const barcode = warning.barcode;
  const key = barcode.replace(/\W/g, "_");
  p2DupFixed[barcode] = {
    store: stores.length === 1 ? stores[0] : null,
    warehouse: warehouses.length === 1 ? warehouses[0] : null,
    dupBoth,
  };
  const selectedItem = p2DupSel[barcode] || {};
  const mkBtn = (type, loc) => {
    const selected = selectedItem[type] === loc;
    return `<button class="btn-s bc dpbtn-${type}-${key}" data-loc="${esc(loc)}" style="${selected ? "background:#c2410c;color:#fff" : ""}" onclick="pickDupLoc('${jesc(barcode)}','${type}','${jesc(loc)}')">${esc(loc)}</button>`;
  };
  let html = `<div class="warn"><div class="row"><div class="col"><span class="code">${esc(barcode)}</span><span class="sub" style="color:#fbbf24">扫描到多个库位冲突</span></div></div><div class="col" style="gap:8px;margin-top:8px">`;
  if (stores.length === 1) {
    html += `<span class="sub">店面：<span class="loc">${esc(stores[0])}</span> <span style="color:#4a5568">（自动保留）</span></span>`;
  } else if (stores.length > 1) {
    html += `<div><div class="sub" style="margin-bottom:4px">选择店面库位：</div><div class="actions">${stores.map((loc) => mkBtn("store", loc)).join("")}</div></div>`;
  }
  if (warehouses.length === 1) {
    html += `<span class="sub">仓库：<span class="loc">${esc(warehouses[0])}</span> <span style="color:#4a5568">（自动保留）</span></span>`;
  } else if (warehouses.length > 1) {
    html += `<div><div class="sub" style="margin-bottom:4px">选择仓库库位：</div><div class="actions">${warehouses.map((loc) => mkBtn("warehouse", loc)).join("")}</div></div>`;
  }
  html += `</div><div class="actions" style="margin-top:8px">${dupBoth ? `<button class="btn-s bf" id="dpconf_${key}" disabled onclick="confirmDupLoc('${jesc(barcode)}')">确认选择</button>` : ""}<button class="btn-s bd" onclick="resolveEx('${jesc(barcode)}','ignore')">忽略</button></div></div>`;
  return html;
}

function renderP2Warnings(items) {
  if (!items.length) {
    return "";
  }
  return '<div class="warn"><div class="col"><span class="sub" style="color:#f87171">以下条码存在数据异常，请选择处理方式后继续：</span></div></div>' +
    items
      .map((warning) => {
        if (warning.resolved) {
          return `<div class="warn"><div class="row"><div class="col"><span class="code" style="text-decoration:line-through;opacity:.45">${esc(warning.barcode)}</span><span class="sub">${esc(warning.reason)}</span></div><span class="${warning.resolution === "ignore" ? "tag-del" : "tag-ok"}">${warning.resolution === "ignore" ? "已忽略" : "已选 " + esc(warning.resolution)}</span></div></div>`;
        }
        const dup = parseDupLoc(warning.reason);
        if (dup) {
          return renderDupCard(warning, dup);
        }
        return `<div class="warn"><div class="row"><div class="col"><span class="code">${esc(warning.barcode)}</span><span class="sub">${esc(warning.reason)}</span></div><div class="actions">${(warning.locations || []).map((loc) => `<button class="btn-s bc" onclick="resolveEx('${jesc(warning.barcode)}','${jesc(loc)}')">选 ${esc(loc)}</button>`).join("")}<button class="btn-s bd" onclick="resolveEx('${jesc(warning.barcode)}','ignore')">忽略</button></div></div></div>`;
      })
      .join("");
}

function renderReview(data) {
  if (data.waiting_stage === "anomaly" || data.waiting_stage === "phase1_barcode") {
    warnBox.innerHTML = renderBarcodes(data.barcode_warnings || []);
    return;
  }
  if (data.waiting_stage === "location_format" || data.waiting_stage === "phase1_location") {
    warnBox.innerHTML = renderLocs(data.location_warnings || []);
    return;
  }
  if (data.waiting_stage === "phase2_review" || data.waiting_stage === "new_barcodes" || data.waiting_stage === "phase2") {
    const phase2Warnings =
      data.phase2_warnings && data.phase2_warnings.length
        ? data.phase2_warnings
        : parseP2WFromLog(data.log);
    const html = renderNew(data.new_barcodes || []) + renderP2Warnings(phase2Warnings);
    warnBox.innerHTML = html || '<div class="empty">等待确认后继续</div>';
    return;
  }
  if ((data.barcode_warnings || []).length) {
    warnBox.innerHTML = renderBarcodes(data.barcode_warnings);
    return;
  }
  if ((data.location_warnings || []).length) {
    warnBox.innerHTML = renderLocs(data.location_warnings);
    return;
  }
  if ((data.new_barcodes || []).length) {
    warnBox.innerHTML = renderNew(data.new_barcodes);
    return;
  }
  warnBox.innerHTML = '<div class="empty">暂无需要人工处理的异常</div>';
}

function showBc(index) {
  $("#bcf_" + index).style.display = "flex";
  $("#bci_" + index).focus();
}

function hideBc(index) {
  $("#bcf_" + index).style.display = "none";
}

function showLoc(index) {
  $("#lf_" + index).style.display = "flex";
  $("#li_" + index).focus();
}

function hideLoc(index) {
  $("#lf_" + index).style.display = "none";
}

function ignoreBc(index) {
  const element = $("#bc_" + index);
  if (!element) {
    return;
  }
  element.style.opacity = ".35";
  element.style.pointerEvents = "none";
  term("已忽略异常条码条目 #" + (index + 1));
}
window.showBc = showBc;
window.hideBc = hideBc;
window.showLoc = showLoc;
window.hideLoc = hideLoc;
window.ignoreBc = ignoreBc;

async function reloadStatus() {
  const response = await fetch("/status");
  const data = await response.json();
  renderReview(data);
  return data;
}

async function resolveEx(barcode, resolution) {
  try {
    const response = await fetch("/resolve_exception", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ barcode, resolution }),
    });
    const data = await response.json();
    if (!data.ok) {
      alert("操作失败：" + data.msg);
      return;
    }
    term(
      resolution === "ignore" ? `已忽略条码：${barcode}` : `条码 ${barcode} 使用库位 ${resolution}`,
      "log-ok",
    );
    await reloadStatus();
  } catch (error) {
    alert("请求失败：" + error);
  }
}
window.resolveEx = resolveEx;

async function delBc(barcode, index) {
  const button = document.querySelector(`#bc_${index} .bd`);
  button.disabled = true;
  button.textContent = "删除中...";
  try {
    const response = await fetch("/delete_barcode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ barcode }),
    });
    const data = await response.json();
    if (!data.ok) {
      alert("删除失败：" + data.msg);
      button.disabled = false;
      button.textContent = "删除";
      return;
    }
    term("已删除条码：" + barcode, "log-warn");
    await reloadStatus();
  } catch (error) {
    alert("请求失败：" + error);
    button.disabled = false;
    button.textContent = "删除";
  }
}
window.delBc = delBc;

async function submitBc(oldBarcode, index) {
  const input = $("#bci_" + index);
  const newBarcode = input.value.trim();
  if (!newBarcode) {
    input.focus();
    return;
  }
  const button = document.querySelector(`#bcf_${index} .bf`);
  button.disabled = true;
  button.textContent = "提交中...";
  try {
    const response = await fetch("/correct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_barcode: oldBarcode, new_barcode: newBarcode }),
    });
    const data = await response.json();
    if (!data.ok) {
      alert("校正失败：" + data.msg);
      button.disabled = false;
      button.textContent = "确认";
      return;
    }
    term("条码校正：" + oldBarcode + " -> " + newBarcode, "log-ok");
    await reloadStatus();
  } catch (error) {
    alert("请求失败：" + error);
    button.disabled = false;
    button.textContent = "确认";
  }
}
window.submitBc = submitBc;

async function submitLoc(oldLocation, index) {
  const input = $("#li_" + index);
  const newLocation = input.value.trim();
  if (!newLocation) {
    input.focus();
    return;
  }
  const button = document.querySelector(`#lf_${index} .bf`);
  button.disabled = true;
  button.textContent = "提交中...";
  try {
    const response = await fetch("/correct_location", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_location: oldLocation, new_location: newLocation }),
    });
    const data = await response.json();
    if (!data.ok) {
      alert("校正失败：" + data.msg);
      button.disabled = false;
      button.textContent = "确认";
      return;
    }
    term("库位校正：" + oldLocation + " -> " + newLocation, "log-ok");
    await reloadStatus();
  } catch (error) {
    alert("请求失败：" + error);
    button.disabled = false;
    button.textContent = "确认";
  }
}
window.submitLoc = submitLoc;

function handleStatus(data) {
  if (data.log && data.log.length > lastLog) {
    for (let index = lastLog; index < data.log.length; index += 1) {
      term(data.log[index], logCls(data.log[index]));
    }
    lastLog = data.log.length;
  }
  renderReview(data);
  if (data.waiting) {
    clearInterval(poll);
    setBadge("waiting", "等待处理");
    setStatus(waitMsg(data.waiting_stage));
    cont.style.display = "block";
    cont.disabled = false;
    cont.textContent = "继续处理";
    term(waitMsg(data.waiting_stage), "log-warn");
    return;
  }
  if (data.running) {
    setBadge("running", "处理中");
    setStatus('<span class="spin"></span>处理中，请稍候...');
    return;
  }
  clearInterval(poll);
  cont.style.display = "none";
  if (data.error) {
    setStatus("处理失败，请查看日志", "error");
    setBadge("error", "出错");
    run.disabled = false;
    return;
  }
  if (data.done) {
    setStatus("处理完成，可下载结果", "success");
    setBadge("done", "完成");
    download.style.display = "block";
    copyModels.style.display = "block";
    copyModelsAll.style.display = "block";
    reset.style.display = "block";
    return;
  }
  setBadge("idle", "空闲");
}

function startPoll() {
  clearInterval(poll);
  poll = setInterval(async () => {
    try {
      const response = await fetch("/status");
      const data = await response.json();
      handleStatus(data);
    } catch (error) {}
  }, 1000);
}

cont.onclick = async () => {
  cont.disabled = true;
  cont.textContent = "处理中...";
  setBadge("running", "处理中");
  setStatus('<span class="spin"></span>继续处理中...');
  term("继续处理");
  try {
    const response = await fetch("/continue", { method: "POST" });
    const data = await response.json();
    if (!data.ok) {
      setBadge("waiting", "等待处理");
      setStatus(data.msg, "error");
      cont.disabled = false;
      cont.textContent = "继续处理";
      term("继续失败：" + data.msg, "log-err");
      return;
    }
    startPoll();
  } catch (error) {
    setStatus("请求失败：" + error, "error");
    cont.disabled = false;
    cont.textContent = "继续处理";
    term("请求失败：" + error, "log-err");
  }
};

download.onclick = () => {
  location.href = "/download";
  term("下载结果文件");
};

reset.onclick = () => {
  selected = [];
  filesBox.innerHTML = "";
  fileInput.value = "";
  upload.disabled = true;
  run.disabled = true;
  cont.style.display = "none";
  cont.disabled = false;
  cont.textContent = "继续处理";
  download.style.display = "none";
  copyModels.style.display = "none";
  copyModelsAll.style.display = "none";
  reset.style.display = "none";
  warnBox.innerHTML = '<div class="empty">暂无需要人工处理的异常</div>';
  setBadge("idle", "空闲");
  setStatus("请先上传文件");
  clearInterval(poll);
  lastLog = 0;
  term("已清空界面，准备下一批", "log-dim");
};

copyModels.onclick = async () => {
  copyModels.disabled = true;
  copyModels.textContent = "复制中...";
  try {
    const response = await fetch("/models");
    const data = await response.json();
    if (!data.ok) {
      alert("获取失败：" + data.msg);
      copyModels.disabled = false;
      copyModels.textContent = "复制所有型号";
      return;
    }
    const uniqueModels = [...new Set(data.models)];
    await copyToClip(uniqueModels.join("\n"));
    term("已复制 " + uniqueModels.length + " 个型号（去重）", "log-ok");
    copyModels.textContent = "已复制 " + uniqueModels.length + " 个型号";
    setTimeout(() => {
      copyModels.textContent = "复制所有型号";
      copyModels.disabled = false;
    }, 2500);
  } catch (error) {
    alert("复制失败：" + error);
    copyModels.textContent = "复制所有型号";
    copyModels.disabled = false;
  }
};

copyModelsAll.onclick = async () => {
  copyModelsAll.disabled = true;
  copyModelsAll.textContent = "复制中...";
  try {
    const response = await fetch("/models");
    const data = await response.json();
    if (!data.ok) {
      alert("获取失败：" + data.msg);
      copyModelsAll.disabled = false;
      copyModelsAll.textContent = "复制所有型号（含重复）";
      return;
    }
    await copyToClip(data.models.join("\n"));
    term("已复制 " + data.models.length + " 个型号（含重复）", "log-ok");
    copyModelsAll.textContent = "已复制 " + data.models.length + " 个型号";
    setTimeout(() => {
      copyModelsAll.textContent = "复制所有型号（含重复）";
      copyModelsAll.disabled = false;
    }, 2500);
  } catch (error) {
    alert("复制失败：" + error);
    copyModelsAll.textContent = "复制所有型号（含重复）";
    copyModelsAll.disabled = false;
  }
};

const dupDrop = $("#dupDrop");
const dupInput = $("#dupInput");
const dupRes = $("#dupRes");
dupDrop.onclick = () => dupInput.click();
dupDrop.addEventListener("dragover", (event) => {
  event.preventDefault();
  dupDrop.classList.add("drag");
});
dupDrop.addEventListener("dragleave", () => dupDrop.classList.remove("drag"));
dupDrop.addEventListener("drop", (event) => {
  event.preventDefault();
  dupDrop.classList.remove("drag");
  if (event.dataTransfer.files[0]) {
    runDup(event.dataTransfer.files[0]);
  }
});
dupInput.onchange = () => {
  if (dupInput.files[0]) {
    runDup(dupInput.files[0]);
  }
  dupInput.value = "";
};

async function runDup(file) {
  dupRes.innerHTML = '<div class="empty"><span class="spin"></span>检查中...</div>';
  term("开始重复检查：" + file.name, "", "dc");
  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await fetch("/check_dup", { method: "POST", body: formData });
    const data = await response.json();
    if (!data.ok) {
      dupRes.innerHTML = `<div class="empty" style="color:#f87171">错误：${esc(data.msg)}</div>`;
      term("检查失败：" + data.msg, "log-err", "dc");
      return;
    }
    if (data.dup_count === 0) {
      dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | <span class="ok">无重复</span></div>`;
      term("重复检查完成：无重复", "log-ok", "dc");
      return;
    }
    dupRes.innerHTML = `<div class="sum">列名：<b>${esc(data.column)}</b> | 总条数：<b>${data.total}</b> | 重复值：<span class="hl">${data.dup_count}</span></div><table><thead><tr><th>值</th><th>出现次数</th><th>行号</th></tr></thead><tbody>${data.duplicates.map((item) => `<tr><td>${esc(item.value)}</td><td>${item.count}</td><td>${item.rows.join(", ")}</td></tr>`).join("")}</tbody></table>`;
    term("重复检查完成：发现 " + data.dup_count + " 个重复值", "log-warn", "dc");
  } catch (error) {
    dupRes.innerHTML = `<div class="empty" style="color:#f87171">请求失败：${esc(String(error))}</div>`;
    term("请求失败：" + error, "log-err", "dc");
  }
}

const tDrop = $("#tDrop");
const tInput = $("#tInput");
const tMsg = $("#tMsg");
const tList = $("#tList");
tDrop.onclick = () => tInput.click();
tDrop.addEventListener("dragover", (event) => {
  event.preventDefault();
  tDrop.classList.add("drag");
});
tDrop.addEventListener("dragleave", () => tDrop.classList.remove("drag"));
tDrop.addEventListener("drop", (event) => {
  event.preventDefault();
  tDrop.classList.remove("drag");
  sendTransfer(event.dataTransfer.files);
});
tInput.onchange = () => {
  sendTransfer(tInput.files);
  tInput.value = "";
};

async function sendTransfer(files) {
  if (!files.length) {
    return;
  }
  const formData = new FormData();
  [...files].forEach((file) => formData.append("files", file));
  tMsg.style.color = "#60a5fa";
  tMsg.textContent = "上传中...";
  try {
    const response = await fetch("/transfer_upload", { method: "POST", body: formData });
    const data = await response.json();
    if (!data.ok) {
      tMsg.style.color = "#f87171";
      tMsg.textContent = "发送失败：" + data.msg;
      return;
    }
    tMsg.style.color = "#4ade80";
    tMsg.textContent = "已发送 " + data.saved.length + " 个文件";
    loadTransfer();
  } catch (error) {
    tMsg.style.color = "#f87171";
    tMsg.textContent = "发送失败";
  }
  setTimeout(() => {
    tMsg.textContent = "";
  }, 3000);
}

async function loadTransfer() {
  try {
    const response = await fetch("/transfer_list");
    const items = await response.json();
    tList.innerHTML = items.length
      ? items
          .map(
            (item) =>
              `<div class="tf"><span class="tname" title="${esc(item.name)}">${esc(item.name)}</span><span class="ts">${item.size}KB</span><a class="tdl" href="/transfer_download/${encodeURIComponent(item.name)}">下载</a></div>`,
          )
          .join("")
      : '<div class="empty">暂无</div>';
  } catch (error) {}
}

const textInput = $("#textInput");
const copyText = $("#copyText");
const sendText = $("#sendText");
const msgList = $("#msgList");

copyText.onclick = async () => {
  if (!textInput.value) {
    return;
  }
  await copyToClip(textInput.value);
  copyText.textContent = "已复制";
  copyText.classList.add("copied");
  setTimeout(() => {
    copyText.textContent = "复制";
    copyText.classList.remove("copied");
  }, 1500);
};

sendText.onclick = sendMsg;
textInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    sendMsg();
  }
});

async function sendMsg() {
  const text = textInput.value.trim();
  if (!text) {
    return;
  }
  sendText.disabled = true;
  try {
    const response = await fetch("/text_send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, sender: "A" }),
    });
    const data = await response.json();
    if (data.ok) {
      textInput.value = "";
      loadMsgs();
    }
  } catch (error) {}
  sendText.disabled = false;
}

async function loadMsgs() {
  try {
    const response = await fetch("/text_list");
    const messages = await response.json();
    msgList.innerHTML = messages.length
      ? messages
          .map(
            (message) =>
              `<div class="mi${message.sender === "A" ? " self" : ""}"><div class="mh"><span class="ms">${message.sender === "A" ? "我（A）" : "B 端"}</span><span><span class="mt">${esc(message.time)}</span><button class="md" onclick="delMsg(${message.id})">×</button></span></div><div class="mb">${esc(message.text)}</div></div>`,
          )
          .join("")
      : '<div class="empty">暂无消息</div>';
  } catch (error) {}
}

async function delMsg(id) {
  try {
    await fetch("/text_delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    loadMsgs();
  } catch (error) {}
}
window.delMsg = delMsg;

async function restore() {
  try {
    const response = await fetch("/status");
    const data = await response.json();
    if (data.log && data.log.length) {
      logs = data.log.map((text) => ({ text, cls: logCls(text), src: "lp" }));
      renderLog();
      lastLog = data.log.length;
    }
    handleStatus(data);
    if (data.running) {
      startPoll();
    }
  } catch (error) {}
}

loadTransfer();
loadMsgs();
restore();
setInterval(loadTransfer, 5000);
setInterval(loadMsgs, 5000);
