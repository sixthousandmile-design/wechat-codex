from __future__ import annotations

from pathlib import Path

from codex_messenger.commands import handle_message
from codex_messenger.models import InboundMessage
from codex_messenger.storage import JobStore


def make_store(tmp_path: Path) -> JobStore:
    return JobStore(str(tmp_path / "relay.sqlite3"))


def make_message(text: str, message_id: str = "m1") -> InboundMessage:
    return InboundMessage(
        platform="whatsapp",
        sender="15551234567",
        message_id=message_id,
        text=text,
    )


def test_duplicate_inbound_is_detected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    message = make_message("ask hello")
    assert store.record_inbound(message)
    assert not store.record_inbound(message)


def test_ask_creates_queued_read_only_job(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = handle_message(store, make_message("ask what is here?"), max_reply_chars=500)
    assert result.job_id is not None
    job = store.get_job(result.job_id)
    assert job is not None
    assert job["state"] == "queued"
    assert job["run_mode"] == "read-only"
    assert job["command"] == "ask"


def test_run_requires_later_approval(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = handle_message(store, make_message("run create README"), max_reply_chars=500)
    assert result.job_id is not None
    job = store.get_job(result.job_id)
    assert job is not None
    assert job["state"] == "pending_approval"
    approve = handle_message(
        store,
        make_message(f"approve {result.job_id}", message_id="m2"),
        max_reply_chars=500,
    )
    assert "Approved" in approve.reply_text
    job = store.get_job(result.job_id)
    assert job is not None
    assert job["state"] == "queued"


def test_status_is_sender_scoped(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = handle_message(store, make_message("ask hello"), max_reply_chars=500)
    other_sender = InboundMessage(
        platform="whatsapp",
        sender="999",
        message_id="m2",
        text=f"status {result.job_id}",
    )
    status = handle_message(store, other_sender, max_reply_chars=500)
    assert "not visible" in status.reply_text


def test_status_accepts_trailing_chat_punctuation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = handle_message(store, make_message("ask hello"), max_reply_chars=500)
    assert result.job_id is not None
    completed = store.complete_job(result.job_id, "succeeded", "hello from codex")
    assert completed is not None

    status = handle_message(
        store,
        make_message(f"status {result.job_id}.", message_id="m2"),
        max_reply_chars=500,
    )
    assert "hello from codex" in status.reply_text


def test_claim_and_complete_job(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = handle_message(store, make_message("ask hello"), max_reply_chars=500)
    claimed = store.claim_next_job(lease_seconds=3600)
    assert claimed is not None
    assert claimed["id"] == result.job_id
    assert claimed["state"] == "running"
    completed = store.complete_job(claimed["id"], "succeeded", "done")
    assert completed is not None
    assert completed["state"] == "succeeded"
    assert completed["result"] == "done"
