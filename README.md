# Echo

A small local coding agent for Linux. Gemma runs on vLLM; coding tools edit your checkout directly by default. Use `--sandbox` to work in a disposable Docker copy instead.

## Features

- **Interactive Chat**: Streamed terminal chat with terminal control.
- **Coding Tools**: Read, search, edit, write, and execute bash commands.
- **Session Management**: Persistent SQLite-backed sessions with the ability to resume.
- **Non-interactive Execution**: Run tasks and generate patches automatically.
- **Subagent Delegation**: Delegate bounded read, search, or review tasks.

## Quick Start

### 1. Setup
Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, Bash, and ripgrep. Docker is needed only for `--sandbox`.

```bash
# Sync dependencies
uv sync --locked

# Optional: build the image for --sandbox
docker build -t echo-ai-sandbox:local .

# Configure environment (copy .env.example to .env first)
cp .env.example .env
uv run echo-ai config
```

### 2. Usage

**Interactive Mode**
Start a chat session in your current repository:
```bash
uv run echo-ai
```


**Session Management**
Manage previous sessions and apply changes:
```bash
uv run echo-ai sessions             # List this repository
uv run echo-ai sessions --all       # Include other repositories and review sessions
uv run echo-ai chat --resume <ID>   # Resume latest session by default
uv run echo-ai resume <ID>          # Resume latest session by default
uv run echo-ai diff <SESSION_ID> --output change.patch # Export a patch
uv run echo-ai run                  # non-interactive
uv run echo-ai chat --sandbox       # run tools / edits in sandbox
```

## Security & Limits

**shell commands** Currenlty does not use docker.

With `--sandbox`:

- **Isolation**: Tools run in a Docker container with no network access.
- **Workspace Copy**: The agent works on a copy of your repository (up to 512 MiB). Symlinks and sensitive credential directories are excluded.
- **Filesystem**: The supplied image contains Python, `pytest`, Bash, Git, and `ripgrep`.

## Configuration

```bash
# After editing echo.yaml
uv run echo-ai # or
uv sync --locked

# after editing sandbox
docker build -t echo-ai-sandbox:local .

# after updating inference service
docker compsoe up -d # or
docker compose up -d --force-recreate

# delete all sessions
~/.local/share/echo-ai/ # ECHO_STATE_DIR
```
