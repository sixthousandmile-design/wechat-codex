from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .models import InboundMessage, JobRow


def utc_now() -> float:
    return time.time()


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:12]}"


class JobStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = Path(db_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inbound_messages (
                    platform TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (platform, message_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    command TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    run_mode TEXT NOT NULL,
                    state TEXT NOT NULL,
                    platform_message_id TEXT,
                    result TEXT,
                    error TEXT,
                    stdout TEXT,
                    stderr TEXT,
                    log_path TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    approved_at REAL,
                    started_at REAL,
                    finished_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_platform_message
                ON jobs(platform, platform_message_id)
                WHERE platform_message_id IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_state_created
                ON jobs(state, created_at)
                """
            )

    def record_inbound(self, message: InboundMessage) -> bool:
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO inbound_messages(platform, message_id, sender, text, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        message.platform,
                        message.message_id,
                        message.sender,
                        message.text,
                        utc_now(),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def create_job(
        self,
        message: InboundMessage,
        command: str,
        prompt: str,
        run_mode: str,
        state: str,
    ) -> JobRow:
        now = utc_now()
        job_id = new_job_id()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    id, platform, sender, command, prompt, run_mode, state,
                    platform_message_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    message.platform,
                    message.sender,
                    command,
                    prompt,
                    run_mode,
                    state,
                    message.message_id,
                    now,
                    now,
                ),
            )
            return self.get_job(job_id, conn=conn)  # type: ignore[return-value]

    def get_job(self, job_id: str, conn: sqlite3.Connection | None = None) -> JobRow | None:
        owns_conn = conn is None
        conn = conn or self.connect()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None
        finally:
            if owns_conn:
                conn.close()

    def approve_job(self, job_id: str, platform: str, sender: str) -> tuple[bool, str, JobRow | None]:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return False, "not_found", None
            job = dict(row)
            if job["platform"] != platform or job["sender"] != sender:
                return False, "sender_mismatch", job
            if job["state"] == "queued":
                return True, "already_queued", job
            if job["state"] != "pending_approval":
                return False, f"state_{job['state']}", job
            conn.execute(
                """
                UPDATE jobs
                SET state = 'queued', approved_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, job_id),
            )
            return True, "approved", self.get_job(job_id, conn=conn)

    def reject_job(self, job_id: str, reason: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET state = 'rejected', error = ?, updated_at = ? WHERE id = ?",
                (reason, now, job_id),
            )

    def reset_stale_running(self, lease_seconds: int) -> None:
        cutoff = utc_now() - lease_seconds
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET state = 'queued', error = 'Worker lease expired; requeued.', updated_at = ?
                WHERE state = 'running' AND updated_at < ?
                """,
                (utc_now(), cutoff),
            )

    def claim_next_job(self, lease_seconds: int) -> JobRow | None:
        self.reset_stale_running(lease_seconds)
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE state = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            job_id = row["id"]
            conn.execute(
                """
                UPDATE jobs
                SET state = 'running', started_at = ?, updated_at = ?
                WHERE id = ? AND state = 'queued'
                """,
                (now, now, job_id),
            )
            conn.commit()
            return self.get_job(job_id)
        finally:
            conn.close()

    def complete_job(
        self,
        job_id: str,
        state: str,
        result: str,
        error: str = "",
        stdout: str = "",
        stderr: str = "",
        log_path: str = "",
    ) -> JobRow | None:
        if state not in {"succeeded", "failed"}:
            raise ValueError("state must be succeeded or failed")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET state = ?, result = ?, error = ?, stdout = ?, stderr = ?,
                    log_path = ?, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (state, result, error, stdout, stderr, log_path, now, now, job_id),
            )
            return self.get_job(job_id, conn=conn)

    def job_summary(self, job: JobRow) -> str:
        result = job.get("result") or job.get("error") or ""
        return (
            f"{job['id']}: {job['state']}\n"
            f"command: {job['command']}\n"
            f"prompt: {job['prompt']}\n"
            f"{result}"
        ).strip()

    def as_public_job(self, job: JobRow) -> dict[str, Any]:
        return {
            "id": job["id"],
            "platform": job["platform"],
            "sender": job["sender"],
            "command": job["command"],
            "prompt": job["prompt"],
            "run_mode": job["run_mode"],
            "state": job["state"],
            "result": job.get("result"),
            "error": job.get("error"),
            "log_path": job.get("log_path"),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }
