# Messaging-to-Codex Interface

This project exposes a small public relay for WhatsApp/WeChat webhooks and a local Windows worker that polls the relay and runs `codex exec` on this PC.

## 1. Install

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set:

- `RELAY_WORKER_TOKEN`
- `ALLOWED_SENDERS`
- WhatsApp settings, or WeChat settings
- `RELAY_URL`
- `CODEX_WORKSPACE`

## 2. Run The Relay

On the public HTTPS host:

```powershell
.\.venv\Scripts\python -m uvicorn relay:app --host 0.0.0.0 --port 8000
```

Configure provider webhooks:

- WhatsApp callback URL: `https://your-host/webhook/whatsapp`
- WeChat callback URL: `https://your-host/webhook/wechat`

## 3. Run The Local Worker

On this PC:

```powershell
.\.venv\Scripts\python worker.py
```

For durability, create a Windows Task Scheduler task that runs the command above at login.

If the worker says it cannot find Codex, set `CODEX_COMMAND` in `.env` to the full
`codex.exe` path under your VS Code extension folder, for example:

```powershell
CODEX_COMMAND=C:\Users\xinleiy\.vscode\extensions\openai.chatgpt-26.623.141536-win32-x64\bin\windows-x86_64\codex.exe
```

## 4. Message Commands

- `ask <question>`: read-only Codex job
- `plan <task>`: read-only Codex planning job
- `run <task>`: create a pending workspace-write job
- `approve <job_id>`: run a pending job
- `status <job_id>`: get status and latest result

The worker never uses `danger-full-access`. Mutating work only runs after `approve <job_id>`.
