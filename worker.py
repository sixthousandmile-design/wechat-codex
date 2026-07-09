from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from codex_messenger.config import WorkerSettings, load_worker_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def resolve_codex_command(command: str) -> str:
    command = command.strip().strip('"')
    path_candidate = Path(command).expanduser()
    if path_candidate.exists():
        return str(path_candidate)
    if path_candidate.parent != Path("."):
        return command

    path_match = shutil.which(command)
    if path_match:
        return path_match

    extension_matches = sorted(
        Path.home().glob(".vscode/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if extension_matches:
        return str(extension_matches[0])

    return command


def build_prompt(job: dict[str, Any]) -> str:
    command = job["command"]
    prompt = job["prompt"]
    if command == "ask":
        return (
            "Remote read-only question. Inspect files only if useful; do not edit files.\n\n"
            f"{prompt}"
        )
    if command == "plan":
        return (
            "Create an implementation plan only. Do not edit files or run mutating commands.\n\n"
            f"{prompt}"
        )
    return f"Approved remote request. Carry out the task in this workspace.\n\n{prompt}"


def build_codex_args(settings: WorkerSettings, job: dict[str, Any]) -> list[str]:
    sandbox = "read-only" if job["run_mode"] == "read-only" else "workspace-write"
    return [
        resolve_codex_command(settings.codex_command),
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        settings.codex_workspace,
        "--skip-git-repo-check",
        "--json",
        "--sandbox",
        sandbox,
        build_prompt(job),
    ]


def extract_final_message(stdout: str, stderr: str) -> str:
    candidates: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("message", "content", "text", "msg"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        item = event.get("item")
        if isinstance(item, dict):
            for key in ("message", "content", "text"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
    if candidates:
        return candidates[-1]
    combined = (stdout.strip() or stderr.strip()).strip()
    return combined[-4000:] if combined else "Codex finished without a text result."


def write_log(settings: WorkerSettings, job: dict[str, Any], data: dict[str, Any]) -> str:
    log_dir = Path(settings.worker_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{job['id']}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def run_codex_job(settings: WorkerSettings, job: dict[str, Any]) -> dict[str, str]:
    args = build_codex_args(settings, job)
    log_data: dict[str, Any] = {
        "job": job,
        "args": args[:-1] + ["<prompt>"],
        "prompt": args[-1],
        "started_at": time.time(),
    }
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=settings.codex_timeout_seconds,
        )
        log_data.update(
            {
                "finished_at": time.time(),
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        result = extract_final_message(completed.stdout, completed.stderr)
        log_path = write_log(settings, job, log_data)
        if completed.returncode == 0:
            return {
                "state": "succeeded",
                "result": result,
                "error": "",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "log_path": log_path,
            }
        return {
            "state": "failed",
            "result": result,
            "error": completed.stderr.strip() or f"codex exited with {completed.returncode}",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "log_path": log_path,
        }
    except subprocess.TimeoutExpired as exc:
        log_data.update(
            {
                "finished_at": time.time(),
                "timeout": settings.codex_timeout_seconds,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }
        )
        log_path = write_log(settings, job, log_data)
        return {
            "state": "failed",
            "result": "",
            "error": f"codex timed out after {settings.codex_timeout_seconds} seconds",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "log_path": log_path,
        }
    except OSError as exc:
        message = (
            f"Failed to start Codex command '{settings.codex_command}': {exc}. "
            "Set CODEX_COMMAND in .env to the full path of codex.exe."
        )
        log_data.update({"finished_at": time.time(), "error": message})
        log_path = write_log(settings, job, log_data)
        return {
            "state": "failed",
            "result": "",
            "error": message,
            "stdout": "",
            "stderr": str(exc),
            "log_path": log_path,
        }


def worker_headers(settings: WorkerSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.worker_token}"}


def run_once(settings: WorkerSettings, client: httpx.Client) -> bool:
    response = client.get("/worker/jobs/next", headers=worker_headers(settings))
    if response.status_code == 204:
        return False
    response.raise_for_status()
    job = response.json()
    logger.info("Running %s (%s)", job["id"], job["command"])
    completion = run_codex_job(settings, job)
    complete_response = client.post(
        f"/worker/jobs/{job['id']}/complete",
        json=completion,
        headers=worker_headers(settings),
    )
    complete_response.raise_for_status()
    logger.info("Completed %s as %s", job["id"], completion["state"])
    return True


def validate_settings(settings: WorkerSettings) -> None:
    missing = []
    if not settings.relay_url:
        missing.append("RELAY_URL")
    if not settings.worker_token:
        missing.append("RELAY_WORKER_TOKEN")
    if not settings.codex_workspace:
        missing.append("CODEX_WORKSPACE")
    if missing:
        raise SystemExit(f"Missing required settings: {', '.join(missing)}")
    if not Path(settings.codex_workspace).exists():
        raise SystemExit(f"CODEX_WORKSPACE does not exist: {settings.codex_workspace}")


def main() -> None:
    settings = load_worker_settings()
    validate_settings(settings)
    with httpx.Client(base_url=settings.relay_url, timeout=30) as client:
        while True:
            try:
                did_work = run_once(settings, client)
            except httpx.HTTPError as exc:
                logger.warning("Worker request failed: %s", exc)
                did_work = False
            if not did_work:
                time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
