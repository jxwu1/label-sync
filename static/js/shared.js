export function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

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

export async function postJSON(url, data) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return response.json();
}