from __future__ import annotations

import asyncio

from codex_messenger.config import RelaySettings
from codex_messenger.outbound import get_wechat_access_token


def relay_settings(**overrides) -> RelaySettings:
    values = {
        "db_path": "relay.sqlite3",
        "worker_token": "worker",
        "allowed_senders": {"wechat:*"},
        "max_reply_chars": 1800,
        "job_lease_seconds": 3600,
        "whatsapp_verify_token": "",
        "whatsapp_app_secret": "",
        "whatsapp_access_token": "",
        "whatsapp_phone_number_id": "",
        "whatsapp_graph_api_base": "https://graph.facebook.com/v23.0",
        "wechat_token": "wechat-token",
        "wechat_access_token": "",
        "wechat_app_id": "",
        "wechat_app_secret": "",
        "wechat_api_base": "https://api.weixin.qq.com",
    }
    values.update(overrides)
    return RelaySettings(**values)


def test_manual_wechat_access_token_is_used() -> None:
    token = asyncio.run(get_wechat_access_token(relay_settings(wechat_access_token="manual-token")))
    assert token == "manual-token"


def test_missing_wechat_credentials_returns_empty_token() -> None:
    token = asyncio.run(get_wechat_access_token(relay_settings()))
    assert token == ""
