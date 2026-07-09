from __future__ import annotations


def test_relay_imports() -> None:
    import relay

    assert relay.app.title == "Messaging-to-Codex Relay"


def test_worker_imports() -> None:
    import worker

    assert worker.build_prompt({"command": "ask", "prompt": "hello", "run_mode": "read-only"})
