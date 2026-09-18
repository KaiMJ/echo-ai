# Echo

A small local coding agent for Linux. Gemma runs on vLLM; coding tools run in disposable Docker workspaces. Your original checkout is never mounted into a tool container.

## Features

- **Interactive Chat**: Streamed terminal chat with terminal control.
- **Coding Tools**: Read, search, edit, write, and execute bash commands.
- **Session Management**: Persistent SQLite-backed sessions with the ability to resume.
- **Non-interactive Execution**: Run tasks and generate patches automatically.
- **Subagent Delegation**: Delegate bounded read, search, or review tasks.

## Quick Start

### 1. Setup
Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, and Docker.

```bash
# Sync dependencies
uv sync --locked

# Build the sandbox image
docker build -t echo-ai-sandbox:local .

# Configure environment (copy .env.example to .env first)
cp .env.example .env
uv run echo-ai config
```

### 2. Usage

**Interactive Mode**
Start a chat session in your current repository:
```bash
uv run echo-ai chat --repo .
```
*   `Enter`: Send message.
*   `Alt+Enter`: Newline.
*   `Ctrl-C`: Cancel current turn.
*   `Ctrl-D`: Exit.
*   Commands: `/help`, `/status`, `/diff`, `/exit`.

**Automated Mode**
Run a task without an interactive terminal:
```bash
uv run echo-ai run --repo . "Find and fix a small bug, then run relevant tests."
```

**Session Management**
Manage previous sessions and apply changes:
```bash
uv run echo-ai sessions             # List sessions
uv run echo-ai resume <SESSION_ID>   # Resume a session
uv run echo-ai diff <SESSION_ID> --output change.patch # Export a patch
```

## Security & Limits

- **Isolation**: Tools run in a Docker container with no network access.
- **Workspace Copy**: The agent works on a copy of your repository (up to 512 MiB). Symlinks and sensitive credential directories are excluded.
- **Filesystem**: The supplied image contains Python, `pytest`, Bash, Git, and `ripgrep`.

## Documentation

- [Architecture](docs/architecture.md): Code map and session behavior.
- [Inference](docs/inference.md): GPU deployment and resizing.
- [Sandbox limits](docs/security.md): Isolation details and risks.
