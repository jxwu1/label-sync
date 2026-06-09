export function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// 历史命名兼容：各页面 module 里原本各自定义的 escapeHtml 统一指到 esc
export { esc as escapeHtml };

export const byId = (id) => document.getElementById(id);

export const qs = (selector) => document.querySelector(selector);

export function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

export function jesc(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

export async function copyToClip(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

export function setupDropZone(dropEl, inputEl, onFiles) {
  const addActive = () => dropEl.classList.add("drag", "drag-over");
  const removeActive = () => dropEl.classList.remove("drag", "drag-over");
  dropEl.addEventListener("click", () => inputEl.click());
  dropEl.addEventListener("dragenter", (event) => {
    event.preventDefault();
    addActive();
  });
  dropEl.addEventListener("dragover", (event) => {
    event.preventDefault();
    addActive();
  });
  dropEl.addEventListener("dragleave", (event) => {
    // dragleave 进子元素时也会触发，只在真正离开 dropEl 时清状态
    if (event.relatedTarget && dropEl.contains(event.relatedTarget)) return;
    removeActive();
  });
  dropEl.addEventListener("drop", (event) => {
    event.preventDefault();
    removeActive();
    if (onFiles) onFiles(event.dataTransfer.files);
  });
  inputEl.addEventListener("change", () => {
    if (onFiles) onFiles(inputEl.files);
    inputEl.value = "";
  });
}

export function logClass(text) {
  if (/错误|Error|失败/.test(text)) return "log-err";
  if (/警告|异常|\[条码异常\]|\[库位格式异常\]|等待/.test(text)) return "log-warn";
  if (/完成|成功/.test(text)) return "log-ok";
  return "";
}

// 统一 fetch 封装：永不 throw，始终 resolve 成对象。
// - 后端约定返回 {ok: bool, msg?: string, ...}，原样透传
// - 网络错误 / 超时 / 非 JSON 响应 → 归一为 {ok: false, msg: "..."}
// - opts.json 提供时自动 POST + JSON.stringify；opts.timeout 默认 30s
export async function apiFetch(url, options = {}) {
  const { timeout = 30000, json, ...rest } = options;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const opts = { ...rest, signal: ctrl.signal };
    if (json !== undefined) {
      opts.method = opts.method || "POST";
      opts.headers = { "Content-Type": "application/json", ...opts.headers };
      opts.body = JSON.stringify(json);
    }
    const resp = await fetch(url, opts);
    let data = null;
    try {
      data = await resp.json();
    } catch {
      return { ok: false, msg: `服务器返回异常（HTTP ${resp.status}）` };
    }
    if (data === null || typeof data !== "object") {
      return { ok: false, msg: `服务器返回异常（HTTP ${resp.status}）` };
    }
    // 部分端点（如 /status）不带 ok 字段，按 HTTP 状态补齐
    if (data.ok === undefined) data.ok = resp.ok;
    return data;
  } catch (err) {
    return { ok: false, msg: err.name === "AbortError" ? "请求超时，请重试" : `网络错误：${err.message}` };
  } finally {
    clearTimeout(timer);
  }
}

export async function postJSON(url, data) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return response.json();
}