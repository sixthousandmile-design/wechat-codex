from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel

from codex_messenger.commands import handle_message
from codex_messenger.config import RelaySettings, load_relay_settings
from codex_messenger.models import InboundMessage
from codex_messenger.outbound import send_platform_reply, send_whatsapp_reply
from codex_messenger.platforms import (
    build_wechat_text_reply,
    parse_wechat_message,
    parse_whatsapp_messages,
    verify_wechat_signature,
    verify_whatsapp_signature,
)
from codex_messenger.storage import JobStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = load_relay_settings()
store = JobStore(settings.db_path)
app = FastAPI(title="Messaging-to-Codex Relay")


class CompletionPayload(BaseModel):
    state: str
    result: str = ""
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    log_path: str = ""


def require_worker(
    authorization: Annotated[str | None, Header()] = None,
    x_worker_token: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.worker_token:
        raise HTTPException(status_code=503, detail="RELAY_WORKER_TOKEN is not configured")
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    elif x_worker_token:
        token = x_worker_token
    if token != settings.worker_token:
        raise HTTPException(status_code=401, detail="invalid worker token")


async def process_inbound(message: InboundMessage) -> str | None:
    if not settings.is_sender_allowed(message.platform, message.sender):
        logger.warning("Rejected sender %s:%s", message.platform, message.sender)
        return None
    if not store.record_inbound(message):
        logger.info("Duplicate inbound message ignored: %s:%s", message.platform, message.message_id)
        return None
    result = handle_message(store, message, settings.max_reply_chars)
    return result.reply_text


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/webhook/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and hub_verify_token == settings.whatsapp_verify_token
        and hub_challenge is not None
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="invalid WhatsApp webhook verification")


@app.post("/webhook/whatsapp")
async def receive_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, str]:
    body = await request.body()
    if not verify_whatsapp_signature(body, x_hub_signature_256, settings.whatsapp_app_secret):
        raise HTTPException(status_code=403, detail="invalid WhatsApp signature")

    payload = json.loads(body.decode("utf-8"))
    messages = parse_whatsapp_messages(payload)
    for message in messages:
        reply = await process_inbound(message)
        if reply:
            await send_whatsapp_reply(settings, message.sender, reply)
    return {"status": "ok"}


@app.get("/webhook/wechat")
def verify_wechat_webhook(
    signature: str | None = None,
    timestamp: str | None = None,
    nonce: str | None = None,
    echostr: str | None = None,
) -> Response:
    if verify_wechat_signature(settings.wechat_token, signature, timestamp, nonce) and echostr:
        return Response(content=echostr, media_type="text/plain")
    raise HTTPException(status_code=403, detail="invalid WeChat webhook verification")


@app.post("/webhook/wechat")
async def receive_wechat_webhook(
    request: Request,
    signature: str | None = None,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> Response:
    if not verify_wechat_signature(settings.wechat_token, signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="invalid WeChat signature")

    message = parse_wechat_message(await request.body())
    if message is None:
        return Response(content="success", media_type="text/plain")

    reply = await process_inbound(message)
    if not reply:
        return Response(content="success", media_type="text/plain")
    return Response(content=build_wechat_text_reply(message, reply), media_type="application/xml")


@app.get("/worker/jobs/next", dependencies=[Depends(require_worker)])
def next_job():
    job = store.claim_next_job(settings.job_lease_seconds)
    if job is None:
        return Response(status_code=204)
    return store.as_public_job(job)


@app.get("/worker/jobs/{job_id}", dependencies=[Depends(require_worker)])
def get_worker_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return store.as_public_job(job)


@app.post("/worker/jobs/{job_id}/complete", dependencies=[Depends(require_worker)])
async def complete_worker_job(job_id: str, payload: CompletionPayload) -> dict:
    job = store.complete_job(
        job_id=job_id,
        state=payload.state,
        result=payload.result,
        error=payload.error,
        stdout=payload.stdout,
        stderr=payload.stderr,
        log_path=payload.log_path,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    if payload.state == "succeeded":
        reply = f"{job_id} succeeded.\n{payload.result}"
    else:
        reply = f"{job_id} failed.\n{payload.error or payload.result}"
    await send_platform_reply(settings, job, reply)
    return store.as_public_job(job)
