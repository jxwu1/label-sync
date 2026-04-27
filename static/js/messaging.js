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
  const selfClass = selfSender === "A" ? "is-self" : "from-self";
  return messages
    .map((message) => {
      const isSelf = message.sender === selfSender;
      return `<div class="message${isSelf ? " " + selfClass : ""}"><div class="message__head"><span class="message__source">${isSelf ? selfLabel : otherLabel}</span><span><span class="message__time">${esc(message.time)}</span><button class="message__del" onclick="delMsg(${message.id})">×</button></span></div><div class="message__body">${esc(message.text)}</div></div>`;
    })
    .join("");
}