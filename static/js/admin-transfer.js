import { esc } from "./shared.js";

export async function uploadTransferFiles(files, msgEl) {
  if (!files.length) return null;
  const formData = new FormData();
  [...files].forEach((file) => formData.append("files", file));
  if (msgEl) { msgEl.style.color = "#60a5fa"; msgEl.textContent = "上传中..."; }
  try {
    const response = await fetch("/transfer_upload", { method: "POST", body: formData });
    const data = await response.json();
    if (data.ok) {
      if (msgEl) { msgEl.style.color = "#4ade80"; msgEl.textContent = `已发送 ${data.saved.length} 个文件`; }
      return data.saved;
    }
    if (msgEl) { msgEl.style.color = "#f87171"; msgEl.textContent = "发送失败：" + (data.msg || ""); }
    return null;
  } catch (error) {
    if (msgEl) { msgEl.style.color = "#f87171"; msgEl.textContent = "发送失败"; }
    console.error("Transfer upload failed:", error);
    return null;
  } finally {
    if (msgEl) { setTimeout(() => { msgEl.textContent = ""; }, 3000); }
  }
}

export async function loadTransferFiles() {
  try {
    const response = await fetch("/transfer_list");
    return await response.json();
  } catch (error) {
    console.error("Transfer list failed:", error);
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
    console.error("Transfer delete failed:", error);
    return false;
  }
}

export function renderAdminTransferItems(items) {
  if (!items || !items.length) return '<div class="t-empty">暂无</div>';
  return items.map((file) => `
    <div class="t-file-item">
      <span class="t-file-name" title="${esc(file.name)}">${esc(file.name)}</span>
      <span class="t-file-size">${file.size}KB</span>
      <div class="t-actions">
        <a class="btn-tdl" href="/transfer_download/${encodeURIComponent(file.name)}">下载</a>
        <button class="btn-tdel" onclick="deleteTransfer('${file.name}')">删除</button>
      </div>
    </div>`).join("");
}