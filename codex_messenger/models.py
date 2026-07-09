from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    platform: str
    sender: str
    message_id: str
    text: str
    recipient: str | None = None


@dataclass(frozen=True)
class CommandResult:
    reply_text: str
    job_id: str | None = None


JobRow = dict[str, Any]
