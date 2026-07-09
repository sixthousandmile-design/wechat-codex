from __future__ import annotations

from .models import CommandResult, InboundMessage
from .storage import JobStore
from .text import help_text, truncate_text


def _split_command(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped:
        return "", ""
    parts = stripped.split(maxsplit=1)
    command = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return command, rest


def _first_token_without_chat_punctuation(text: str) -> str:
    if not text:
        return ""
    return text.split()[0].strip(".,;:!?，。；：！？")


def handle_message(store: JobStore, message: InboundMessage, max_reply_chars: int) -> CommandResult:
    command, rest = _split_command(message.text)

    if command == "ask" and rest:
        job = store.create_job(
            message=message,
            command="ask",
            prompt=rest,
            run_mode="read-only",
            state="queued",
        )
        return CommandResult(f"Queued read-only Codex job {job['id']}.", job["id"])

    if command == "plan" and rest:
        job = store.create_job(
            message=message,
            command="plan",
            prompt=rest,
            run_mode="read-only",
            state="queued",
        )
        return CommandResult(f"Queued read-only planning job {job['id']}.", job["id"])

    if command == "run" and rest:
        job = store.create_job(
            message=message,
            command="run",
            prompt=rest,
            run_mode="workspace-write",
            state="pending_approval",
        )
        return CommandResult(
            f"Created pending job {job['id']}.\nReply: approve {job['id']}",
            job["id"],
        )

    if command == "approve" and rest:
        job_id = _first_token_without_chat_punctuation(rest)
        ok, reason, job = store.approve_job(job_id, message.platform, message.sender)
        if ok and reason == "approved":
            return CommandResult(f"Approved {job_id}; queued for local Codex worker.", job_id)
        if ok and reason == "already_queued":
            return CommandResult(f"{job_id} is already queued.", job_id)
        if reason == "not_found":
            return CommandResult(f"Job {job_id} was not found.")
        if reason == "sender_mismatch":
            return CommandResult(f"Job {job_id} can only be approved by its original sender.")
        state = job["state"] if job else reason
        return CommandResult(f"Job {job_id} cannot be approved from state: {state}.", job_id)

    if command == "status" and rest:
        job_id = _first_token_without_chat_punctuation(rest)
        job = store.get_job(job_id)
        if job is None:
            return CommandResult(f"Job {job_id} was not found.")
        if job["platform"] != message.platform or job["sender"] != message.sender:
            return CommandResult(f"Job {job_id} is not visible to this sender.")
        summary = store.job_summary(job)
        return CommandResult(truncate_text(summary, max_reply_chars), job_id)

    job = store.create_job(
        message=message,
        command="unknown",
        prompt=message.text.strip(),
        run_mode="none",
        state="rejected",
    )
    return CommandResult(f"Rejected {job['id']}: unknown command.\n{help_text()}", job["id"])
