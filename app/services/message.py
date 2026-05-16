from datetime import datetime

from app.schemas import ServiceResult
from app.state import message_store


def send_text_message(text: str, sender: str) -> dict:
    message = message_store.add(
        text=text,
        sender=sender,
        current_time=datetime.now().strftime("%H:%M:%S"),
    )
    return {"ok": True, "msg": message.to_dict()}


def list_text_messages() -> list[dict]:
    return message_store.list()


def delete_text_message(message_id) -> ServiceResult:
    if not message_store.delete(message_id):
        return ServiceResult(ok=False, payload={"msg": "消息不存在"}, status_code=404)
    return ServiceResult(ok=True)


def clear_text_messages() -> dict:
    message_store.clear()
    return {"ok": True}
