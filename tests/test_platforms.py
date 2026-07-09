from __future__ import annotations

import hashlib
import hmac

from codex_messenger.platforms import (
    parse_wechat_message,
    parse_whatsapp_messages,
    verify_wechat_signature,
    verify_whatsapp_signature,
)


def test_whatsapp_signature_verification() -> None:
    body = b'{"hello":"world"}'
    secret = "secret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_whatsapp_signature(body, signature, secret)
    assert not verify_whatsapp_signature(body + b"x", signature, secret)


def test_parse_whatsapp_text_message() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "123"},
                            "messages": [
                                {
                                    "from": "15551234567",
                                    "id": "wamid.1",
                                    "type": "text",
                                    "text": {"body": "ask hello"},
                                },
                                {"from": "1555", "id": "wamid.2", "type": "image"},
                            ],
                        }
                    }
                ]
            }
        ]
    }
    messages = parse_whatsapp_messages(payload)
    assert len(messages) == 1
    assert messages[0].sender == "15551234567"
    assert messages[0].message_id == "wamid.1"
    assert messages[0].text == "ask hello"


def test_wechat_signature_verification() -> None:
    token = "token"
    timestamp = "123"
    nonce = "abc"
    raw = "".join(sorted([token, timestamp, nonce]))
    signature = hashlib.sha1(raw.encode()).hexdigest()
    assert verify_wechat_signature(token, signature, timestamp, nonce)
    assert not verify_wechat_signature(token, "bad", timestamp, nonce)


def test_parse_wechat_text_message() -> None:
    body = b"""
    <xml>
      <ToUserName><![CDATA[toUser]]></ToUserName>
      <FromUserName><![CDATA[fromUser]]></FromUserName>
      <CreateTime>1348831860</CreateTime>
      <MsgType><![CDATA[text]]></MsgType>
      <Content><![CDATA[run make README]]></Content>
      <MsgId>1234567890123456</MsgId>
    </xml>
    """
    message = parse_wechat_message(body)
    assert message is not None
    assert message.platform == "wechat"
    assert message.sender == "fromUser"
    assert message.recipient == "toUser"
    assert message.text == "run make README"
    assert message.message_id == "1234567890123456"
