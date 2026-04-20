import { esc } from "./shared.js";
import { postJSON } from "./shared.js";

export async function sendTextMessage(text, sender) {
  return postJSON("/text_send", { text, sender });
}

export async function loadMessages() {
  try {
    const response = await fetch("/text_list");
    return await response.json();
  } catch (error) {
    console.error("Load messages failed:", error);
    return [];
  }
}

export async function deleteMessage(id) {
  try {
    await postJSON("/text_delete", { id });
    return true;
  } catch (error) {
    console.error("Delete message failed:", error);
    return false;
  }
}

export function renderAdminMessages(messages, selfSender = "B") {
  if (!messages || !messages.length) return '<div class="t-empty">暂无消息</div>';
  const selfLabel = selfSender === "A" ? "我（A）" : "我（B）";
  const otherLabel = selfSender === "A" ? "B 端" : "A 端";
  const selfClass = selfSender === "A" ? "self" : "from-self";
  return messages.map((message) => `
    <div class="msg-item${message.sender === selfSender ? " " + selfClass : ""}">
      <div class="msg-header">
        <span class="msg-sender">${message.sender === selfSender ? selfLabel : otherLabel}</span>
        <span><span class="msg-time">${esc(message.time)}</span><button class="btn-mdel" onclick="deleteTextMsg(${message.id})">×</button></span>
      </div>
      <div class="msg-body">${esc(message.text)}</div>
    </div>`).join("");
}