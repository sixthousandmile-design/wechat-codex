from __future__ import annotations


def truncate_text(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 40)].rstrip() + "\n...[truncated]"


def help_text() -> str:
    return (
        "Commands:\n"
        "ask <question>\n"
        "plan <task>\n"
        "run <task>\n"
        "approve <job_id>\n"
        "status <job_id>"
    )
