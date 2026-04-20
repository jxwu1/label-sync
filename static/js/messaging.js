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
    return [];
  }
}

export async function deleteMessage(id) {
  try {
    await postJSON("/text_delete", { id });
    return true;
  } catch (error) {
    return false;
  }
}

export function renderMessages(messages, selfSender = "A") {
  if (!messages || !messages.length) {
    return '<div class="empty">暂无消息</div>';
  }
  const selfLabel = selfSender === "A" ? "我（A）" : "我（B）";
  const otherLabel = selfSender === "A" ? "B 端" : "A 端";
  const selfClass = selfSender === "A" ? "self" : "from-self";
  return messages
    .map((message) => {
      const isSelf = message.sender === selfSender;
      return `<div class="mi${isSelf ? " " + selfClass : ""}"><div class="mh"><span class="ms">${isSelf ? selfLabel : otherLabel}</span><span><span class="mt">${esc(message.time)}</span><button class="md" onclick="delMsg(${message.id})">×</button></span></div><div class="mb">${esc(message.text)}</div></div>`;
    })
    .join("");
}