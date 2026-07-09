from __future__ import annotations

import hashlib
import hmac
import time
import xml.etree.ElementTree as ET
from html import escape
from typing import Any

from .models import InboundMessage


def verify_whatsapp_signature(body: bytes, header_value: str | None, app_secret: str) -> bool:
    if not app_secret or not header_value:
        return False
    if not header_value.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    supplied = header_value.split("=", 1)[1]
    return hmac.compare_digest(expected, supplied)


def parse_whatsapp_messages(payload: dict[str, Any]) -> list[InboundMessage]:
    messages: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for item in value.get("messages", []) or []:
                if item.get("type") != "text":
                    continue
                text = (item.get("text") or {}).get("body", "")
                sender = item.get("from", "")
                message_id = item.get("id", "")
                if sender and message_id and text:
                    messages.append(
                        InboundMessage(
                            platform="whatsapp",
                            sender=sender,
                            message_id=message_id,
                            text=text,
                            recipient=(value.get("metadata") or {}).get("phone_number_id"),
                        )
                    )
    return messages


def compute_wechat_signature(token: str, timestamp: str, nonce: str) -> str:
    joined = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def verify_wechat_signature(
    token: str, signature: str | None, timestamp: str | None, nonce: str | None
) -> bool:
    if not token or not signature or not timestamp or not nonce:
        return False
    expected = compute_wechat_signature(token, timestamp, nonce)
    return hmac.compare_digest(expected, signature)


def _xml_text(root: ET.Element, name: str) -> str:
    item = root.find(name)
    return item.text if item is not None and item.text is not None else ""


def parse_wechat_message(body: bytes) -> InboundMessage | None:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None

    msg_type = _xml_text(root, "MsgType")
    if msg_type != "text":
        return None

    sender = _xml_text(root, "FromUserName")
    recipient = _xml_text(root, "ToUserName")
    content = _xml_text(root, "Content")
    message_id = _xml_text(root, "MsgId") or f"{sender}:{_xml_text(root, 'CreateTime')}:{content}"
    if not sender or not recipient or not content:
        return None

    return InboundMessage(
        platform="wechat",
        sender=sender,
        message_id=message_id,
        text=content,
        recipient=recipient,
    )


def build_wechat_text_reply(message: InboundMessage, text: str) -> str:
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{escape(message.sender)}]]></ToUserName>"
        f"<FromUserName><![CDATA[{escape(message.recipient or '')}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{escape(text)}]]></Content>"
        "</xml>"
    )
