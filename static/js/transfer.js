import { esc } from "./shared.js";

export async function uploadTransferFiles(files, msgEl) {
  if (!files.length) return;
  const formData = new FormData();
  [...files].forEach((file) => formData.append("files", file));
  if (msgEl) {
    msgEl.style.color = "#60a5fa";
    msgEl.textContent = "上传中...";
  }
  try {
    const response = await fetch("/transfer_upload", { method: "POST", body: formData });
    const data = await response.json();
    if (data.ok) {
      if (msgEl) {
        msgEl.style.color = "#4ade80";
        msgEl.textContent = `已发送 ${data.saved.length} 个文件`;
      }
      return data.saved;
    }
    if (msgEl) {
      msgEl.style.color = "#f87171";
      msgEl.textContent = "发送失败：" + (data.msg || "");
    }
    return null;
  } catch (error) {
    if (msgEl) {
      msgEl.style.color = "#f87171";
      msgEl.textContent = "发送失败";
    }
    return null;
  } finally {
    if (msgEl) {
      setTimeout(() => { msgEl.textContent = ""; }, 3000);
    }
  }
}

export async function loadTransferFiles() {
  try {
    const response = await fetch("/transfer_list");
    return await response.json();
  } catch (error) {
    return [];
  }
}

export async function deleteTransferFile(filename) {
  try {
    const response = await fetch("/transfer_delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    const data = await response.json();
    return data.ok;
  } catch (error) {
    return false;
  }
}

export function renderTransferItems(items, options = {}) {
  const { showDelete = true, cssClass = { file: "tf", name: "tname", size: "ts", download: "tdl", delete: "tdel" } } = options;
  if (!items || !items.length) {
    return `<div class="empty">暂无</div>`;
  }
  return items
    .map((item) => {
      const deleteBtn = showDelete
        ? `<button class="${cssClass.delete}" onclick="deleteTransfer('${item.name}')">删除</button>`
        : "";
      return `<div class="${cssClass.file}"><span class="${cssClass.name}" title="${esc(item.name)}">${esc(item.name)}</span><span class="${cssClass.size}">${item.size}KB</span><a class="${cssClass.download}" href="/transfer_download/${encodeURIComponent(item.name)}">下载</a>${deleteBtn}</div>`;
    })
    .join("");
}