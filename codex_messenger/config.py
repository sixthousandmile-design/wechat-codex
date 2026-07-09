from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _split_csv(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class RelaySettings:
    db_path: str
    worker_token: str
    allowed_senders: set[str]
    max_reply_chars: int
    job_lease_seconds: int
    whatsapp_verify_token: str
    whatsapp_app_secret: str
    whatsapp_access_token: str
    whatsapp_phone_number_id: str
    whatsapp_graph_api_base: str
    wechat_token: str
    wechat_access_token: str

    def is_sender_allowed(self, platform: str, sender: str) -> bool:
        if not self.allowed_senders:
            return False
        return (
            f"{platform}:{sender}" in self.allowed_senders
            or sender in self.allowed_senders
            or f"{platform}:*" in self.allowed_senders
        )


@dataclass(frozen=True)
class WorkerSettings:
    relay_url: str
    worker_token: str
    codex_workspace: str
    codex_command: str
    codex_timeout_seconds: int
    poll_interval_seconds: int
    worker_log_dir: str


def load_relay_settings() -> RelaySettings:
    load_dotenv()
    return RelaySettings(
        db_path=os.getenv("RELAY_DB_PATH", "relay.sqlite3"),
        worker_token=os.getenv("RELAY_WORKER_TOKEN", ""),
        allowed_senders=_split_csv(os.getenv("ALLOWED_SENDERS", "")),
        max_reply_chars=_get_int("MAX_REPLY_CHARS", 1800),
        job_lease_seconds=_get_int("JOB_LEASE_SECONDS", 3600),
        whatsapp_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
        whatsapp_app_secret=os.getenv("WHATSAPP_APP_SECRET", ""),
        whatsapp_access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
        whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        whatsapp_graph_api_base=os.getenv(
            "WHATSAPP_GRAPH_API_BASE", "https://graph.facebook.com/v23.0"
        ).rstrip("/"),
        wechat_token=os.getenv("WECHAT_TOKEN", ""),
        wechat_access_token=os.getenv("WECHAT_ACCESS_TOKEN", ""),
    )


def load_worker_settings() -> WorkerSettings:
    load_dotenv()
    return WorkerSettings(
        relay_url=os.getenv("RELAY_URL", "").rstrip("/"),
        worker_token=os.getenv("RELAY_WORKER_TOKEN", ""),
        codex_workspace=os.getenv("CODEX_WORKSPACE", ""),
        codex_command=os.getenv("CODEX_COMMAND", "codex"),
        codex_timeout_seconds=_get_int("CODEX_TIMEOUT_SECONDS", 900),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 5),
        worker_log_dir=os.getenv("WORKER_LOG_DIR", "worker_logs"),
    )
