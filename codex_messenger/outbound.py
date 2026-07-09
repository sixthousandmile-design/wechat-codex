from __future__ import annotations

import logging

import httpx

from .config import RelaySettings
from .models import JobRow
from .text import truncate_text

logger = logging.getLogger(__name__)


async def send_platform_reply(settings: RelaySettings, job: JobRow, text: str) -> bool:
    body = truncate_text(text, settings.max_reply_chars)
    platform = job["platform"]
    if platform == "whatsapp":
        return await send_whatsapp_reply(settings, job["sender"], body)
    if platform == "wechat":
        return await send_wechat_custom_reply(settings, job["sender"], body)
    logger.warning("No reply adapter for platform %s", platform)
    return False


async def send_whatsapp_reply(settings: RelaySettings, recipient: str, text: str) -> bool:
    if not (
        settings.whatsapp_access_token
        and settings.whatsapp_phone_number_id
        and settings.whatsapp_graph_api_base
    ):
        logger.warning("WhatsApp reply skipped; access token or phone number ID is not configured")
        return False

    url = f"{settings.whatsapp_graph_api_base}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("WhatsApp reply failed: %s", exc)
        return False


async def send_wechat_custom_reply(settings: RelaySettings, openid: str, text: str) -> bool:
    if not settings.wechat_access_token:
        logger.info("WeChat async reply skipped; WECHAT_ACCESS_TOKEN is not configured")
        return False

    url = (
        "https://api.weixin.qq.com/cgi-bin/message/custom/send"
        f"?access_token={settings.wechat_access_token}"
    )
    payload = {"touser": openid, "msgtype": "text", "text": {"content": text}}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("WeChat custom reply failed: %s", exc)
        return False
