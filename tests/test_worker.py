from __future__ import annotations

from codex_messenger.config import WorkerSettings
from worker import build_codex_args, extract_final_message, resolve_codex_command, run_codex_job


def settings() -> WorkerSettings:
    return WorkerSettings(
        relay_url="https://relay.example",
        worker_token="token",
        codex_workspace=r"C:\work",
        codex_command="codex",
        codex_timeout_seconds=10,
        poll_interval_seconds=1,
        worker_log_dir="logs",
    )


def test_build_read_only_codex_args() -> None:
    job = {"command": "ask", "prompt": "hello", "run_mode": "read-only"}
    args = build_codex_args(settings(), job)
    assert "--sandbox" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in args
    assert "--json" in args


def test_build_workspace_write_codex_args() -> None:
    job = {"command": "run", "prompt": "make README", "run_mode": "workspace-write"}
    args = build_codex_args(settings(), job)
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert args[args.index("--ask-for-approval") + 1] == "never"
    assert args.index("--ask-for-approval") < args.index("exec")


def test_extract_final_message_from_jsonl() -> None:
    stdout = '{"type":"event","message":"first"}\n{"type":"event","message":"final"}\n'
    assert extract_final_message(stdout, "") == "final"


def test_resolve_existing_codex_path(tmp_path) -> None:
    fake_codex = tmp_path / "codex.exe"
    fake_codex.write_text("", encoding="utf-8")
    assert resolve_codex_command(str(fake_codex)) == str(fake_codex)


def test_missing_codex_command_fails_job_without_crashing(tmp_path) -> None:
    bad_settings = WorkerSettings(
        relay_url="https://relay.example",
        worker_token="token",
        codex_workspace=str(tmp_path),
        codex_command=str(tmp_path / "missing-codex.exe"),
        codex_timeout_seconds=1,
        poll_interval_seconds=1,
        worker_log_dir=str(tmp_path / "logs"),
    )
    result = run_codex_job(
        bad_settings,
        {"id": "job_test", "command": "ask", "prompt": "hello", "run_mode": "read-only"},
    )
    assert result["state"] == "failed"
    assert "Failed to start Codex command" in result["error"]
