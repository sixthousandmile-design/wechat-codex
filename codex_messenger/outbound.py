from __future__ import annotations

import logging
import time

import httpx

from .config import RelaySettings
from .models import JobRow
from .text import truncate_text

logger = logging.getLogger(__name__)

_wechat_cached_token: str = ""
_wechat_cached_token_expires_at: float = 0.0
_wechat_last_token_result: dict[str, object] = {"ok": False, "reason": "not_requested"}
_wechat_last_send_result: dict[str, object] = {"ok": False, "reason": "not_sent"}


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
    global _wechat_last_send_result

    access_token = await get_wechat_access_token(settings)
    if not access_token:
        logger.info(
            "WeChat async reply skipped; configure WECHAT_ACCESS_TOKEN or WECHAT_APP_ID/WECHAT_APP_SECRET"
        )
        _wechat_last_send_result = {"ok": False, "reason": "no_access_token"}
        return False

    url = (
        f"{settings.wechat_api_base}/cgi-bin/message/custom/send"
        f"?access_token={access_token}"
    )
    payload = {"touser": openid, "msgtype": "text", "text": {"content": text}}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("errcode", 0) != 0:
                logger.warning("WeChat custom reply failed: %s", data)
                _wechat_last_send_result = {"ok": False, "reason": "api_error", **data}
                return False
        _wechat_last_send_result = {"ok": True, "reason": "sent"}
        return True
    except httpx.HTTPError as exc:
        logger.warning("WeChat custom reply failed: %s", exc)
        _wechat_last_send_result = {"ok": False, "reason": "http_error", "error": str(exc)}
        return False


async def get_wechat_access_token(settings: RelaySettings) -> str:
    global _wechat_cached_token, _wechat_cached_token_expires_at, _wechat_last_token_result

    if settings.wechat_access_token:
        _wechat_last_token_result = {"ok": True, "source": "manual"}
        return settings.wechat_access_token

    now = time.time()
    if _wechat_cached_token and now < _wechat_cached_token_expires_at:
        _wechat_last_token_result = {"ok": True, "source": "cache"}
        return _wechat_cached_token

    if not (settings.wechat_app_id and settings.wechat_app_secret):
        _wechat_last_token_result = {"ok": False, "reason": "missing_credentials"}
        return ""

    url = f"{settings.wechat_api_base}/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("WeChat access_token fetch failed: %s", exc)
        _wechat_last_token_result = {"ok": False, "reason": "http_error", "error": str(exc)}
        return ""

    token = data.get("access_token")
    if not token:
        logger.warning("WeChat access_token response did not include token: %s", data)
        _wechat_last_token_result = {"ok": False, "reason": "api_error", **data}
        return ""

    expires_in = int(data.get("expires_in", 7200))
    _wechat_cached_token = token
    _wechat_cached_token_expires_at = now + max(60, expires_in - 300)
    _wechat_last_token_result = {
        "ok": True,
        "source": "app_credentials",
        "expires_in": expires_in,
    }
    return _wechat_cached_token


def get_wechat_diagnostics(settings: RelaySettings) -> dict[str, object]:
    return {
        "configured": bool(
            settings.wechat_access_token or (settings.wechat_app_id and settings.wechat_app_secret)
        ),
        "has_manual_access_token": bool(settings.wechat_access_token),
        "has_app_id": bool(settings.wechat_app_id),
        "has_app_secret": bool(settings.wechat_app_secret),
        "api_base": settings.wechat_api_base,
        "token_result": _wechat_last_token_result,
        "last_send_result": _wechat_last_send_result,
    }
